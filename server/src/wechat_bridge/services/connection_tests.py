"""Separate platform send evidence from an authenticated owner echo."""

import asyncio
import hashlib
import secrets
import time
from wechat_bridge.storage.client_registry import ClientError


class ConnectionTests:
    def __init__(self, store, channels, recovery):
        self.store, self.db, self.channels, self.recovery = store, store.db, channels, recovery
        self.lock = asyncio.Lock()
        self.db.execute("""CREATE TABLE IF NOT EXISTS connection_tests (
          bot_id TEXT PRIMARY KEY,id TEXT NOT NULL,fingerprint TEXT NOT NULL,nonce_hash TEXT NOT NULL,
          started_at REAL NOT NULL,expires_at REAL NOT NULL,send_status TEXT NOT NULL,received_at REAL)""")
        store.connection_tests = self

    def snapshot(self, bot_id):
        row = self.db.execute("SELECT * FROM connection_tests WHERE bot_id=?", (bot_id,)).fetchone()
        if not row:
            return {"state": "not_tested", "send_status": None, "receive_confirmed": False}
        try:
            current = self.recovery.fingerprint(bot_id) == row["fingerprint"]
        except Exception:
            current = False
        result = {
            k: row[k] for k in ("id", "started_at", "expires_at", "send_status", "received_at")
        }
        confirmed = bool(row["received_at"] and current)
        result.update(
            receive_confirmed=confirmed,
            state="configuration_changed"
            if not current
            else "received"
            if confirmed
            else "expired"
            if row["expires_at"] < time.time()
            else "awaiting_owner_echo",
        )
        return result

    async def send(self, bot_id):
        async with self.lock:
            previous = self.db.execute(
                "SELECT started_at FROM connection_tests WHERE bot_id=?", (bot_id,)
            ).fetchone()
            if previous and time.time() - previous[0] < 10:
                raise ClientError("connection_test_retry_later", 429)
            fingerprint = self.recovery.fingerprint(bot_id)
            id = secrets.token_hex(16)
            nonce = "nb-test:" + secrets.token_hex(16)
            now = time.time()
            self.db.execute(
                "INSERT OR REPLACE INTO connection_tests VALUES (?,?,?,?,?,?,'attempting',NULL)",
                (
                    bot_id,
                    id,
                    fingerprint,
                    hashlib.sha256(nonce.encode()).hexdigest(),
                    now,
                    now + 600,
                ),
            )
            try:
                result = await self.channels.adapter(bot_id).send(
                    "Notify Bridge 连接测试\n\n请从本人手机将下面一行原样回复给当前 Bot，验证回程：\n"
                    + nonce
                    + "\n\n10 分钟内有效。",
                    dedup_key="connection-test-" + id,
                    caller="connection-test",
                    kind="connection_test",
                )
                status = result["status"]
            except Exception:
                status = "unconfirmed_do_not_retry"
            self.db.execute(
                "UPDATE connection_tests SET send_status=? WHERE bot_id=? AND id=?",
                (status, bot_id, id),
            )
            return self.snapshot(bot_id)

    def receive(self, bot_id, text, at):
        row = self.db.execute("SELECT * FROM connection_tests WHERE bot_id=?", (bot_id,)).fetchone()
        if not row or row["expires_at"] < time.time() or at < row["started_at"] - 1:
            return False
        if hashlib.sha256(text.strip().encode()).hexdigest() != row["nonce_hash"]:
            return False
        try:
            valid = self.recovery.fingerprint(bot_id) == row["fingerprint"]
        except Exception:
            valid = False
        if valid:
            self.db.execute(
                "UPDATE connection_tests SET received_at=coalesce(received_at,?) WHERE bot_id=?",
                (time.time(), bot_id),
            )
            return True
        return False

    def impact(self, bot_id):
        self.channels.registry.get(bot_id)
        apps = [
            dict(row, is_default=bool(row["is_default"]))
            for row in self.db.execute(
                "SELECT a.id,a.name,a.enabled,coalesce(d.bot_id=gr.bot_id,0) AS is_default FROM client_bot_grants gr JOIN api_clients a ON a.id=gr.client_id LEFT JOIN client_bot_defaults d ON d.client_id=a.id WHERE gr.bot_id=? ORDER BY a.name",
                (bot_id,),
            )
        ]
        bindings = self.recovery.bindings()
        return {
            "applications": apps,
            "recovery_bound": any(b["bot_id"] == bot_id for b in bindings),
            "last_recovery_protected": any(b["bot_id"] == bot_id for b in bindings)
            and not any(b["bot_id"] != bot_id and b["valid"] for b in bindings),
            "test": self.snapshot(bot_id),
        }
