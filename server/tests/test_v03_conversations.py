"""Full isolated caller/admin/phone contract, not real upstream delivery proof."""

import secrets
import sqlite3
import pytest
from wechat_bridge.storage.database import Store
from test_portal import portal, ADMIN, ORIGIN, login, send


def test_full_recorded_pagination_shared_states_and_encrypted_restore(portal, tmp_path):
    store, client, auth, _, chats, _, key = portal
    login(client)
    cid = chats[0]["id"]
    for i in range(151):
        store.portal.add(
            cid, "user", "admin", "private-history-" + str(i), "pending", inbox_id=None
        )
    seen = []
    before = 0
    while True:
        data = client.get(
            "/admin/api/conversations/" + cid + "/messages",
            headers=ADMIN,
            params={"before": before},
        ).json()
        seen = [m["id"] for m in data["messages"]] + seen
        if not data["has_older"]:
            break
        before = data["messages"][0]["id"]
    assert len(seen) == 151 and seen == sorted(set(seen))
    reads = [tuple(r) for r in store.db.execute("SELECT * FROM web_reads")]
    states = client.get(
        "/admin/api/conversations/" + cid + "/message-states",
        headers=ADMIN,
        params={"ids": ",".join(map(str, seen[:100]))},
    )
    assert states.status_code == 200 and len(states.json()["states"]) == 100
    assert client.get(
        "/chat/api/conversations/" + cid + "/message-states", params={"ids": str(seen[0])}
    ).json() == {"states": [{"id": seen[0], "status": "pending"}]}
    assert [tuple(r) for r in store.db.execute("SELECT * FROM web_reads")] == reads
    assert (
        client.get(
            "/admin/api/conversations/" + cid + "/message-states",
            headers=ADMIN,
            params={"ids": ",".join(map(str, seen))},
        ).status_code
        == 422
    )
    path = tmp_path / "recovered.sqlite3"
    backup = sqlite3.connect(path)
    store.db.backup(backup)
    backup.close()
    recovered = Store(path, key)
    try:
        assert recovered.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            recovered.portal.history(cid, limit=100)["messages"][-1]["text"]
            == "private-history-150"
        )
        assert (
            recovered.clients.authenticate(auth["Authorization"][7:]).id
            == store.clients.authenticate(auth["Authorization"][7:]).id
        )
    finally:
        recovered.close()


def create(client, client_id, text="请核对开发结果", request_id=None):
    return client.post(
        "/admin/api/conversations",
        headers=ADMIN,
        json={
            "client_id": client_id,
            "name": "主动沟通",
            "text": text,
            "request_id": request_id or secrets.token_hex(16),
        },
    )


