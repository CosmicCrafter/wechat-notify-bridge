"""Connection record, saved credentials and real communication are separate facts."""

import json
import secrets
import time
import httpx
import pytest
from test_portal import portal as portal_fixture, ADMIN
from test_feishu import CONFIG

portal = portal_fixture


def setup(portal):
    store, client, auth, _, chats, *_ = portal
    name = "待配置-" + secrets.token_hex(4)
    row = client.post(
        "/admin/api/bots", headers=ADMIN, json={"name": name, "platform": "feishu"}
    ).json()
    bot_id = row["id"]
    calls = []
    valid = secrets.token_urlsafe(24)

    def transport(request):
        body = json.loads(request.content)
        calls.append(request.url.path)
        if request.url.path.endswith("/internal"):
            if body["app_secret"] == "test-unavailable":
                raise httpx.ConnectError("fixture", request=request)
            if body["app_secret"] == "test-malformed":
                return httpx.Response(200, json=["invalid"])
            return httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": "fixture", "expire": 7200}
                if body["app_secret"] == valid
                else {"code": 10003, "msg": body["app_secret"]},
            )
        return httpx.Response(
            200, json={"code": 0, "data": {"message_id": "om_" + secrets.token_hex(16)}}
        )

    adapter = client.app.state.channels.adapter(bot_id)
    adapter.transport = httpx.MockTransport(transport)
    body = {
        **CONFIG,
        "app_id": "cli_" + secrets.token_hex(8),
        "app_secret": valid,
        "verify_credentials": True,
    }
    identity = store.clients.authenticate(auth["Authorization"][7:])
    store.bots.set_grants(identity.id, ["default", bot_id], "default")
    return bot_id, body, calls, adapter


def metadata(client, bot_id):
    return next(
        b for b in client.get("/admin/api/bots", headers=ADMIN).json()["bots"] if b["id"] == bot_id
    )


def test_pending_record_denies_delivery_and_enable_without_affecting_old_bot(portal):
    store, client, auth, _, chats, original_calls, _ = portal
    original = store.bots.get("default")
    bot_id, body, calls, adapter = setup(portal)
    row = metadata(client, bot_id)
    assert (
        not row["enabled"]
        and row["configuration_state"] == "pending_configuration"
        and not row["delivery_ready"]
    )
    payload = {
        "conversation_id": chats[0]["id"],
        "dedup_key": "pending-send",
        "text": "must not send",
        "bot_id": bot_id,
    }
    assert client.post("/api/messages", headers=auth, json=payload).status_code == 409
    assert (
        client.post(
            "/admin/api/bots/" + bot_id, headers=ADMIN, json={"name": row["name"], "enabled": True}
        ).json()["detail"]
        == "bot_configuration_required"
    )
    assert not calls and not adapter.config()
    result = client.post("/api/messages", headers=auth, json={**payload, "bot_id": "default"})
    assert result.json()["status"] == "api_accepted" and len(original_calls) == 1
    assert store.bots.get("default") == original
    # Pre-F03 partial records could already carry enabled=1. Preserve that data,
    # but never expose them as deliverable or send with missing credentials.
    store.db.execute("UPDATE bots SET enabled=1 WHERE id=?", (bot_id,))
    legacy_partial = metadata(client, bot_id)
    assert legacy_partial["enabled"] and not legacy_partial["delivery_ready"]
    assert legacy_partial["configuration_state"] == "pending_configuration"
    assert client.post("/api/messages", headers=auth, json=payload).status_code == 409
    assert not calls


def test_failed_validation_preserves_record_and_corrected_retry_reuses_it(portal):
    store, client, auth, _, chats, *_ = portal
    bot_id, body, calls, adapter = setup(portal)
    url = "/admin/api/bots/" + bot_id + "/feishu"
    # Even a cached valid token cannot make wrong new credentials appear valid.
    adapter.token, adapter.token_until = "old-cached-token", time.time() + 3600
    bad = secrets.token_urlsafe(24)
    result = client.post(url, headers=ADMIN, json={**body, "app_secret": bad})
    assert result.status_code == 422 and result.json()["detail"] == {
        "code": "feishu_credentials_rejected",
        "platform_code": 10003,
    }
    assert bad not in result.text and not adapter.config() and not store.bots.get(bot_id)["enabled"]
    assert len(calls) == 1
    assert (
        client.post(url, headers=ADMIN, json={**body, "app_id": "wrong format"}).status_code == 422
    )
    assert len(calls) == 1
    result = client.post(url, headers=ADMIN, json=body)
    assert result.status_code == 200 and result.json()["configured"]
    row = metadata(client, bot_id)
    assert row["enabled"] and row["configuration_state"] == "configured" and row["delivery_ready"]
    assert row["test"]["state"] == "not_tested" and not row["test"]["receive_confirmed"]
    assert client.post(url, headers=ADMIN, json=body).status_code == 200
    assert (
        client.post(
            "/admin/api/bots", headers=ADMIN, json={"name": row["name"], "platform": "feishu"}
        ).status_code
        == 409
    )
    assert sum(b["id"] == bot_id for b in store.bots.list()) == 1
    assert body["app_secret"] not in "\n".join(store.db.iterdump())
    result = client.post(
        "/api/messages",
        headers=auth,
        json={
            "conversation_id": chats[0]["id"],
            "bot_id": bot_id,
            "dedup_key": "now-ready",
            "text": "独立平台替身",
        },
    )
    assert result.json()["status"] == "api_accepted"


