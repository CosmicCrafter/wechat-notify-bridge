"""Real API, independent fake Feishu A/B, grants, suppression and one-task fallback."""

import json
import secrets
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from test_portal import portal as portal_fixture, ADMIN
from test_feishu import feishu as feishu_fixture, CONFIG
from test_portal import login, ORIGIN

portal = portal_fixture
feishu = feishu_fixture


@pytest.fixture
def routing(feishu):
    value, calls = feishu
    store, client, auth, other, chats, *_ = value
    hub = client.app.state.channels
    b = store.bots.create("紧急测试B", "feishu")["id"]
    adapter = hub.adapter(b)
    adapter.configure({**CONFIG, "app_id": "cli_f02B", "owner_open_id": "ou_f02B"})
    sent = []

    def transport(request):
        if request.url.path.endswith("/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "f02-test-token", "expire": 7200}
            )
        sent.append(json.loads(request.content))
        return httpx.Response(
            200, json={"code": 0, "data": {"message_id": "om_" + secrets.token_hex(16)}}
        )

    adapter.transport = httpx.MockTransport(transport)
    app = store.clients.authenticate(auth["Authorization"][7:]).id
    store.bots.set_grants(app, ["default", "feishu-default", b], "feishu-default")
    policy = {
        "default_bot": "feishu-default",
        "urgent_bot": b,
        "urgent_enabled": True,
        "interval_seconds": 60,
        "fallback_bot": None,
    }
    assert (
        client.post(
            "/admin/api/clients/" + app + "/notification-policy", headers=ADMIN, json=policy
        ).status_code
        == 200
    )
    return value, b, sent, policy, app


def send(value, key, level="info", **kwargs):
    _, client, auth, _, chats, *_ = value
    return client.post(
        "/api/messages",
        headers=auth,
        json={
            "text": "F02 notification " + key,
            "dedup_key": key,
            "conversation_id": chats[0]["id"],
            "level": level,
            **kwargs,
        },
    )


def test_default_preference_explicit_and_authorized_urgent_with_dedup(routing):
    value, b, sent, policy, app = routing
    store, client, auth, _, chats, *_ = value
    cid = chats[0]["id"]
    assert (
        client.get("/admin/api/clients/" + app + "/notification-policy", headers=ADMIN).json()[
            "policy"
        ]["urgent_enabled"]
        is True
    )
    assert (
        b
        not in client.get(
            "/admin/api/conversations/" + cid + "/notification-preference", headers=ADMIN
        ).json()["bot_ids"]
    )
    assert (
        client.post(
            "/admin/api/conversations/" + cid + "/notification-preference",
            headers=ADMIN,
            json={"bot_id": b},
        ).status_code
        == 403
    )
    normal = send(value, "normal")
    assert normal.status_code == 200 and normal.json()["bot_id"] == "feishu-default"
    assert (
        client.post(
            "/admin/api/conversations/" + cid + "/notification-preference",
            headers=ADMIN,
            json={"bot_id": "default"},
        ).status_code
        == 200
    )
    preference = send(value, "preference")
    assert preference.json()["bot_id"] == "default"
    urgent = send(value, "urgent", "urgent")
    assert urgent.status_code == 200 and urgent.json()["bot_id"] == b
    assert send(value, "urgent", "urgent").json()["duplicate"] and len(sent) == 1
    assert (
        client.get(
            "/api/deliveries", headers=auth, params={"dedup_key": "urgent", "conversation_id": cid}
        ).json()["bot_id"]
        == b
    )
    explicit = send(value, "explicit", bot_id="feishu-default")
    assert explicit.json()["bot_id"] == "feishu-default"
    assert send(value, "limited", "urgent").status_code == 429
    policy["urgent_enabled"] = False
    assert (
        client.post(
            "/admin/api/clients/" + app + "/notification-policy", headers=ADMIN, json=policy
        ).status_code
        == 200
    )
    assert send(value, "denied", "urgent").status_code == 403


def test_muted_message_and_task_remain_one_record_and_do_not_call_platform(routing):
    value, b, sent, _, _ = routing
    store, client, auth, _, chats, calls, *_ = value
    cid = chats[0]["id"]
    assert (
        client.post(
            "/admin/api/conversations/" + cid + "/mute", headers=ADMIN, json={"muted": True}
        ).status_code
        == 200
    )
    first = send(value, "muted")
    assert first.status_code == 200 and first.json()["status"] == "muted"
    assert send(value, "muted").json()["duplicate"]
    assert not sent and not calls
    task = {
        "conversation_id": cid,
        "dedup_key": "muted-task",
        "title": "保留任务",
        "prompt": "不会因为静音丢失",
        "mode": "input",
        "options": [],
    }
    reply = client.post("/api/task-cards", headers=auth, json=task)
    assert reply.status_code == 200 and reply.json()["status"] == "muted"
    assert store.db.execute("SELECT count(*) FROM task_cards").fetchone()[0] == 1
    assert len(store.portal.history(cid)["messages"]) == 2
    assert send(value, "still-urgent", "urgent").json()["bot_id"] == b and len(sent) == 1