def test_admin_atomic_first_message_mobile_sync_explicit_claim_and_reply(portal):
    store, client, auth, other, chats, calls, _ = portal
    app = store.db.execute(
        "SELECT client_id FROM conversations WHERE id=?", (chats[0]["id"],)
    ).fetchone()[0]
    request_id = secrets.token_hex(16)
    first = create(client, app, request_id=request_id)
    assert first.status_code == 200
    cid = first.json()["conversation"]["id"]
    second = create(client, app, request_id=request_id)
    assert (
        second.json()["duplicate"]
        and second.json()["message"]["id"] == first.json()["message"]["id"]
    )
    assert create(client, app, "不同内容", request_id).status_code == 409
    login(client)
    phone = client.get(f"/chat/api/conversations/{cid}/messages").json()
    assert phone["messages"][0]["source"] == "admin" and phone["messages"][0]["status"] == "pending"
    inbox = client.get("/api/inbox", headers=auth, params={"conversation_id": cid}).json()[
        "messages"
    ]
    assert len(inbox) == 1 and inbox[0]["source"] == "admin" and inbox[0]["processing"] is None
    id = inbox[0]["id"]
    assert (
        client.get(f"/admin/api/conversations/{cid}/messages", headers=ADMIN).json()["messages"][0][
            "status"
        ]
        == "client_read"
    )
    body = {"request_id": secrets.token_hex(16)}
    assert client.post(f"/api/inbox/{id}/claim", headers=other, json=body).status_code == 404
    claim = client.post(f"/api/inbox/{id}/claim", headers=auth, json=body)
    assert claim.status_code == 200 and claim.json()["processing"]["status"] == "claimed"
    assert client.post(f"/api/inbox/{id}/claim", headers=auth, json=body).json()["duplicate"]
    assert (
        client.post(
            f"/api/inbox/{id}/claim", headers=auth, json={"request_id": secrets.token_hex(16)}
        ).status_code
        == 409
    )
    report = {
        "claim_id": body["request_id"],
        "request_id": secrets.token_hex(16),
        "status": "completed",
        "result": "核对完成，已记录处理结果",
    }
    assert client.post(f"/api/inbox/{id}/report", headers=auth, json=report).status_code == 200
    assert client.post(f"/api/inbox/{id}/report", headers=auth, json=report).json()["duplicate"]
    assert (
        client.post(
            f"/api/inbox/{id}/report", headers=auth, json=dict(report, result="changed")
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/inbox/{id}/report",
            headers=auth,
            json=dict(report, request_id=secrets.token_hex(16), status="processing"),
        ).status_code
        == 409
    )
    client.get("/api/inbox", headers=auth, params={"conversation_id": cid})
    assert (
        client.get(f"/chat/api/conversations/{cid}/messages").json()["messages"][0]["status"]
        == "completed"
    )
    assert (
        send(client, auth, cid, text="已回复核对结果", key=secrets.token_hex(16)).status_code == 200
    )
    history = client.get(f"/admin/api/conversations/{cid}/messages", headers=ADMIN).json()[
        "messages"
    ]
    assert len(history) == 2 and history[-1]["text"] == "已回复核对结果" and len(calls) == 1
    assert report["result"] not in "\n".join(store.db.iterdump())


def test_no_orphan_on_first_message_failure_disabled_app_and_restore(portal, monkeypatch, tmp_path):
    store, client, auth, _, chats, _, key = portal
    app = store.db.execute(
        "SELECT client_id FROM conversations WHERE id=?", (chats[0]["id"],)
    ).fetchone()[0]
    before = store.db.execute("SELECT count(*) FROM conversations").fetchone()[0]
    with monkeypatch.context() as scoped:

        def fail(*args, **kwargs):
            raise RuntimeError("injected persistence failure")

        scoped.setattr(store.portal, "reply", fail)
        with pytest.raises(RuntimeError):
            create(client, app)
    assert store.db.execute("SELECT count(*) FROM conversations").fetchone()[0] == before
    assert store.db.execute("SELECT count(*) FROM admin_conversation_requests").fetchone()[0] == 0
    assert create(client, app, text=" ").status_code == 422
    store.clients.revoke(app)
    assert create(client, app).status_code == 409
    backup = sqlite3.connect(tmp_path / "restored.sqlite3")
    store.db.backup(backup)
    assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    backup.close()


def test_admin_mobile_reply_sources_history_and_lifecycle_share_one_ledger(portal):
    store, client, auth, _, chats, _, _ = portal
    login(client)
    cid = chats[0]["id"]
    body = {"text": "两端共享的消息", "request_id": secrets.token_hex(16)}
    assert (
        client.post(
            f"/admin/api/conversations/{cid}/messages", headers=ADMIN, json=body
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/chat/api/conversations/{cid}/messages", headers=ORIGIN, json=body
        ).status_code
        == 200
    )
    assert len(client.get(f"/chat/api/conversations/{cid}/messages").json()["messages"]) == 2
    assert (
        client.post(
            f"/admin/api/conversations/{cid}/archive", headers=ADMIN, json={"archived": True}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/admin/api/conversations/{cid}/messages",
            headers=ADMIN,
            json=dict(body, request_id=secrets.token_hex(16)),
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/admin/api/conversations/{cid}/archive", headers=ADMIN, json={"archived": False}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/admin/api/conversations/{cid}/pin", headers=ADMIN, json={"pinned": True}
        ).status_code
        == 200
    )
    assert next(
        c for c in client.get("/chat/api/conversations").json()["conversations"] if c["id"] == cid
    )["pinned"]
