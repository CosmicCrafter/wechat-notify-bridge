"""Recovery codes and terminal fallback on independent data and fake platforms."""

import json
import re
import secrets
import sqlite3
import pytest
from test_portal import portal, ADMIN, login as phone_login
from test_feishu import feishu, CONFIG
from test_v03_admin_auth import account, signin, ADMIN_ORIGIN
from wechat_bridge.admin_reset import reset
from wechat_bridge.storage.admin_accounts import password_matches


def code(portal):
    wire = portal[5][-1]["msg"]["item_list"][0]["text_item"]["text"]
    return re.search(r"验证码：(\d{8})", wire)[1]


def clear_cooldown(store):
    store.db.execute("DELETE FROM admin_recovery_cooldown")


def bind(account, bot="default"):
    portal, password = account
    client = portal[1]
    start = client.post(
        "/admin/api/account/recovery/bind",
        headers=ADMIN,
        json={"bot_id": bot, "old_password": password},
    )
    assert start.status_code == 200
    otp = code(portal)
    r = client.post(
        "/admin/api/account/recovery/verify",
        headers=ADMIN,
        json={"challenge_id": start.json()["challenge_id"], "code": otp},
    )
    assert r.status_code == 200
    return start.json()["challenge_id"], otp


def test_verified_last_recovery_connection_protection_and_no_code_history(account):
    portal, password = account
    store, client, *_ = portal
    id, otp = bind(account)
    assert (
        client.post(
            "/admin/api/account/recovery/verify",
            headers=ADMIN,
            json={"challenge_id": id, "code": otp},
        ).status_code
        == 400
    )
    assert not store.db.execute("SELECT 1 FROM chat_messages").fetchone()
    assert otp not in client.get("/admin/api/deliveries", headers=ADMIN).text
    assert otp not in "\n".join(store.db.iterdump())
    assert (
        client.post(
            "/admin/api/bots/default", headers=ADMIN, json={"name": "默认", "enabled": False}
        ).status_code
        == 409
    )
    assert client.post("/admin/api/bots/default/delete", headers=ADMIN, json={}).status_code == 409
    assert (
        client.post("/admin/api/pairing/start", headers=ADMIN, json={"replace": True}).status_code
        == 409
    )
    assert (
        client.post(
            "/admin/api/account/recovery/default/remove",
            headers=ADMIN,
            json={"enabled": False, "old_password": password},
        ).status_code
        == 409
    )
    assert store.bots.get("default")["enabled"] and store.account()


def test_recovery_reset_uniform_request_one_use_limits_and_identity_separation(account):
    portal, password = account
    store, client, auth, *_ = portal
    bind(account)
    headers, _ = signin(account)
    clear_cooldown(store)
    before = len(portal[5])
    fake = client.post(
        "/admin/api/recovery/request",
        headers=ADMIN_ORIGIN,
        json={"username": "unknown", "platform": "wechat"},
    )
    assert fake.status_code == 200 and fake.json()["accepted"] and len(portal[5]) == before
    clear_cooldown(store)
    requested = client.post(
        "/admin/api/recovery/request",
        headers=ADMIN_ORIGIN,
        json={"username": "维护者", "platform": "wechat"},
    )
    assert requested.status_code == 200 and set(requested.json()) == set(fake.json())
    otp = code(portal)
    id = requested.json()["challenge_id"]
    assert (
        client.post(
            "/admin/api/recovery/request",
            headers=ADMIN_ORIGIN,
            json={"username": "维护者", "platform": "wechat"},
        ).status_code
        == 429
    )
    new = secrets.token_urlsafe(32)
    assert (
        client.post(
            "/admin/api/recovery/complete",
            headers=ADMIN_ORIGIN,
            json={"challenge_id": fake.json()["challenge_id"], "code": otp, "password": new},
        ).status_code
        == 400
    )
    reset_body = {"challenge_id": id, "code": otp, "password": new}
    assert (
        client.post(
            "/admin/api/recovery/complete", headers=ADMIN_ORIGIN, json=reset_body
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/admin/api/recovery/complete", headers=ADMIN_ORIGIN, json=reset_body
        ).status_code
        == 400
    )
    assert client.get("/admin/api/clients").status_code == 401
    assert client.get("/api/status", headers=auth).status_code == 200
    assert (
        client.post(
            "/admin/api/auth/login",
            headers=ADMIN_ORIGIN,
            json={"username": "维护者", "password": new},
        ).status_code
        == 200
    )
    clear_cooldown(store)
    requested = client.post(
        "/admin/api/recovery/request",
        headers=ADMIN_ORIGIN,
        json={"username": "维护者", "platform": "wechat"},
    ).json()
    correct = code(portal)
    wrong = "00000000" if correct != "00000000" else "11111111"
    for _ in range(5):
        assert (
            client.post(
                "/admin/api/recovery/complete",
                headers=ADMIN_ORIGIN,
                json={"challenge_id": requested["challenge_id"], "code": wrong, "password": new},
            ).status_code
            == 400
        )
    assert (
        client.post(
            "/admin/api/recovery/complete",
            headers=ADMIN_ORIGIN,
            json={"challenge_id": requested["challenge_id"], "code": correct, "password": new},
        ).status_code
        == 400
    )