def test_preflight_fallback_has_one_business_task_and_no_unknown_retry(routing):
    value, b, sent, policy, app = routing
    store, client, auth, _, chats, *_ = value
    cid = chats[0]["id"]
    policy["fallback_bot"] = "feishu-default"
    assert (
        client.post(
            "/admin/api/clients/" + app + "/notification-policy", headers=ADMIN, json=policy
        ).status_code
        == 200
    )
    store.bots.update(b, "紧急测试B", False)
    body = {
        "conversation_id": cid,
        "dedup_key": "fallback-task",
        "title": "唯一任务",
        "prompt": "不要复制业务任务",
        "mode": "input",
        "options": [],
        "level": "urgent",
    }
    result = client.post("/api/task-cards", headers=auth, json=body)
    assert result.status_code == 200 and result.json()["bot_id"] == "feishu-default"
    assert len(result.json()["notification_route"]["attempts"]) == 2
    assert store.db.execute("SELECT count(*) FROM task_cards").fetchone()[0] == 1
    assert client.post("/api/task-cards", headers=auth, json=body).json()["duplicate"]
    assert store.db.execute("SELECT count(*) FROM task_cards").fetchone()[0] == 1

    def timeout(request):
        raise httpx.ReadTimeout("test-timeout", request=request)

    store.bots.update(b, "紧急测试B", True)
    client.app.state.channels.adapter(b).transport = httpx.MockTransport(timeout)
    # The first urgent has a ledger; another request remains rate limited, never secretly switches targets.
    assert send(value, "unknown-urgent", "urgent").status_code == 429
    store.db.execute("UPDATE notification_routes SET created_at=0")
    adapter = client.app.state.channels.adapter(b)
    adapter.token = "test-token"
    adapter.token_until = time.time() + 300
    unknown = send(value, "send-timeout", "urgent")
    assert unknown.status_code == 200 and unknown.json()["status"] == "unconfirmed_do_not_retry"
    assert unknown.json()["bot_id"] == b
    assert len(unknown.json()["notification_route"]["attempts"]) == 1
    assert send(value, "send-timeout", "urgent").json()["duplicate"]


def test_explicit_target_never_falls_back_and_revoked_grant_cannot_retry(routing):
    value, b, _, policy, app = routing
    store, client, auth, _, chats, *_ = value
    policy["fallback_bot"] = "feishu-default"
    client.post("/admin/api/clients/" + app + "/notification-policy", headers=ADMIN, json=policy)
    store.bots.update(b, "紧急测试B", False)
    first = send(value, "explicit-failed", "urgent", bot_id=b)
    assert first.json()["status"] == "not_sent" and first.json()["bot_id"] == b
    assert not first.json()["notification_route"]["rule"].endswith("fallback")
    store.bots.set_grants(app, ["default", "feishu-default"], "feishu-default")
    assert send(value, "explicit-failed", "urgent", bot_id=b).status_code == 403
    assert (
        send(value, "explicit-failed", "urgent", bot_id=b, retry_preparation=True).status_code
        == 403
    )


def test_muted_dedup_survives_unmute_without_policy_and_sqlite_restore(routing, tmp_path):
    value, _, sent, _, app = routing
    store, client, auth, _, chats, calls, *_ = value
    cid = chats[0]["id"]
    store.db.execute("DELETE FROM notification_policies WHERE client_id=?", (app,))
    client.post("/admin/api/conversations/" + cid + "/mute", headers=ADMIN, json={"muted": True})
    assert send(value, "quiet-once").json()["status"] == "muted"
    backup = tmp_path / "consistent.sqlite3"
    with sqlite3.connect(backup) as target:
        store.db.backup(target)
    from wechat_bridge.storage.database import Store
    from wechat_bridge.services.notification_routing import NotificationRouting
    from types import SimpleNamespace

    restored = Store(backup, value[-1])
    try:
        routes = NotificationRouting(SimpleNamespace(store=restored)).rows()
        assert routes[0]["result"]["status"] == "muted"
        assert restored.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert len(restored.portal.history(cid)["messages"]) == 1
    finally:
        restored.close()
    client.post("/admin/api/conversations/" + cid + "/mute", headers=ADMIN, json={"muted": False})
    result = send(value, "quiet-once")
    assert result.json()["status"] == "muted" and result.json()["duplicate"]
    assert not sent and not calls


def test_admin_and_phone_competing_task_decisions_share_one_answer(routing):
    value, *_ = routing
    store, client, auth, _, chats, *_ = value
    cid = chats[0]["id"]
    task = client.post(
        "/api/task-cards",
        headers=auth,
        json={
            "conversation_id": cid,
            "dedup_key": "cross-endpoint-task",
            "title": "同一决定",
            "prompt": "两端同时答复，只有一个有效决定",
            "mode": "input",
            "options": [],
        },
    ).json()["task"]
    login(client)

    def answer(source):
        return client.post(
            f"/{source}/api/conversations/{cid}/tasks/{task['id']}/answer",
            headers=ADMIN if source == "admin" else ORIGIN,
            json={"request_id": secrets.token_hex(16), "text": source + "的决定"},
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(answer, ["admin", "chat"]))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert store.portal.tasks.get(cid, task["id"])["status"] == "answered"
    assert (
        store.db.execute("SELECT count(*) FROM inbox WHERE identity LIKE 'task:%'").fetchone()[0]
        == 1
    )
    assert (
        store.db.execute(
            "SELECT count(*) FROM chat_messages WHERE conversation_id=? AND direction='user'", (cid,)
        ).fetchone()[0]
        == 1
    )
