"""Archive does not close; stop needs a current fenced external acknowledgement."""

import secrets
import sqlite3
from test_portal import portal as portal_fixture, ADMIN
from test_f02_receivers import protected, reply
from wechat_bridge.storage.database import Store

portal = portal_fixture


def test_archive_mute_and_stop_are_independent_and_do_not_affect_peer(portal):
    store, client, auth, *_ = portal
    a, ra, _ = protected(client, auth, "F02-life-A", "生命周期A")
    b, rb, _ = protected(client, auth, "F02-life-B", "生命周期B")
    for cid, headers in ((a, ra), (b, rb)):
        assert (
            client.post(
                "/api/conversations/" + cid + "/monitor",
                headers=headers,
                json={"status": "running", "request_id": secrets.token_hex(16)},
            ).status_code
            == 200
        )
    result = client.post(
        "/admin/api/conversations/" + a + "/archive",
        headers=ADMIN,
        json={"archived": True, "visibility_only": True},
    )
    assert result.status_code == 200 and result.json()["archived"] and result.json()["can_reply"]
    assert store.receivers.summary(a)["status"] == "active"
    assert client.post(
        "/admin/api/conversations/" + a + "/mute", headers=ADMIN, json={"muted": True}
    ).json()["muted"]
    assert store.lifecycle.public(a)["monitor_status"] == "running"
    assert (
        client.post(
            "/api/conversations/" + a + "/state", headers=ra, json={"active": False}
        ).status_code
        == 409
    )
    iid = reply(client, a)
    assert client.get("/api/inbox", headers=ra, params={"conversation_id": a}).status_code == 200
    stopped = client.post(
        "/admin/api/conversations/" + a + "/stop",
        headers=ADMIN,
        json={"request_id": secrets.token_hex(16)},
    ).json()
    assert stopped["monitor_status"] == "stop_requested"
    assert store.lifecycle.public(b)["monitor_status"] == "running"
    ack = {"status": "stopped", "stop_id": stopped["stop_id"], "request_id": secrets.token_hex(16)}
    assert (
        client.post("/api/conversations/" + a + "/monitor", headers=ra, json=ack).status_code == 409
    )
    claim = client.post(
        "/api/inbox/" + str(stopped["stop_inbox_id"]) + "/claim",
        headers=ra,
        json={"request_id": secrets.token_hex(16)},
    ).json()["processing"]
    ack.update(claim_id=claim["claim_id"], generation=claim["generation"])
    result = client.post("/api/conversations/" + a + "/monitor", headers=ra, json=ack)
    assert result.status_code == 200 and result.json()["monitor_status"] == "stopped"
    assert not store.portal.owner_chat(a)["active"] and store.portal.owner_chat(b)["active"]
    assert store.receivers.summary(a)["status"] == "revoked"
    assert store.claims.public(stopped["stop_inbox_id"])["status"] == "completed"
    assert (
        client.get("/api/conversations/" + a + "/lifecycle", headers=auth).json()["monitor_status"]
        == "stopped"
    )


def test_offline_stop_is_unconfirmed_and_legacy_closed_chat_does_not_reopen(portal, tmp_path):
    store, client, auth, _, chats, *rest = portal
    cid, scoped, _ = protected(client, auth, "F02-offline", "离线停止")
    first = client.post(
        "/admin/api/conversations/" + cid + "/stop",
        headers=ADMIN,
        json={"request_id": secrets.token_hex(16)},
    ).json()
    second = client.post(
        "/admin/api/conversations/" + cid + "/stop",
        headers=ADMIN,
        json={"request_id": secrets.token_hex(16)},
    ).json()
    assert first["stop_message_id"] == second["stop_message_id"]
    store.db.execute(
        "UPDATE conversation_runtime SET stop_deadline=0 WHERE conversation_id=?", (cid,)
    )
    assert (
        store.lifecycle.public(cid)["monitor_status"] == "stop_unconfirmed"
        and store.portal.owner_chat(cid)["active"]
    )
    legacy = chats[0]["id"]
    store.conversations.set_active(
        store.clients.authenticate(auth["Authorization"][7:]).id, legacy, False
    )
    assert (
        client.post(
            "/admin/api/conversations/" + legacy + "/archive",
            headers=ADMIN,
            json={"archived": False, "visibility_only": True},
        ).status_code
        == 200
    )
    assert not store.portal.owner_chat(legacy)["active"]
    target = sqlite3.connect(tmp_path / "restored.sqlite3")
    store.db.backup(target)
    target.close()
    restored = Store(tmp_path / "restored.sqlite3", rest[-1])
    try:
        assert restored.lifecycle.public(cid)["monitor_status"] == "stop_unconfirmed"
        assert not restored.portal.owner_chat(legacy)["active"]
        assert restored.portal.history(cid)["messages"]
    finally:
        restored.close()
