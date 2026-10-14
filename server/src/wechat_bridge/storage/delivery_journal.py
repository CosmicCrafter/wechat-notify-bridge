"""Encrypted logical request and separate transport attempts; old rows stay unknown."""

import hashlib
import json
import time


class DeliveryJournal:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS delivery_requests (
            key TEXT PRIMARY KEY,client_id TEXT,bot_id TEXT NOT NULL,conversation_id TEXT,
            dedup_hash TEXT NOT NULL,encrypted BLOB);
          CREATE INDEX IF NOT EXISTS delivery_request_dedup ON delivery_requests(dedup_hash);
          CREATE TABLE IF NOT EXISTS delivery_attempts (
            key TEXT NOT NULL,attempt INTEGER NOT NULL,status TEXT NOT NULL,
            started_at REAL NOT NULL,finished_at REAL,error_code TEXT,phase TEXT,
            platform_request_started INTEGER,PRIMARY KEY(key,attempt));
        """)

    def begin(self, key, client_id, bot_id, cid, request):
        self.db.execute(
            "INSERT OR IGNORE INTO delivery_requests VALUES (?,?,?,?,?,?)",
            (
                key,
                client_id,
                bot_id,
                cid,
                hashlib.sha256(request["dedup_key"].encode()).hexdigest(),
                self.store.cipher.encrypt(json.dumps(request, ensure_ascii=False).encode()),
            ),
        )
        attempt = self.db.execute(
            "SELECT coalesce(max(attempt),0)+1 FROM delivery_attempts WHERE key=?", (key,)
        ).fetchone()[0]
        self.db.execute(
            "INSERT INTO delivery_attempts(key,attempt,status,started_at) VALUES (?,?,'attempting',?)",
            (key, attempt, time.time()),
        )

    def finish(self, key, status, error, diagnostics):
        self.db.execute(
            "UPDATE delivery_attempts SET status=?,finished_at=?,error_code=?,phase=?,platform_request_started=? WHERE key=? AND attempt=(SELECT max(attempt) FROM delivery_attempts WHERE key=?)",
            (
                status,
                time.time(),
                error,
                diagnostics.get("phase"),
                diagnostics.get("platform_request_started"),
                key,
                key,
            ),
        )

    def request(self, key):
        row = self.db.execute("SELECT * FROM delivery_requests WHERE key=?", (key,)).fetchone()
        if not row or not row["encrypted"]:
            return None
        return dict(row, request=json.loads(self.store.cipher.decrypt(row["encrypted"])))

    def public(self, key):
        row = self.request(key)
        attempts = [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM delivery_attempts WHERE key=? ORDER BY attempt", (key,)
            )
        ]
        return {
            "dedup_key": row["request"]["dedup_key"] if row else None,
            "text": row["request"]["text"] if row else None,
            "attempts": attempts,
            "history_complete": bool(row),
        }
