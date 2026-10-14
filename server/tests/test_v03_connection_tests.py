"""Connection proof requires verified owner transport; config save is insufficient."""

import re
from test_portal import portal, ADMIN
from test_clients import incoming
from test_feishu import feishu, callback, message


def test_wechat_send_and_owner_echo_independent_from_business_inbox(portal):
    store, client, auth, _, chats, calls, _ = portal
    impact = client.get("/admin/api/bots/default/impact", headers=ADMIN).json()
    assert impact["applications"] and impact["test"]["state"] == "not_tested"
    first = client.post("/admin/api/bots/default/test", headers=ADMIN, json={})
    assert (
        first.status_code == 200
        and first.json()["send_status"] == "api_accepted"
        and not first.json()["receive_confirmed"]
    )
    wire = calls[-1]["msg"]["item_list"][0]["text_item"]["text"]
    nonce = re.search(r"nb-test:[a-f0-9]{32}", wire)[0]
    now = __import__("time").time()
    store.ingest({"msgs": [incoming(nonce, 100, from_user_id="stranger")]}, now)
    assert not client.get("/admin/api/bots/default/impact", headers=ADMIN).json()["test"][
        "receive_confirmed"
    ]
    store.ingest({"msgs": [incoming(nonce, 101, from_user_id=store.account()["user_id"])]}, now)
    assert client.get("/admin/api/bots/default/impact", headers=ADMIN).json()["test"][
        "receive_confirmed"
    ]
    assert client.get("/api/inbox", headers=auth).json()["messages"] == []
    assert not store.db.execute("SELECT 1 FROM chat_messages").fetchone()


def test_feishu_requires_signed_owner_callback_for_test_echo(feishu):
    portal, calls = feishu
    store, client, *_ = portal
    r = client.post("/admin/api/bots/feishu-default/test", headers=ADMIN, json={})
    assert r.status_code == 200 and not r.json()["receive_confirmed"]
    text = str(calls[-1][1])
    nonce = re.search(r"nb-test:[a-f0-9]{32}", text)[0]
    assert callback(client, message(nonce), signed=False).status_code == 401
    assert not client.get("/admin/api/bots/feishu-default/impact", headers=ADMIN).json()["test"][
        "receive_confirmed"
    ]
    assert callback(client, message(nonce)).status_code == 200
    assert client.get("/admin/api/bots/feishu-default/impact", headers=ADMIN).json()["test"][
        "receive_confirmed"
    ]
    assert not store.db.execute("SELECT 1 FROM chat_messages").fetchone()
