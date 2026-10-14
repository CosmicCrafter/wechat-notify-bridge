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
        columns = {r["name"] for r in self.db.execute("PRAGMA table_info(inbox_claims)")}
        for name, definition in [
            ("binding_id", "TEXT"),
            ("generation", "INTEGER NOT NULL DEFAULT 0"),
            ("lease_expires", "REAL"),
        ]:
            if name not in columns:
                self.db.execute("ALTER TABLE inbox_claims ADD COLUMN " + name + " " + definition)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS inbox_claim_audit (id INTEGER PRIMARY KEY AUTOINCREMENT,inbox_id INTEGER NOT NULL,generation INTEGER NOT NULL,binding_id TEXT,action TEXT NOT NULL,created_at REAL NOT NULL)"
        )

    def audit(self, iid, generation, bid, action):
        self.db.execute(
            "INSERT INTO inbox_claim_audit(inbox_id,generation,binding_id,action,created_at) VALUES (?,?,?,?,?)",
            (iid, generation, bid, action, time.time()),
        )

    def authorize(self, identity, inbox_id):
        self.store.clients.revalidate(identity)
        row = self.db.execute(
            "SELECT * FROM inbox WHERE id=? AND kind='message' AND route_status='direct'",
            (inbox_id,),
        ).fetchone()
        if not row:
            raise ClientError("inbox_message_not_found", 404)
        self.store.conversations.get(identity.id, row["conversation_id"], require_active=True)
        self.store.receivers.authorize(identity, row["conversation_id"], write=True)
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
            "generation": row["generation"],
            "binding_id": row["binding_id"],
            "lease_expires": row["lease_expires"],
            "lease_expired": bool(
                row["lease_expires"]
                and row["lease_expires"] <= time.time()
                and row["status"] in ("claimed", "processing")
            ),
        }

    def claim(self, identity, inbox_id, request_id, lease_seconds=120):
        message = self.authorize(identity, inbox_id)
        binding = self.store.receivers.authorize(identity, message["conversation_id"], write=True)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old = self.db.execute(
                "SELECT * FROM inbox_claims WHERE inbox_id=?", (inbox_id,)
            ).fetchone()
            duplicate = False
            if binding:
                if old and old["status"] in ("completed", "failed"):
                    if old["claim_id"] != request_id:
                        raise ClientError("inbox_processing_final", 409)
                    duplicate = True
                elif old and old["binding_id"] and old["lease_expires"] > time.time():
                    if old["claim_id"] != request_id or old["binding_id"] != binding["id"]:
                        raise ClientError("inbox_already_claimed", 409)
                    duplicate = True
                elif old and old["claim_id"] == request_id:
                    raise ClientError("inbox_claim_expired", 409)
                if not duplicate:
                    now = time.time()
                    generation = (old["generation"] if old else 0) + 1
                    self.db.execute(
                        "INSERT INTO inbox_claims(inbox_id,client_id,claim_id,status,claimed_at,updated_at,result,binding_id,generation,lease_expires) VALUES (?,?,?,'claimed',?,?,NULL,?,?,?) ON CONFLICT(inbox_id) DO UPDATE SET claim_id=excluded.claim_id,status='claimed',claimed_at=excluded.claimed_at,updated_at=excluded.updated_at,result=NULL,binding_id=excluded.binding_id,generation=excluded.generation,lease_expires=excluded.lease_expires",
                        (
                            inbox_id,
                            identity.id,
                            request_id,
                            now,
                            now,
                            binding["id"],
                            generation,
                            now + lease_seconds,
                        ),
                    )
                    self.audit(inbox_id, generation, binding["id"], "takeover" if old else "claim")
                    self.db.execute(
                        "UPDATE chat_messages SET status='claimed' WHERE inbox_id=?", (inbox_id,)
                    )
            elif old:
                if old["client_id"] != identity.id or old["claim_id"] != request_id:
                    raise ClientError("inbox_already_claimed", 409)
                duplicate = True
            else:
                now = time.time()
                self.db.execute(
                    "INSERT INTO inbox_claims(inbox_id,client_id,claim_id,status,claimed_at,updated_at,result) VALUES (?,?,?,'claimed',?,?,NULL)",
                    (inbox_id, identity.id, request_id, now, now),
                )
                self.db.execute(
                    "UPDATE chat_messages SET status='claimed' WHERE inbox_id=?", (inbox_id,)
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"processing": self.public(inbox_id), "duplicate": duplicate}

    def report(self, identity, inbox_id, claim_id, request_id, status, result, generation=None):
        message = self.authorize(identity, inbox_id)
        binding = self.store.receivers.authorize(identity, message["conversation_id"], write=True)
        digest = hashlib.sha256(
            json.dumps(
                [claim_id, status, result] + ([generation] if generation is not None else []),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT * FROM inbox_claims WHERE inbox_id=? AND client_id=? AND claim_id=?",
                (inbox_id, identity.id, claim_id),
            ).fetchone()
            if not row:
                raise ClientError("inbox_claim_required", 409)
            if binding and row["generation"] > 0:
                if row["binding_id"] != binding["id"] or generation != row["generation"]:
                    raise ClientError("inbox_fence_mismatch", 409)
                if (
                    row["status"] not in ("completed", "failed")
                    and row["lease_expires"] <= time.time()
                ):
                    raise ClientError("inbox_claim_expired", 409)
            elif binding and row["status"] not in ("completed", "failed"):
                raise ClientError("inbox_generation_required", 409)
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
                self.audit(inbox_id, row["generation"], row["binding_id"], status)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"processing": self.public(inbox_id), "duplicate": bool(old)}

    def renew(self, identity, inbox_id, claim_id, generation, lease_seconds):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            message = self.authorize(identity, inbox_id)
            binding = self.store.receivers.authorize(
                identity, message["conversation_id"], write=True
            )
            row = self.db.execute(
                "SELECT * FROM inbox_claims WHERE inbox_id=?", (inbox_id,)
            ).fetchone()
            if (
                not binding
                or not row
                or row["binding_id"] != binding["id"]
                or row["generation"] != generation
                or row["claim_id"] != claim_id
            ):
                raise ClientError("inbox_fence_mismatch", 409)
            if row["status"] not in ("claimed", "processing"):
                raise ClientError("inbox_processing_final", 409)
            if row["lease_expires"] <= time.time():
                raise ClientError("inbox_claim_expired", 409)
            self.db.execute(
                "UPDATE inbox_claims SET lease_expires=?,updated_at=? WHERE inbox_id=?",
                (time.time() + lease_seconds, time.time(), inbox_id),
            )
            self.audit(inbox_id, generation, binding["id"], "renew")
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"processing": self.public(inbox_id)}
