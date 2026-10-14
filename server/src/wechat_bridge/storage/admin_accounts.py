"""Single administrator with password authentication and isolated browser sessions."""

import base64
import hashlib
import hmac
import re
import secrets
import time

from wechat_bridge.storage.client_registry import ClientError

ADMIN_COOKIE = "notify_admin_session"
SESSION_TTL = 8 * 3600
_DUMMY_HASH = None


def username(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_.\-\u4e00-\u9fff]{3,32}", value):
        raise ClientError("invalid_admin_username", 422)
    return value.casefold()


def password_hash(password):
    if not isinstance(password, str) or not 15 <= len(password) <= 128:
        raise ClientError("invalid_admin_password", 422)
    # Reject supplied prototype passwords, not user-selected production defaults.
    if any(word in password.casefold() for word in ("demoonly", "notifybridgedemo")):
        raise ClientError("prototype_password_forbidden", 422)
    salt = secrets.token_bytes(16)
    try:
        raw = password.encode()
    except UnicodeError:
        raise ClientError("invalid_admin_password", 422) from None
    digest = hashlib.scrypt(raw, salt=salt, n=32768, r=8, p=3, dklen=32, maxmem=64 * 1024 * 1024)
    return (
        "scrypt$32768$8$3$"
        + base64.urlsafe_b64encode(salt).decode()
        + "$"
        + base64.urlsafe_b64encode(digest).decode()
    )


def password_matches(password, encoded):
    try:
        algo, n, r, p, salt, expected = encoded.split("$")
        if (algo, n, r, p) != ("scrypt", "32768", "8", "3") or len(password) > 128:
            return False
        actual = hashlib.scrypt(
            password.encode(),
            salt=base64.urlsafe_b64decode(salt),
            n=32768,
            r=8,
            p=3,
            dklen=32,
            maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(actual, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError):
        return False


class AdminAccounts:
    def __init__(self, db):
        self.db = db
        db.executescript("""
          CREATE TABLE IF NOT EXISTS admin_account (
            id INTEGER PRIMARY KEY CHECK(id=1),username TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,created_at REAL NOT NULL,password_changed_at REAL NOT NULL,
            legacy_enabled INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS admin_sessions (
            token_hash TEXT PRIMARY KEY,csrf TEXT NOT NULL,version INTEGER NOT NULL,
            created_at REAL NOT NULL,expires_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS admin_limits (
            bucket TEXT PRIMARY KEY,failures INTEGER NOT NULL,until_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS admin_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,action TEXT NOT NULL,created_at REAL NOT NULL,source TEXT NOT NULL);
        """)
        global _DUMMY_HASH
        if _DUMMY_HASH is None:
            _DUMMY_HASH = password_hash(secrets.token_urlsafe(24))
        self.dummy_hash = _DUMMY_HASH

    def account(self):
        return self.db.execute("SELECT * FROM admin_account WHERE id=1").fetchone()

    def metadata(self):
        row = self.account()
        return {
            "configured": bool(row),
            "username": row["username"] if row else None,
            "password_changed_at": row["password_changed_at"] if row else None,
            # Kept as read-only compatibility metadata; historical DB flags cannot enable Key auth.
            "legacy_enabled": False,
        }

    def audit(self, action, source="web"):
        self.db.execute(
            "INSERT INTO admin_audit(action,created_at,source) VALUES (?,?,?)",
            (action, time.time(), source),
        )

    def initialize(self, name, encoded):
        if self.account():
            raise ClientError("admin_already_initialized", 409)
        name = username(name)
        now = time.time()
        self.db.execute(
            "INSERT INTO admin_account VALUES (1,?,?,1,?,?,0)", (name, encoded, now, now)
        )
        self.audit("initialize")
        return self.metadata()

    def limit(self, bucket):
        now = time.time()
        self.db.execute("DELETE FROM admin_limits WHERE until_at<?", (now,))
        row = self.db.execute(
            "SELECT failures FROM admin_limits WHERE bucket=?", (bucket,)
        ).fetchone()
        if row and row[0] >= 5:
            raise ClientError("admin_rate_limited", 429)

    def failure(self, bucket):
        self.db.execute(
            "INSERT INTO admin_limits VALUES (?,1,?) ON CONFLICT(bucket) DO UPDATE SET failures=failures+1",
            (bucket, time.time() + 900),
        )

    def session(self, token):
        if not isinstance(token, str) or len(token) > 128:
            return None
        return self.db.execute(
            "SELECT s.* FROM admin_sessions s JOIN admin_account a ON a.id=1 AND a.version=s.version "
            "WHERE s.token_hash=? AND s.expires_at>?",
            (hashlib.sha256(token.encode()).hexdigest(), time.time()),
        ).fetchone()

    def issue(self, expected_version=None):
        row = self.account()
        if not row:
            raise ClientError("admin_not_initialized", 409)
        self.db.execute("DELETE FROM admin_sessions WHERE expires_at<?", (time.time(),))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        result = self.db.execute(
            "INSERT INTO admin_sessions SELECT ?,?,version,?,? FROM admin_account WHERE id=1 AND version=?",
            (
                hashlib.sha256(token.encode()).hexdigest(),
                csrf,
                time.time(),
                time.time() + SESSION_TTL,
                expected_version if expected_version is not None else row["version"],
            ),
        )
        if result.rowcount != 1:
            raise ClientError("admin_state_changed", 409)
        return token, csrf

    def revoke(self, token):
        self.db.execute(
            "DELETE FROM admin_sessions WHERE token_hash=?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        )

    def change(self, *, name=None, encoded=None, source="web", expected_version=None):
        row = self.account()
        if not row:
            raise ClientError("admin_not_initialized", 409)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.account()
            if expected_version is not None and row["version"] != expected_version:
                raise ClientError("admin_state_changed", 409)
            self.db.execute(
                "UPDATE admin_account SET username=?,password_hash=?,version=version+1,password_changed_at=? WHERE id=1",
                (
                    username(name) if name is not None else row["username"],
                    encoded or row["password_hash"],
                    time.time() if encoded else row["password_changed_at"],
                ),
            )
            self.db.execute("DELETE FROM admin_sessions")
            self.db.execute("DELETE FROM admin_limits")
            if self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='admin_recovery_challenges'"
            ).fetchone():
                self.db.execute("DELETE FROM admin_recovery_challenges")
            self.audit(
                "password_reset"
                if source in ("terminal", "recovery")
                else "password_change"
                if encoded
                else "username_change",
                source,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.metadata()