@pytest.mark.parametrize(
    "secret,status", [("test-unavailable", 503), ("test-malformed", 502), ("test-rejected", 422)]
)
def test_failed_edit_keeps_old_credentials_grants_and_delivery(portal, secret, status):
    store, client, auth, _, chats, *_ = portal
    bot_id, body, calls, adapter = setup(portal)
    url = "/admin/api/bots/" + bot_id + "/feishu"
    assert client.post(url, headers=ADMIN, json=body).status_code == 200
    before = adapter.config()
    identity = store.clients.authenticate(auth["Authorization"][7:])
    grants = store.bots.grants(identity.id)
    failed = client.post(url, headers=ADMIN, json={**body, "app_secret": secret})
    assert failed.status_code == status and secret not in failed.text
    assert (
        adapter.config() == before
        and store.bots.grants(identity.id) == grants
        and store.bots.get(bot_id)["enabled"]
    )
    assert (
        client.post(
            "/api/messages",
            headers=auth,
            json={
                "conversation_id": chats[0]["id"],
                "bot_id": bot_id,
                "text": "仍使用原凭据",
                "dedup_key": "old-survives",
            },
        ).json()["status"]
        == "api_accepted"
    )


def test_legacy_save_retains_contract_and_partial_write_rolls_back(portal, monkeypatch):
    store, client, *_ = portal
    bot_id, body, calls, adapter = setup(portal)
    legacy = {k: v for k, v in body.items() if k != "verify_credentials"}
    assert (
        client.post("/admin/api/bots/" + bot_id + "/feishu", headers=ADMIN, json=legacy).status_code
        == 200
    )
    assert not calls  # Existing callers do not unexpectedly make a new platform request.
    before = adapter.config()
    save = store.channels.save_settings

    def fail_after_write(scope, value):
        save(scope, value)
        raise RuntimeError("injected local persistence failure")

    monkeypatch.setattr(store.channels, "save_settings", fail_after_write)
    with pytest.raises(RuntimeError):
        adapter.configure({**legacy, "app_secret": secrets.token_urlsafe(24), "enabled": False})
    assert adapter.config() == before and store.bots.get(bot_id)["enabled"]


def test_pending_wechat_can_pair_but_repair_does_not_reenable_disabled_old_connection(
    portal, monkeypatch
):
    store, client, *_ = portal
    bot_id = client.post(
        "/admin/api/bots", headers=ADMIN, json={"name": "扫码待配置", "platform": "wechat"}
    ).json()["id"]
    assert not store.bots.get(bot_id)["enabled"]
    pair = client.app.state.channels.pairing(bot_id)
    calls = []

    async def start(replace):
        calls.append(replace)
        return pair.snapshot()

    monkeypatch.setattr(pair, "start", start)
    assert (
        client.post(
            "/admin/api/bots/" + bot_id + "/pairing/start", headers=ADMIN, json={"replace": False}
        ).status_code
        == 200
    )
    assert calls == [False] and not pair.run_workers
    scope = client.app.state.channels.adapter(bot_id).store
    account = {
        "bot_token": secrets.token_urlsafe(24),
        "bot_id": "test-new",
        "user_id": "test-new-owner",
        "context_token": "fixture",
        "base_url": "https://ilinkai.weixin.qq.com",
        "bound_at": time.time(),
    }
    scope.bind(account)
    assert store.bots.get(bot_id)["enabled"]
    store.bots.update(bot_id, "扫码待配置", False)
    scope.bind({**account, "bot_token": secrets.token_urlsafe(24)})
    assert not store.bots.get(bot_id)["enabled"]
    assert (
        client.post(
            "/admin/api/bots/" + bot_id + "/pairing/start", headers=ADMIN, json={"replace": True}
        ).status_code
        == 409
    )
    assert calls == [False]
