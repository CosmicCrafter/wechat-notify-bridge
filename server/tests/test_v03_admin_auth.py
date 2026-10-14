"""Real administrator HTTP contracts, isolated data and random passwords."""

import secrets
import sqlite3
import pytest
from test_portal import portal as portal_fixture, send
from wechat_bridge.storage.admin_accounts import password_hash, password_matches

ADMIN_ORIGIN = {"Origin": "https://testserver", "X-Admin-Request": "1"}
portal = portal_fixture


@pytest.fixture
def account(portal):
    store, client, *_ = portal
    return portal, client.app.state.test_admin_password


def signin(account):
    portal, password = account
    r = portal[1].post(
        "/admin/api/auth/login",
        headers=ADMIN_ORIGIN,
        json={"username": "维护者", "password": password},
    )
    assert r.status_code == 200
    return {**ADMIN_ORIGIN, "X-Admin-CSRF": r.json()["csrf"]}, r


def test_password_hash_is_salted_memory_hard_and_prototype_values_rejected():
    password = secrets.token_urlsafe(32)
    first, second = password_hash(password), password_hash(password)
    assert first != second and password not in first
    assert password_matches(password, first)
    assert not password_matches(password + "x", first)
    with pytest.raises(Exception):
        password_hash("DemoOnly123!")


def test_admin_cookie_identity_csrf_and_legacy_boundary(account):
    portal, password = account
    store, client, app_auth, *_ = portal
    headers, r = signin(account)
    cookie = r.headers["set-cookie"]
    for value in ["HttpOnly", "Secure", "SameSite=strict", "Path=/admin/"]:
        assert value in cookie
    assert client.get("/admin/api/clients").status_code == 200
    assert client.get("/api/status").status_code == 401
    assert client.get("/chat/api/conversations").status_code == 401
    body = {"name": "isolated-client"}
    assert client.post("/admin/api/clients", json=body).status_code == 403
    assert (
        client.post(
            "/admin/api/clients", headers={**headers, "Origin": "https://evil.test"}, json=body
        ).status_code
        == 403
    )
    assert client.post("/admin/api/clients", headers=headers, json=body).status_code == 200
    assert (
        client.get("/admin/api/clients", headers=app_auth).status_code == 200
    )  # valid own admin Cookie
    client.cookies.clear()
    assert client.get("/admin/api/clients", headers=app_auth).status_code == 401
    assert (
        client.get(
            "/admin/api/clients", headers={"Authorization": "Bearer fixture-admin"}
        ).status_code
        == 401
    )
    assert password not in "\n".join(store.db.iterdump())


def test_legacy_admin_key_and_browser_setup_cannot_be_restored(account, tmp_path):
    portal, password = account
    store, client, app_auth, *_ = portal
    # Restored databases can retain the historical flag, but it is no longer authorization.
    store.db.execute("UPDATE admin_account SET legacy_enabled=1 WHERE id=1")
    snapshot = sqlite3.connect(tmp_path / "historical-admin.sqlite3")
    store.db.backup(snapshot)
    store.db.execute("UPDATE admin_account SET legacy_enabled=0 WHERE id=1")
    snapshot.backup(store.db)
    snapshot.close()
    client.cookies.clear()
    legacy = {"Authorization": "Bearer fixture-admin"}
    assert client.get("/admin/api/clients", headers=legacy).status_code == 401
    assert (
        client.post("/admin/api/clients", headers=legacy, json={"name": "blocked"}).status_code
        == 401
    )
    for headers in (legacy, app_auth, {}):
        assert (
            client.post(
                "/admin/api/auth/setup",
                headers=headers,
                json={"username": "other", "password": password},
            ).status_code
            == 404
        )
    headers, _ = signin(account)
    assert (
        client.post("/admin/api/clients", headers=legacy, json={"name": "csrf-blocked"}).status_code
        == 403
    )
    assert client.get("/admin/api/account").json()["legacy_enabled"] is False
    for enabled in (False, True):
        assert (
            client.post(
                "/admin/api/account/legacy-key",
                headers=headers,
                json={"old_password": password, "enabled": enabled},
            ).status_code
            == 404
        )
    assert client.get("/api/status", headers=app_auth).status_code == 200


