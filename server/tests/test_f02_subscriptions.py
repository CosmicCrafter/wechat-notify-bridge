"""Subscription availability and receipt are independent of durable inbox execution."""

import asyncio
import base64
import json
import secrets
from test_portal import portal as portal_fixture, ADMIN
from test_f02_receivers import protected, reply

portal = portal_fixture


def test_expired_or_cancelled_subscription_keeps_inbox_and_archive_keeps_delivery(portal):
    store, client, auth, *_ = portal
    cid, scoped, _ = protected(client, auth, "F02-subscription", "订阅")
    manager = client.app.state.events
    seen = []

    def callback(url, secret, sid, eid, value, old=None):
        if value.get("type") == "verification":
            return 200, json.dumps({"challenge": value["challenge"]}).encode()
        seen.append(eid)
        return 500, b""

    manager.sender = callback
    args = {
        "name": "message.created",
        "arguments": {"conversation_id": cid},
        "delivery": {
            "mode": "webhook",
            "url": "https://receiver.example/events",
            "secret": "whsec_" + base64.b64encode(secrets.token_bytes(32)).decode(),
        },
    }
    created = asyncio.run(
        manager.handle(
            "events/subscribe", args, auth["Authorization"][7:], scoped["X-Notify-Receiver"]
        )
    )
    assert client.post(
        "/admin/api/conversations/" + cid + "/archive",
        headers=ADMIN,
        json={"archived": True, "visibility_only": True},
    ).json()["active"]
    iid = reply(client, cid)
    asyncio.run(manager.tick())
    assert len(seen) == 1
    assert store.claims.public(iid) is None
    subs = client.get("/admin/api/conversations/" + cid + "/subscriptions", headers=ADMIN).json()
    assert subs["subscriptions"][0]["verified_at"] and not subs["webhook_receipt_is_execution"]
    store.db.execute("UPDATE mcp_event_subscriptions SET expires=0 WHERE id=?", (created["id"],))
    assert (
        client.get("/admin/api/conversations/" + cid + "/subscriptions", headers=ADMIN).json()[
            "subscriptions"
        ][0]["state"]
        == "expired"
    )
    assert (
        len(
            client.get("/api/inbox", headers=scoped, params={"conversation_id": cid}).json()[
                "messages"
            ]
        )
        == 1
    )
    renewed = asyncio.run(
        manager.handle(
            "events/subscribe", args, auth["Authorization"][7:], scoped["X-Notify-Receiver"]
        )
    )
    assert renewed["id"] == created["id"]
    assert (
        asyncio.run(
            manager.handle(
                "events/unsubscribe", args, auth["Authorization"][7:], scoped["X-Notify-Receiver"]
            )
        )
        == {}
    )
    assert (
        store.db.execute("SELECT status FROM mcp_event_subscriptions").fetchone()[0] == "cancelled"
    )
    assert store.receivers.summary(cid)["status"] == "active"
