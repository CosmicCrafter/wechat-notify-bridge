"""Owner-verified recovery destinations; codes never enter the chat ledger."""

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from wechat_bridge.storage.client_registry import ClientError


class AdminRecovery:
    def __init__(self, store, channels, accounts):
        self.store, self.db, self.channels, self.accounts = store, store.db, channels, accounts
        self.lock = asyncio.Lock()
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS admin_recovery_bindings (
            bot_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,verified_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS admin_recovery_challenges (
            id TEXT PRIMARY KEY,purpose TEXT NOT NULL,bot_id TEXT,version INTEGER NOT NULL,
            fingerprint TEXT,code_hash TEXT NOT NULL,expires_at REAL NOT NULL,attempts INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS admin_recovery_cooldown (id INTEGER PRIMARY KEY CHECK(id=1),until_at REAL NOT NULL);
        """)
        self.channels.registry.protection = self.assert_change

    def fingerprint(self, bot_id):
        bot = self.channels.registry.get(bot_id)
        adapter = self.channels.adapter(bot_id)
        if bot["platform"] == "wechat":
            config = adapter.store.account() or {}
            fields = ("user_id", "bot_id", "bot_token", "base_url")
            ready = bool(
                config.get("user_id") and config.get("bot_token") and config.get("context_token")
            )
        else:
            config = adapter.config()
            fields = ("app_id", "owner_open_id", "app_secret", "verification_token", "encrypt_key")
            ready = bool(config.get("enabled") and all(config.get(f) for f in fields))
        if not bot["enabled"] or not ready:
            raise ClientError("recovery_connection_unavailable", 409)
        return hashlib.sha256(
            json.dumps(
                [bot["platform"], *[config.get(f) for f in fields]], ensure_ascii=False
            ).encode()
        ).hexdigest()

    def bindings(self):
        result = []
        for row in self.db.execute("SELECT * FROM admin_recovery_bindings ORDER BY verified_at"):
            try:
                bot = self.channels.registry.get(row["bot_id"])
                valid = self.fingerprint(row["bot_id"]) == row["fingerprint"]
            except Exception:
                bot = {"name": "连接不可用", "platform": "unknown"}
                valid = False
            result.append(
                {
                    "bot_id": row["bot_id"],
                    "name": bot["name"],
                    "platform": bot["platform"],
                    "verified_at": row["verified_at"],
                    "valid": valid,
                }
            )
        return result

    def assert_change(self, bot_id):
        protected = self.db.execute(
            "SELECT 1 FROM admin_recovery_bindings WHERE bot_id=?", (bot_id,)
        ).fetchone()
        if protected and not any(b["valid"] and b["bot_id"] != bot_id for b in self.bindings()):
            raise ClientError("last_admin_recovery_protected", 409)

    def remove(self, bot_id):
        self.assert_change(bot_id)
        self.db.execute("DELETE FROM admin_recovery_bindings WHERE bot_id=?", (bot_id,))
        self.accounts.audit("recovery_unbind", "web:" + bot_id)
        return {"bindings": self.bindings()}

    async def issue(
        self,
        purpose,
        *,
        bot_id=None,
        username=None,
        platform=None,
        expected_version=None,
        background_tasks=None,
    ):
        account = self.accounts.account()
        if not account:
            raise ClientError("admin_not_initialized", 409)
        if expected_version is not None and account["version"] != expected_version:
            raise ClientError("admin_state_changed", 409)
        now = time.time()
        cooldown = self.db.execute(
            "SELECT until_at FROM admin_recovery_cooldown WHERE id=1"
        ).fetchone()
        if cooldown and cooldown[0] > now:
            raise ClientError("admin_code_retry_later", 429)
        self.accounts.limit("admin-code")
        self.accounts.failure("admin-code")
        self.db.execute("INSERT OR REPLACE INTO admin_recovery_cooldown VALUES (1,?)", (now + 60,))
        self.db.execute("DELETE FROM admin_recovery_challenges WHERE expires_at<?", (now,))
        if purpose == "recovery":
            # Only a preverified destination may receive recovery codes. Uniform public result.
            candidates = [b for b in self.bindings() if b["valid"] and b["platform"] == platform]
            bot_id = (
                candidates[0]["bot_id"]
                if candidates
                and hmac.compare_digest(
                    (username or "").casefold().encode(), account["username"].encode()
                )
                else None
            )
        fingerprint = self.fingerprint(bot_id) if bot_id else None
        id = secrets.token_urlsafe(24)
        code = "".join(secrets.choice("0123456789") for _ in range(8))
        self.db.execute(
            "INSERT INTO admin_recovery_challenges VALUES (?,?,?,?,?,?,?,0)",
            (
                id,
                purpose,
                bot_id,
                account["version"],
                fingerprint,
                hashlib.sha256((id + ":" + code).encode()).hexdigest(),
                now + 300,
            ),
        )

        async def deliver():
            pending = self.db.execute(
                "SELECT * FROM admin_recovery_challenges WHERE id=?", (id,)
            ).fetchone()
            if (
                not bot_id
                or not pending
                or self.accounts.account()["version"] != pending["version"]
            ):
                return
            try:
                if self.fingerprint(bot_id) != fingerprint:
                    raise ClientError("admin_state_changed", 409)
                result = await self.channels.adapter(bot_id).send(
                    "Notify Bridge 管理员"
                    + ("恢复" if purpose == "recovery" else "绑定验证")
                    + "验证码："
                    + code
                    + "\n\n5 分钟内有效。不要转发；非本人请求请忽略。",
                    dedup_key="admin-security-" + id,
                    caller="admin-security",
                    kind="admin_security",
                )
                if result["status"] not in ("api_accepted", "no_error_reported", "phone_confirmed"):
                    self.db.execute("DELETE FROM admin_recovery_challenges WHERE id=?", (id,))
                    if purpose == "binding":
                        raise ClientError("admin_code_send_unconfirmed", 409)
            except Exception:
                self.db.execute("DELETE FROM admin_recovery_challenges WHERE id=?", (id,))
                if purpose == "binding":
                    raise ClientError("admin_code_send_unconfirmed", 409) from None

        if purpose == "recovery" and background_tasks is not None:
            # Starlette sends the identical public response before any platform I/O.
            background_tasks.add_task(deliver)
        else:
            await deliver()
        self.accounts.audit(
            "recovery_request" if purpose == "recovery" else "recovery_bind_request"
        )
        return {"challenge_id": id, "expires_in": 300, "accepted": True}

    def check(self, id, code, purpose):
        row = self.db.execute(
            "SELECT * FROM admin_recovery_challenges WHERE id=? AND purpose=?", (id, purpose)
        ).fetchone()
        if not row or row["expires_at"] < time.time() or row["attempts"] >= 5:
            raise ClientError("invalid_admin_code", 400)
        self.db.execute(
            "UPDATE admin_recovery_challenges SET attempts=attempts+1 WHERE id=?", (id,)
        )
        valid = hmac.compare_digest(
            hashlib.sha256((id + ":" + code).encode()).hexdigest(), row["code_hash"]
        )
        account = self.accounts.account()
        try:
            destination = bool(
                row["bot_id"] and self.fingerprint(row["bot_id"]) == row["fingerprint"]
            )
        except Exception:
            destination = False
        if not valid or not destination or not account or account["version"] != row["version"]:
            raise ClientError("invalid_admin_code", 400)
        return row

    def bind(self, id, code):
        row = self.check(id, code, "binding")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.accounts.account()["version"] != row["version"]:
                raise ClientError("admin_state_changed", 409)
            self.db.execute(
                "INSERT OR REPLACE INTO admin_recovery_bindings VALUES (?,?,?)",
                (row["bot_id"], row["fingerprint"], time.time()),
            )
            self.db.execute("DELETE FROM admin_recovery_challenges WHERE id=?", (id,))
            self.accounts.audit("recovery_bind", "web:" + row["bot_id"])
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"bindings": self.bindings()}
