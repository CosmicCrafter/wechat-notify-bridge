"""Preparation retry retains one logical message, and cannot retry unknown sends."""

import httpx
from test_feishu import feishu, send
from test_portal import ADMIN, portal


def test_preparation_retry_reuses_message_and_retains_attempt_evidence(feishu):
    portal, calls = feishu
    store, client, *_ = portal
    adapter = client.app.state.channels.feishu
    failing = [True]

    def upstream(request):
        calls.append((request, {}))
        if request.url.path.endswith("/internal"):
            if failing[0]:
                raise httpx.ConnectError("offline", request=request)
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "temporary-test", "expire": 7200}
            )
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "temporary-id"}})

    adapter.transport = httpx.MockTransport(upstream)
    first = send(feishu).json()
    assert first["status"] == "not_sent"
    assert send(feishu).json()["duplicate"] and len(calls) == 1
    rows = client.get("/admin/api/deliveries", headers=ADMIN, params={"q": "feishu-event"}).json()[
        "deliveries"
    ]
    assert len(rows) == 1 and rows[0]["retryable"] and len(rows[0]["attempts"]) == 1
    failing[0] = False
    second = send(feishu, retry_preparation=True).json()
    assert second["status"] == "api_accepted" and second["message_id"] == first["message_id"]
    assert store.db.execute("SELECT count(*) FROM chat_messages").fetchone()[0] == 1
    evidence = client.get("/admin/api/deliveries", headers=ADMIN).json()["deliveries"][0]
    assert [r["status"] for r in evidence["attempts"]] == ["not_sent", "api_accepted"]
    assert not evidence["retryable"]
    assert (
        client.post(
            "/admin/api/deliveries/" + evidence["key"] + "/retry-preparation",
            headers=ADMIN,
            json={},
        ).status_code
        == 409
    )
    assert send(feishu, retry_preparation=True).status_code == 409


def test_unknown_send_refuses_explicit_retry_and_delete_removes_request_body(feishu):
    portal, calls = feishu
    store, client, *_ = portal
    adapter = client.app.state.channels.feishu

    def upstream(request):
        calls.append((request, {}))
        if request.url.path.endswith("/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "temporary-test", "expire": 7200}
            )
        raise httpx.ReadTimeout("unknown", request=request)

    adapter.transport = httpx.MockTransport(upstream)
    assert send(feishu).json()["status"] == "unconfirmed_do_not_retry"
    count = len(calls)
    assert send(feishu, retry_preparation=True).status_code == 409 and len(calls) == count
    row = client.get("/admin/api/deliveries", headers=ADMIN).json()["deliveries"][0]
    assert not row["retryable"]
    assert (
        client.post(
            "/admin/api/conversations/" + row["conversation_id"] + "/delete", headers=ADMIN, json={}
        ).status_code
        == 200
    )
    assert store.delivery_journal.request(row["key"]) is None
