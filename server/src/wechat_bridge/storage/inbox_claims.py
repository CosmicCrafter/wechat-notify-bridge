"""Explicit caller acknowledgements. Reading inbox alone never means execution."""

import hashlib
import json
import time
from wechat_bridge.storage.client_registry import ClientError


class InboxClaims:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS inbox_claims (
          inbox_id INTEGER PRIMARY KEY,client_id TEXT NOT NULL,claim_id TEXT NOT NULL,
          status TEXT NOT NULL,claimed_at REAL NOT NULL,updated_at REAL NOT NULL,result BLOB);
        CREATE TABLE IF NOT EXISTS inbox_reports (
          inbox_id INTEGER NOT NULL,request_id TEXT NOT NULL,payload_hash TEXT NOT NULL,
          PRIMARY KEY(inbox_id,request_id));
        """)

    def authorize(self, identity, inbox_id):
        self.store.clients.revalidate(identity)
        row = self.db.execute(
            "SELECT * FROM inbox WHERE id=? AND kind='message' AND route_status='direct'",
            (inbox_id,),
        ).fetchone()
        if not row:
            raise ClientError("inbox_message_not_found", 404)
        self.store.conversations.get(identity.id, row["conversation_id"], require_active=True)
        self.store.receivers.authorize(identity,row["conversation_id"],write=True)
        if row["bot_id"] is not None and not self.store.bots.allowed(identity.id, row["bot_id"]):
            raise ClientError("inbox_message_not_found", 404)
        return row

    def public(self, inbox_id):
        row = self.db.execute("SELECT * FROM inbox_claims WHERE inbox_id=?", (inbox_id,)).fetchone()
        if not row:
            return None
        return {
            "claim_id": row["claim_id"],
            "status": row["status"],
            "claimed_at": row["claimed_at"],
            "updated_at": row["updated_at"],
            "result": self.store.cipher.decrypt(row["result"]).decode() if row["result"] else "",
        }

    def claim(self, identity, inbox_id, request_id):
        self.authorize(identity, inbox_id)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old = self.db.execute(
                "SELECT * FROM inbox_claims WHERE inbox_id=?", (inbox_id,)
            ).fetchone()
            if old and (old["client_id"] != identity.id or old["claim_id"] != request_id):
                raise ClientError("inbox_already_claimed", 409)
            if not old:
                now = time.time()
                self.db.execute(
                    "INSERT INTO inbox_claims VALUES (?,?,?,'claimed',?,?,NULL)",
                    (inbox_id, identity.id, request_id, now, now),
                )
                self.db.execute(
                    "UPDATE chat_messages SET status='claimed' WHERE inbox_id=?", (inbox_id,)
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"processing": self.public(inbox_id), "duplicate": bool(old)}

    def report(self, identity, inbox_id, claim_id, request_id, status, result):
        self.authorize(identity, inbox_id)
        digest = hashlib.sha256(
            json.dumps([claim_id, status, result], ensure_ascii=False).encode()
        ).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT * FROM inbox_claims WHERE inbox_id=? AND client_id=? AND claim_id=?",
                (inbox_id, identity.id, claim_id),
            ).fetchone()
            if not row:
                raise ClientError("inbox_claim_required", 409)
            old = self.db.execute(
                "SELECT * FROM inbox_reports WHERE inbox_id=? AND request_id=?",
                (inbox_id, request_id),
            ).fetchone()
            if old and old["payload_hash"] != digest:
                raise ClientError("request_id_content_conflict", 409)
            if not old:
                if row["status"] in ("completed", "failed"):
                    raise ClientError("inbox_processing_final", 409)
                self.db.execute(
                    "INSERT INTO inbox_reports VALUES (?,?,?)", (inbox_id, request_id, digest)
                )
                self.db.execute(
                    "UPDATE inbox_claims SET status=?,updated_at=?,result=? WHERE inbox_id=?",
                    (status, time.time(), self.store.cipher.encrypt(result.encode()), inbox_id),
                )
                self.db.execute(
                    "UPDATE chat_messages SET status=? WHERE inbox_id=?", (status, inbox_id)
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"processing": self.public(inbox_id), "duplicate": bool(old)}
