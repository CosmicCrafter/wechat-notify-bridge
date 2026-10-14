"""Application credentials, independent of stable app identity and OAuth grants."""

import hashlib
import secrets
import time
from wechat_bridge.storage.client_registry import ClientError


class Credentials:
    def __init__(self, clients):
        self.clients, self.db = clients, clients.db
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS api_credentials (
            id TEXT PRIMARY KEY,client_id TEXT NOT NULL,key_hash TEXT UNIQUE NOT NULL,
            suffix TEXT,status TEXT NOT NULL,created_at REAL NOT NULL,expires_at REAL,
            revoked_at REAL,last_used_at REAL,format TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS credential_client ON api_credentials(client_id,status);
        """)
        self.migrate()

    def migrate(self):
        for row in self.db.execute(
            "SELECT * FROM api_clients a WHERE NOT EXISTS (SELECT 1 FROM api_credentials k WHERE k.client_id=a.id)"
        ).fetchall():
            self.issue(
                row["id"],
                row["key_hash"],
                None,
                "legacy",
                created_at=row["created_at"],
                status="active" if row["enabled"] else "revoked",
            )

    def expire(self):
        self.db.execute(
            "UPDATE api_credentials SET status='expired' WHERE status='retiring' AND expires_at<=?",
            (time.time(),),
        )

    def issue(self, client_id, digest, suffix, format, *, created_at=None, status="active"):
        id = "nbk_" + secrets.token_hex(8)
        self.db.execute(
            "INSERT INTO api_credentials VALUES (?,?,?,?,?,?,NULL,NULL,NULL,?)",
            (
                id,
                client_id,
                digest,
                suffix,
                status,
                created_at if created_at is not None else time.time(),
                format,
            ),
        )
        return id

    def public(self, row):
        result = {
            name: row[name]
            for name in (
                "id",
                "client_id",
                "suffix",
                "status",
                "created_at",
                "expires_at",
                "revoked_at",
                "last_used_at",
                "format",
            )
        }
        if row["suffix"] is None:
            result["created_at"] = None
        return result

    def list(self, client_id):
        self.clients.get(client_id)
        self.expire()
        return [
            self.public(r)
            for r in self.db.execute(
                "SELECT * FROM api_credentials WHERE client_id=? ORDER BY created_at DESC,id",
                (client_id,),
            )
        ]

    def valid(self, client_id, digest, credential_id=None):
        row = self.db.execute(
            "SELECT * FROM api_credentials WHERE client_id=? AND key_hash=? AND status IN ('active','retiring') AND (expires_at IS NULL OR expires_at>?)",
            (client_id, digest, time.time()),
        ).fetchone()
        return row if row and (credential_id is None or row["id"] == credential_id) else None

    def can_receive(self, client_id):
        client = self.clients.get(client_id)
        if not client["enabled"]:
            return False
        api = self.db.execute(
            "SELECT 1 FROM api_credentials WHERE client_id=? AND status IN ('active','retiring') AND (expires_at IS NULL OR expires_at>?) LIMIT 1",
            (client_id, time.time()),
        ).fetchone()
        if api:
            return True
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='oauth_tokens'").fetchone():
            return bool(
                self.db.execute(
                    "SELECT 1 FROM oauth_tokens WHERE api_client=? AND key_hash=? AND expires_at>? LIMIT 1",
                    (client_id, client["key_hash"], time.time()),
                ).fetchone()
            )
        return False

    def rotate(self, client_id, overlap_seconds=3600):
        client = self.clients.get(client_id)
        if not client["enabled"]:
            raise ClientError("client_disabled", 409)
        if not 0 <= overlap_seconds <= 86400:
            raise ClientError("invalid_key_overlap", 422)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.expire()
            if self.db.execute(
                "SELECT 1 FROM api_credentials WHERE client_id=? AND status='retiring'",
                (client_id,),
            ).fetchone():
                raise ClientError("credential_rotation_pending", 409)
            now = time.time()
            self.db.execute(
                "UPDATE api_credentials SET status=?,expires_at=?,revoked_at=? WHERE client_id=? AND status='active'",
                (
                    "retiring" if overlap_seconds else "revoked",
                    now + overlap_seconds,
                    None if overlap_seconds else now,
                    client_id,
                ),
            )
            key = "nb_" + secrets.token_urlsafe(32)
            id = self.issue(client_id, hashlib.sha256(key.encode()).hexdigest(), key[-4:], "nb")
            self.db.execute("UPDATE api_clients SET rotated_at=? WHERE id=?", (now, client_id))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {
            "credential": next(c for c in self.list(client_id) if c["id"] == id),
            "api_key": key,
            "overlap_seconds": overlap_seconds,
        }

    def finish(self, client_id):
        self.clients.get(client_id)
        self.db.execute(
            "UPDATE api_credentials SET status='revoked',revoked_at=? WHERE client_id=? AND status='retiring'",
            (time.time(), client_id),
        )
        return {"credentials": self.list(client_id)}

    def revoke(self, client_id, id):
        self.clients.get(client_id)
        row = self.db.execute(
            "SELECT * FROM api_credentials WHERE client_id=? AND id=?", (client_id, id)
        ).fetchone()
        if not row:
            raise ClientError("credential_not_found", 404)
        self.db.execute(
            "UPDATE api_credentials SET status='revoked',revoked_at=coalesce(revoked_at,?) WHERE client_id=? AND id=?",
            (time.time(), client_id, id),
        )
        return {"credentials": self.list(client_id)}