def test_terminal_reset_consistent_backup_restoration_keeps_all_business_data(account, tmp_path):
    portal, password = account
    store, client, auth, *_ = portal
    phone_login(client)
    signin(account)
    before = store.account()
    clients = [dict(r) for r in store.db.execute("SELECT * FROM api_clients")]
    new = secrets.token_urlsafe(32)
    database = store.db.execute("PRAGMA database_list").fetchone()[2]
    snapshot = reset(database, tmp_path / "private-reset-backup", new)
    assert client.get("/admin/api/clients").status_code == 401
    assert (
        store.account() == before
        and [dict(r) for r in store.db.execute("SELECT * FROM api_clients")] == clients
    )
    assert client.get("/api/status", headers=auth).status_code == 200
    assert client.get("/chat/api/conversations").status_code == 200
    assert password_matches(new, client.app.state.admin_accounts.account()["password_hash"])
    restore = sqlite3.connect(snapshot)
    restore.row_factory = sqlite3.Row
    assert restore.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert password_matches(
        password, restore.execute("SELECT password_hash FROM admin_account").fetchone()[0]
    )
    restore.close()


def test_same_owner_credential_repair_requires_password_and_reverification(account, feishu):
    portal, password = account
    store, client, *_ = portal

    def bind_feishu():
        clear_cooldown(store)
        start = client.post(
            "/admin/api/account/recovery/bind",
            headers=ADMIN,
            json={"bot_id": "feishu-default", "old_password": password},
        )
        assert start.status_code == 200
        otp = re.search(r"验证码：(\d{8})", str(feishu[1][-1][1]))[1]
        assert (
            client.post(
                "/admin/api/account/recovery/verify",
                headers=ADMIN,
                json={"challenge_id": start.json()["challenge_id"], "code": otp},
            ).status_code
            == 200
        )

    bind_feishu()
    changed = dict(CONFIG, app_secret=secrets.token_urlsafe(32))
    assert (
        client.post(
            "/admin/api/bots/feishu-default/feishu", headers=ADMIN, json=changed
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/admin/api/bots/feishu-default/feishu",
            headers=ADMIN,
            json=dict(changed, admin_password=password + "x"),
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/admin/api/bots/feishu-default/feishu",
            headers=ADMIN,
            json=dict(changed, admin_password=password),
        ).status_code
        == 200
    )
    assert "admin_password" not in store.channels.settings("feishu:feishu-default")
    bindings = client.get("/admin/api/account/recovery", headers=ADMIN).json()["bindings"]
    assert not bindings[0]["valid"]
    assert (
        client.post(
            "/admin/api/bots/feishu-default",
            headers=ADMIN,
            json={"name": "恢复连接", "enabled": False},
        ).status_code
        == 409
    )
    bind_feishu()
    assert client.get("/admin/api/account/recovery", headers=ADMIN).json()["bindings"][0]["valid"]


def test_old_password_checks_are_limited(account):
    portal, password = account
    store, client, *_ = portal
    headers, _ = signin(account)
    for _ in range(5):
        assert (
            client.post(
                "/admin/api/account/password",
                headers=headers,
                json={"old_password": password + "x", "password": secrets.token_urlsafe(32)},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/admin/api/account/password",
            headers=headers,
            json={"old_password": password, "password": secrets.token_urlsafe(32)},
        ).status_code
        == 429
    )
