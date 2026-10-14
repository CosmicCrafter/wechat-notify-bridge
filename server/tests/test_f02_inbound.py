"""No inferred task answers; native references and owner assignments are stable."""

from test_feishu import feishu as feishu_fixture, callback, message, input_task
from test_portal import ADMIN, portal as portal_fixture
from test_f02_receivers import protected

feishu = feishu_fixture
portal = portal_fixture


def test_unquoted_reply_never_answers_even_a_single_input_task(feishu):
    portal, _ = feishu
    store, client, auth, *_ = portal
    task = input_task(feishu, "F02-unquoted")
    assert "task_id" not in callback(client, message("001234")).json()
    cid = task["task"]["conversation_id"]
    assert store.portal.tasks.get(cid, task["task"]["id"])["status"] == "pending"
    rows = client.get("/admin/api/unassigned", headers=ADMIN).json()["messages"]
    assert len(rows) == 1 and rows[0]["text"] == "001234"
    assert callback(client, message("001234")).json()["duplicate"]
    iid = rows[0]["id"]
    url = "/admin/api/unassigned/" + str(iid) + "/assign"
    assert client.post(url, headers=ADMIN, json={"conversation_id": cid}).status_code == 200
    assert client.post(url, headers=ADMIN, json={"conversation_id": cid}).json()["duplicate"]
    assert client.get("/admin/api/unassigned", headers=ADMIN).json()["messages"] == []
    assert store.portal.tasks.get(cid, task["task"]["id"])["status"] == "pending"


def test_protected_reply_uses_parent_mapping_and_never_a_display_name(feishu):
    portal, _ = feishu
    store, client, auth, other, *_ = portal
    cid, scoped, _ = protected(client, auth, "F02-native", "稳定引用")
    sent = client.post(
        "/api/messages",
        headers=scoped,
        json={
            "channel": "feishu",
            "conversation_id": cid,
            "text": "请回复此消息",
            "dedup_key": "F02-reference",
        },
    ).json()
    parent = sent["diagnostics"]["provider_message_id"]
    assert callback(client, message("原生引用回复", parent_id=parent)).status_code == 200
    assert (
        client.get("/api/inbox", headers=scoped, params={"conversation_id": cid}).json()[
            "messages"
        ][0]["text"]
        == "原生引用回复"
    )
    assert (
        client.post(
            "/admin/api/conversations/" + cid + "/rename", headers=ADMIN, json={"name": "已改名"}
        ).status_code
        == 200
    )
    later = message("改名后仍准确", parent_id=parent)
    later["event"]["message"]["message_id"] = "om_f02_later"
    assert callback(client, later).status_code == 200
    bare = message("[codex-已改名] 无引用")
    bare["event"]["message"]["message_id"] = "om_f02_bare"
    assert callback(client, bare).status_code == 200
    queued = client.get("/admin/api/unassigned", headers=ADMIN).json()["messages"]
    assert len(queued) == 1 and "无引用" in queued[0]["text"]
    assert (
        len(
            client.get("/api/inbox", headers=scoped, params={"conversation_id": cid}).json()[
                "messages"
            ]
        )
        == 2
    )


def test_owner_assignment_rechecks_bot_grants_and_cannot_move_a_direct_reply(feishu):
    portal, _ = feishu
    store, client, auth, other, chats, *_ = portal
    assert callback(client, message("待核对归属")).status_code == 200
    iid = client.get("/admin/api/unassigned", headers=ADMIN).json()["messages"][0]["id"]
    identity = store.clients.authenticate(auth["Authorization"][7:])
    store.bots.set_grants(identity.id, ["default"], "default")
    url = "/admin/api/unassigned/" + str(iid) + "/assign"
    assert (
        client.post(url, headers=ADMIN, json={"conversation_id": chats[0]["id"]}).status_code == 403
    )
    store.bots.set_grants(identity.id, ["default", "feishu-default"], "default")
    assert (
        client.post(url, headers=ADMIN, json={"conversation_id": chats[0]["id"]}).status_code == 200
    )
    assert (
        client.post(url, headers=ADMIN, json={"conversation_id": chats[1]["id"]}).status_code == 409
    )


def test_query_boolean_alias_cannot_escape_the_scoped_inbox(feishu):
    portal, _ = feishu
    _, client, auth, *_ = portal
    _, scoped, _ = protected(client, auth, "F02-alias", "别名")
    for query in ("true", "1", "yes", "on"):
        assert (
            client.get(
                "/api/inbox", headers=scoped, params={"include_unaddressed": query}
            ).status_code
            == 403
        )
