"""v0.3 E0 regressions: isolated stores and mock platform only."""

import asyncio
import json
import httpx
from test_service import store
from test_feishu import feishu, send, CONFIG
from test_portal import portal, login, ORIGIN
from wechat_bridge.services.bridge import Bridge


def test_slow_wechat_does_not_hold_shared_state_lock_and_dedup_is_preserved(store):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def handler(request):
            calls.append(request)
            started.set()
            await release.wait()
            return httpx.Response(200, json={"ret": 0})

        bridge = Bridge(store, httpx.MockTransport(handler))
        sending = asyncio.create_task(bridge.send("slow", "slow-event", "codex"))
        duplicate = None
        try:
            await asyncio.wait_for(started.wait(), 1)
            await asyncio.wait_for(bridge.lock.acquire(), 0.2)
            try:
                store.set("reply-during-send", True)
            finally:
                bridge.lock.release()
            duplicate = asyncio.create_task(bridge.send("slow", "slow-event", "codex"))
        finally:
            release.set()
            result = await sending
            if duplicate:
                second = await duplicate
                assert second["duplicate"] is True
            await bridge.close()
        assert result["status"] == "api_accepted"
        assert len(calls) == 1
        assert store.get("reply-during-send") is True

    asyncio.run(run())


def task(feishu):
    portal, calls = feishu
    cid = portal[4][0]["id"]
    body = dict(
        channel="feishu",
        conversation_id=cid,
        dedup_key="projection-test",
        title="Confirm",
        prompt="Choose",
        options=[{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}],
    )
    result = portal[1].post("/api/task-cards", headers=portal[2], json=body)
    assert result.status_code == 200
    return cid, result.json()["task"]["id"]


def test_phone_task_answer_projects_feishu_card_without_second_decision(feishu):
    portal, calls = feishu
    cid, tid = task(feishu)
    client = portal[1]
    login(client)
    body = {"request_id": "projection-answer-12345", "choice_id": "yes", "text": ""}
    url = f"/chat/api/conversations/{cid}/tasks/{tid}/answer"
    r = client.post(url, headers=ORIGIN, json=body)
    assert r.status_code == 200
    assert r.json()["task"]["status"] == "answered"
    assert any(request.method == "PATCH" for request, _ in calls)
    count = portal[0].db.execute("SELECT count(*) FROM inbox").fetchone()[0]
    assert client.post(url, headers=ORIGIN, json=body).json()["duplicate"] is True
    assert portal[0].db.execute("SELECT count(*) FROM inbox").fetchone()[0] == count


def test_token_preparation_failure_is_not_an_unknown_message_send(feishu):
    portal, calls = feishu
    adapter = portal[1].app.state.channels.feishu

    def failure(request):
        assert request.url.path.endswith("/internal")
        calls.append((request, {}))
        raise httpx.ConnectError("offline", request=request)

    adapter.transport = httpx.MockTransport(failure)
    result = send(feishu).json()
    assert result["status"] == "not_sent"
    assert result["diagnostics"]["phase"] == "preparation"
    assert result["diagnostics"]["platform_request_started"] is False
    assert not any("/im/v1/messages" in str(request.url) for request, _ in calls)


def test_card_projection_failure_keeps_decision_and_replay_retries_projection(feishu):
    portal, calls = feishu
    adapter = portal[1].app.state.channels.feishu
    failing = [True]

    def handler(request):
        payload = json.loads(request.content)
        calls.append((request, payload))
        if request.url.path.endswith("/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "fixture-token", "expire": 7200}
            )
        if request.method == "PATCH":
            if failing[0]:
                raise httpx.ConnectError("offline", request=request)
            return httpx.Response(200, json={"code": 0})
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "om_projection"}})

    adapter.transport = httpx.MockTransport(handler)
    cid, tid = task(feishu)
    client = portal[1]
    login(client)
    body = {"request_id": "projection-failure-12345", "choice_id": "yes", "text": ""}
    url = f"/chat/api/conversations/{cid}/tasks/{tid}/answer"
    first = client.post(url, headers=ORIGIN, json=body)
    assert first.status_code == 200 and first.json()["projection"]["status"] == "failed"
    assert portal[0].portal.tasks.get(cid, tid)["status"] == "answered"
    count = portal[0].db.execute("SELECT count(*) FROM inbox").fetchone()[0]
    failing[0] = False
    second = client.post(url, headers=ORIGIN, json=body)
    assert second.json()["duplicate"] is True
    assert second.json()["projection"]["status"] == "synced"
    assert portal[0].db.execute("SELECT count(*) FROM inbox").fetchone()[0] == count


def test_actual_message_post_timeout_remains_unknown_and_never_resends(feishu):
    portal, calls = feishu
    adapter = portal[1].app.state.channels.feishu

    def handler(request):
        calls.append((request, {}))
        if request.url.path.endswith("/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "fixture-token", "expire": 7200}
            )
        raise httpx.ReadTimeout("timed out", request=request)

    adapter.transport = httpx.MockTransport(handler)
    first = send(feishu).json()
    second = send(feishu).json()
    assert first["status"] == "unconfirmed_do_not_retry"
    assert first["diagnostics"]["platform_request_started"] is True
    assert second["duplicate"] is True
    assert len([r for r, _ in calls if "/im/v1/messages" in str(r.url)]) == 1
