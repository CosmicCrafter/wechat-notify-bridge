"""F02-1 capability isolation on the actual HTTP stack and independent databases."""

import secrets
import sqlite3
from dataclasses import replace
import pytest
from test_portal import portal as portal_fixture, ADMIN
from wechat_bridge.storage.database import Store

portal = portal_fixture


def protected(client, auth, key, name):
    response = client.post(
        "/api/conversations",
        headers=auth,
        json={
            "conversation_key": key,
            "name": name,
            "receiver_mode": "protected",
            "host_type": "http",
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    setup = result["receiver_setup"]
    scoped = {**auth, "X-Notify-Receiver": setup["receiver_token"]}
    verified = client.post(
        "/api/receivers/verify", headers=scoped, json={"challenge": setup["challenge"]}
    )
    assert verified.status_code == 200
    return result["id"], scoped, setup


def reply(client, cid, text="给正确接收端的消息"):
    response = client.post(
        "/admin/api/conversations/" + cid + "/messages",
        headers=ADMIN,
        json={"text": text, "request_id": secrets.token_hex(16)},
    )
    assert response.status_code == 200
    return client.app.state.bridge.store.db.execute(
        "SELECT inbox_id FROM chat_messages WHERE id=?", (response.json()["message"]["id"],)
    ).fetchone()[0]


def test_one_app_two_scopes_no_extra_app_key_and_cross_conversation_denied(portal):
    store, client, auth, other, *_ = portal
    credentials = store.db.execute("SELECT count(*) FROM api_credentials").fetchone()[0]
    a, ra, setup = protected(client, auth, "F02-A01", "A01")
    b, rb, _ = protected(client, auth, "F02-A02", "A02")
    assert store.db.execute("SELECT count(*) FROM api_credentials").fetchone()[0] == credentials
    iid = reply(client, a)
    for headers in (auth, other, rb):
        assert client.get(
            "/api/inbox", headers=headers, params={"conversation_id": a}
        ).status_code in (403, 404)
        assert client.get("/api/conversations/" + a + "/history", headers=headers).status_code in (
            403,
            404,
        )
        assert client.post(
            "/api/inbox/" + str(iid) + "/claim",
            headers=headers,
            json={"request_id": secrets.token_hex(16)},
        ).status_code in (403, 404)
    result = client.get("/api/inbox", headers=ra).json()
    assert [m["conversation_id"] for m in result["messages"]] == [a]
    assert (
        client.get("/api/inbox", headers=ra, params={"include_unaddressed": True}).status_code
        == 403
    )
    assert client.get("/api/conversations", headers=ra).json()["conversations"][0]["id"] == a
    assert len(client.get("/api/conversations", headers=ra).json()["conversations"]) == 1
    assert (
        client.post(
            "/api/messages",
            headers=rb,
            json={"conversation_id": a, "text": "wrong", "dedup_key": "wrong"},
        ).status_code
        == 403
    )
    duplicate = client.post(
        "/api/conversations",
        headers=auth,
        json={"conversation_key": "F02-A01", "receiver_mode": "protected"},
    ).json()
    assert duplicate["id"] == a and "receiver_setup" not in duplicate
    assert setup["receiver_token"] not in "\n".join(store.db.iterdump())


def test_admin_first_message_waits_for_pairing_and_one_time_exchange(portal):
    store, client, auth, *_ = portal
    app = store.clients.authenticate(auth["Authorization"][7:]).id
    body = {
        "client_id": app,
        "name": "待绑定",
        "text": "首条消息",
        "request_id": secrets.token_hex(16),
        "receiver_mode": "protected",
    }
    first = client.post("/admin/api/conversations", headers=ADMIN, json=body).json()
    cid = first["conversation"]["id"]
    assert first["conversation"]["receiver"]["status"] == "waiting_binding"
    assert client.post("/admin/api/conversations", headers=ADMIN, json=body).json()["duplicate"]
    assert (
        client.get("/api/inbox", headers=auth, params={"conversation_id": cid}).status_code == 403
    )
    pair = client.post(
        "/admin/api/conversations/" + cid + "/receiver/pair",
        headers=ADMIN,
        json={"host_type": "http", "label": "独立接收器"},
    ).json()
    assert (
        client.post(
            "/admin/api/conversations/" + cid + "/receiver/pair", headers=auth, json={}
        ).status_code
        == 401
    )
    setup = client.post(
        "/api/receivers/exchange", headers=auth, json={"pairing_code": pair["pairing_code"]}
    ).json()
    assert (
        client.post(
            "/api/receivers/exchange", headers=auth, json={"pairing_code": pair["pairing_code"]}
        ).status_code
        == 400
    )
    scoped = {**auth, "X-Notify-Receiver": setup["receiver_token"]}
    assert (
        client.get("/api/inbox", headers=scoped, params={"conversation_id": cid}).status_code == 403
    )
    result = client.post(
        "/api/receivers/verify", headers=scoped, json={"challenge": setup["challenge"]}
    ).json()
    assert result["receiver"]["assurance"] == "conversation_capability"
    assert result["receiver"]["host_identity"] == "unverified"
    assert (
        len(
            client.get("/api/inbox", headers=scoped, params={"conversation_id": cid}).json()[
                "messages"
            ]
        )
        == 1
    )
    assert (
        client.post(
            "/admin/api/conversations/" + cid + "/receiver/pair", headers=ADMIN, json={}
        ).status_code
        == 409
    )


def test_observer_can_read_but_not_claim_or_report_and_revocation_invalidates(portal):
    store, client, auth, *_ = portal
    cid, primary, _ = protected(client, auth, "F02-role", "角色")
    iid = reply(client, cid)
    pair = client.post(
        "/admin/api/conversations/" + cid + "/receiver/pair",
        headers=ADMIN,
        json={"role": "observer"},
    ).json()
    observer = client.post(
        "/api/receivers/exchange", headers=auth, json={"pairing_code": pair["pairing_code"]}
    ).json()
    readonly = {**auth, "X-Notify-Receiver": observer["receiver_token"]}
    assert (
        client.post(
            "/api/receivers/verify", headers=readonly, json={"challenge": observer["challenge"]}
        ).status_code
        == 200
    )
    assert (
        client.get("/api/inbox", headers=readonly, params={"conversation_id": cid}).status_code
        == 200
    )
    assert (
        client.post(
            "/api/inbox/" + str(iid) + "/claim",
            headers=readonly,
            json={"request_id": secrets.token_hex(16)},
        ).status_code
        == 403
    )
    current = store.receivers.summary(cid)["binding_id"]
    assert (
        client.post(
            "/admin/api/conversations/" + cid + "/receiver/" + current + "/revoke",
            headers=ADMIN,
            json={},
        ).status_code
        == 200
    )
    assert (
        client.get("/api/inbox", headers=primary, params={"conversation_id": cid}).status_code
        == 403
    )


def test_expiration_app_revocation_and_receiver_validation_redacts_secrets(portal):
    store, client, auth, *_ = portal
    cid, scoped, setup = protected(client, auth, "F02-expiry", "到期")
    result = client.post(
        "/api/receivers/verify",
        headers=scoped,
        json={"challenge": setup["challenge"], "unexpected": setup["receiver_token"]},
    )
    assert result.status_code == 422 and setup["receiver_token"] not in result.text
    store.db.execute("UPDATE receiver_bindings SET expires_at=0 WHERE conversation_id=?", (cid,))
    assert (
        client.get("/api/inbox", headers=scoped, params={"conversation_id": cid}).status_code == 403
    )
    assert store.receivers.summary(cid)["status"] == "expired"
    cid, scoped, _ = protected(client, auth, "F02-revoke", "撤销")
    identity = store.clients.authenticate(auth["Authorization"][7:])
    store.clients.revoke(identity.id)
    assert (
        client.get("/api/inbox", headers=scoped, params={"conversation_id": cid}).status_code == 401
    )


def test_protected_capability_survives_consistent_database_restore(portal, tmp_path):
    store, client, auth, *rest = portal
    cid, scoped, _ = protected(client, auth, "F02-restore", "恢复")
    iid = reply(client, cid)
    restored = sqlite3.connect(tmp_path / "restored.sqlite3")
    store.db.backup(restored)
    restored.close()
    copy = Store(tmp_path / "restored.sqlite3", rest[-1])
    try:
        identity = copy.clients.authenticate(auth["Authorization"][7:])
        from wechat_bridge.storage.receivers import digest

        identity = replace(identity, receiver_hash=digest(scoped["X-Notify-Receiver"]))
        assert copy.receivers.authorize(identity, cid)
        assert copy.portal.history(cid)["messages"][0]["text"] == "给正确接收端的消息"
        assert copy.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        copy.close()