def test_no_account_rejects_legacy_key_until_authorized_terminal_initialization(portal, tmp_path):
    from wechat_bridge.admin_reset import reset

    store, client, app_auth, *_ = portal
    store.db.execute("DELETE FROM admin_account")
    store.db.execute("DELETE FROM admin_sessions")
    legacy = {"Authorization": "Bearer fixture-admin"}
    assert client.get("/admin/api/clients", headers=legacy).status_code == 503
    assert client.get("/admin/api/auth/status").json() == {
        "configured": False,
        "authenticated": False,
    }
    password = secrets.token_urlsafe(32)
    database = store.db.execute("PRAGMA database_list").fetchone()[2]
    reset(database, tmp_path / "private-initialize", password, name="new-admin", initialize=True)
    response = client.post(
        "/admin/api/auth/login",
        headers=ADMIN_ORIGIN,
        json={"username": "new-admin", "password": password},
    )
    assert response.status_code == 200
    assert client.get("/admin/api/clients").status_code == 200
    client.cookies.clear()
    assert client.get("/admin/api/clients", headers=legacy).status_code == 401
    assert client.get("/api/status", headers=app_auth).status_code == 200


def test_wrong_old_password_does_not_mutate_and_change_revokes_sessions(account):
    portal, password = account
    store, client, *_ = portal
    headers, _ = signin(account)
    new = secrets.token_urlsafe(32)
    assert (
        client.post(
            "/admin/api/account/password",
            headers=headers,
            json={"old_password": password + "x", "password": new},
        ).status_code
        == 401
    )
    assert client.get("/admin/api/clients").status_code == 200
    r = client.post(
        "/admin/api/account/password",
        headers=headers,
        json={"old_password": password, "password": new},
    )
    assert r.status_code == 200 and r.json()["reauthentication_required"]
    assert store.db.execute("SELECT count(*) FROM admin_sessions").fetchone()[0] == 0
    assert client.get("/admin/api/clients").status_code == 401
    assert (
        client.post(
            "/admin/api/auth/login",
            headers=ADMIN_ORIGIN,
            json={"username": "维护者", "password": password},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/admin/api/auth/login",
            headers=ADMIN_ORIGIN,
            json={"username": "维护者", "password": new},
        ).status_code
        == 200
    )
    assert client.get("/api/status", headers=portal[2]).status_code == 200


def test_username_change_requires_password_and_stable_app_identity(account):
    portal, password = account
    headers, _ = signin(account)
    store, client, *_ = portal
    before = [dict(r) for r in store.db.execute("SELECT * FROM api_clients")]
    assert (
        client.post(
            "/admin/api/account/username",
            headers=headers,
            json={"old_password": password + "x", "username": "维护新版"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/admin/api/account/username",
            headers=headers,
            json={"old_password": password, "username": "维护新版"},
        ).status_code
        == 200
    )
    assert [dict(r) for r in store.db.execute("SELECT * FROM api_clients")] == before
    assert (
        client.post(
            "/admin/api/auth/login",
            headers=ADMIN_ORIGIN,
            json={"username": "维护新版", "password": password},
        ).status_code
        == 200
    )


def test_invalid_auth_payload_redacts_password_and_login_is_throttled(account):
    portal, password = account
    client = portal[1]
    r = client.post(
        "/admin/api/auth/login",
        headers=ADMIN_ORIGIN,
        json={"username": "维护者", "password": password, "unknown": password},
    )
    assert r.status_code == 422 and password not in r.text
    for _ in range(5):
        assert (
            client.post(
                "/admin/api/auth/login",
                headers=ADMIN_ORIGIN,
                json={"username": "unknown", "password": password},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/admin/api/auth/login",
            headers=ADMIN_ORIGIN,
            json={"username": "维护者", "password": password},
        ).status_code
        == 429
    )


def test_admin_history_browsing_never_moves_mobile_reads(account):
    portal, password = account
    store, client, auth, _, chats, *_ = portal
    headers, _ = signin(account)
    cid = chats[0]["id"]
    assert send(client, auth, cid).status_code == 200
    before = list(store.db.execute("SELECT * FROM web_reads"))
    r = client.get("/admin/api/conversations")
    assert r.status_code == 200
    assert all("unread" not in c for c in r.json()["conversations"])
    assert client.get(f"/admin/api/conversations/{cid}/messages").status_code == 200
    assert list(store.db.execute("SELECT * FROM web_reads")) == before
    assert client.get("/admin/api/deliveries").status_code == 200
    assert client.get("/admin/api/overview").status_code == 200


def test_auth_tables_are_additive_and_database_backup_restores(account, tmp_path):
    portal, password = account
    store = portal[0]
    destination = tmp_path / "restore.sqlite3"
    restore = sqlite3.connect(destination)
    store.db.backup(restore)
    assert restore.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert restore.execute("SELECT username FROM admin_account").fetchone()[0] == "维护者"
    assert restore.execute("SELECT count(*) FROM api_clients").fetchone()[0] == 2
    restore.close()
