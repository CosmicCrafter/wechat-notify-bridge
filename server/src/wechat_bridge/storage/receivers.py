"""Conversation-scoped capabilities. Possession does not attest an AI host's chat identity."""

import hashlib
import hmac
import secrets
import time
import uuid

from wechat_bridge.storage.client_registry import ClientError


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Receivers:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS receiver_bindings (
            id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL,client_id TEXT NOT NULL,
            role TEXT NOT NULL,status TEXT NOT NULL,host_type TEXT NOT NULL,label TEXT NOT NULL,
            token_hash TEXT UNIQUE,pair_hash TEXT UNIQUE,challenge_hash TEXT,
            created_at REAL NOT NULL,verified_at REAL,expires_at REAL NOT NULL,challenge_until REAL NOT NULL,
            revoked_at REAL);
          CREATE UNIQUE INDEX IF NOT EXISTS receiver_primary ON receiver_bindings(conversation_id)
            WHERE role='primary' AND status IN ('pending','active');
          CREATE TABLE IF NOT EXISTS receiver_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,conversation_id TEXT NOT NULL,binding_id TEXT,
            action TEXT NOT NULL,source TEXT NOT NULL,created_at REAL NOT NULL);
        """)

    def audit(self, cid, bid, action, source):
        self.db.execute(
            "INSERT INTO receiver_audit(conversation_id,binding_id,action,source,created_at) VALUES (?,?,?,?,?)",
            (cid, bid, action, source, time.time()),
        )

    def summary(self, cid):
        chat = self.db.execute(
            "SELECT receiver_mode FROM conversations WHERE id=?", (cid,)
        ).fetchone()
        row = self.db.execute(
            "SELECT * FROM receiver_bindings WHERE conversation_id=? AND role='primary' ORDER BY created_at DESC,id DESC LIMIT 1",
            (cid,),
        ).fetchone()
        mode = chat[0] if chat else "legacy"
        status = "application_scope" if mode == "legacy" else "waiting_binding"
        if mode == "protected" and row:
            status = "expired" if row["expires_at"] <= time.time() else row["status"]
            if status == "pending" and row["challenge_until"] <= time.time():
                status = "pairing_expired"
        return {
            "mode": mode,
            "status": status,
            "binding_id": row["id"] if row else None,
            "host_type": row["host_type"] if row else None,
            "label": row["label"] if row else None,
            "verified_at": row["verified_at"] if row else None,
            "expires_at": row["expires_at"] if row else None,
            "assurance": "conversation_capability"
            if status == "active"
            else "application_only"
            if mode == "legacy"
            else "unverified",
            "host_identity": "unverified",
        }

    def issue(
        self,
        client_id,
        cid,
        *,
        role="primary",
        host_type="unknown",
        label="",
        pairing=False,
        replace=False,
        source="admin",
    ):
        chat = self.store.conversations.get(client_id, cid, require_active=True)
        if chat["receiver_mode"] != "protected":
            raise ClientError("receiver_protected_conversation_required", 409)
        owned = not self.db.in_transaction
        if owned:
            self.db.execute("BEGIN IMMEDIATE")
        try:
            current = self.db.execute(
                "SELECT * FROM receiver_bindings WHERE conversation_id=? AND role=? AND status IN ('pending','active')",
                (cid, role),
            ).fetchone()
            if current and role == "primary" and not replace:
                raise ClientError("receiver_primary_exists", 409)
            if current and role == "primary":
                self.revoke(cid, current["id"], source=source)
            now, bid = time.time(), uuid.uuid4().hex
            token = "nrb_" + secrets.token_urlsafe(32) if not pairing else None
            pair = "nrp_" + secrets.token_urlsafe(32) if pairing else None
            challenge = secrets.token_urlsafe(32) if token else None
            self.db.execute(
                "INSERT INTO receiver_bindings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                (
                    bid,
                    cid,
                    client_id,
                    role,
                    "pending",
                    host_type,
                    label,
                    digest(token) if token else None,
                    digest(pair) if pair else None,
                    digest(challenge) if challenge else None,
                    now,
                    None,
                    now + 86400,
                    now + 300,
                ),
            )
            self.audit(cid, bid, "paired" if pairing else "issued", source)
            if owned:
                self.db.commit()
        except Exception:
            if owned:
                self.db.rollback()
            raise
        result = {
            "binding_id": bid,
            "conversation_id": cid,
            "host_identity": "unverified",
            "role": role,
        }
        if pair:
            result.update(pairing_code=pair, pairing_expires_at=now + 300)
        else:
            result.update(receiver_token=token, challenge=challenge)
        return result

    def revoke(self, cid, bid, *, source="admin"):
        row = self.db.execute(
            "SELECT * FROM receiver_bindings WHERE id=? AND conversation_id=?", (bid, cid)
        ).fetchone()
        if not row:
            raise ClientError("receiver_not_found", 404)
        self.db.execute(
            "UPDATE receiver_bindings SET status='revoked',pair_hash=NULL,challenge_hash=NULL,revoked_at=? WHERE id=?",
            (time.time(), bid),
        )
        self.audit(cid, bid, "revoked", source)
        # Additive F02-2 state is optional when reading a pre-lease schema.
        if "binding_id" in {r["name"] for r in self.db.execute("PRAGMA table_info(inbox_claims)")}:
            self.db.execute(
                "UPDATE inbox_claims SET lease_expires=? WHERE binding_id=? AND status IN ('claimed','processing')",
                (time.time(), bid),
            )
        if self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='mcp_event_subscriptions'"
        ).fetchone():
            self.db.execute(
                "UPDATE mcp_event_subscriptions SET status='revoked' WHERE conversation=?", (cid,)
            )
        return self.summary(cid)

    def exchange(self, identity, code):
        self.store.clients.revalidate(identity)
        row = self.db.execute(
            "SELECT * FROM receiver_bindings WHERE pair_hash=? AND client_id=? AND status='pending'",
            (digest(code), identity.id),
        ).fetchone()
        if not row or row["challenge_until"] <= time.time():
            raise ClientError("receiver_pairing_invalid", 400)
        self.store.conversations.get(identity.id, row["conversation_id"], require_active=True)
        token, challenge = "nrb_" + secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.db.execute(
            "UPDATE receiver_bindings SET pair_hash=NULL,token_hash=?,challenge_hash=?,challenge_until=? WHERE id=?",
            (digest(token), digest(challenge), time.time() + 300, row["id"]),
        )
        self.audit(row["conversation_id"], row["id"], "pair_exchanged", "client:" + identity.id)
        return {
            "receiver_token": token,
            "challenge": challenge,
            "binding_id": row["id"],
            "conversation_id": row["conversation_id"],
            "role": row["role"],
            "host_identity": "unverified",
        }

    def resolve(self, identity, *, pending=False):
        self.store.clients.revalidate(identity)
        token_hash = getattr(identity, "receiver_hash", None)
        row = (
            self.db.execute(
                "SELECT * FROM receiver_bindings WHERE token_hash=? AND client_id=?",
                (token_hash, identity.id),
            ).fetchone()
            if token_hash
            else None
        )
        if (
            not row
            or row["status"] not in (("pending", "active") if pending else ("active",))
            or row["expires_at"] <= time.time()
        ):
            raise ClientError("receiver_access_denied", 403)
        return row

    def verify(self, identity, challenge):
        row = self.resolve(identity, pending=True)
        if row["status"] == "active":
            return {"receiver": self.summary(row["conversation_id"]), "duplicate": True}
        if row["challenge_until"] <= time.time() or not hmac.compare_digest(
            row["challenge_hash"] or "", digest(challenge)
        ):
            raise ClientError("receiver_challenge_invalid", 400)
        self.db.execute(
            "UPDATE receiver_bindings SET status='active',verified_at=?,challenge_hash=NULL WHERE id=?",
            (time.time(), row["id"]),
        )
        self.audit(
            row["conversation_id"], row["id"], "capability_verified", "client:" + identity.id
        )
        return {"receiver": self.summary(row["conversation_id"]), "duplicate": False}

    def authorize(self, identity, cid, *, write=False):
        chat = self.store.conversations.get(identity.id, cid)
        if chat["receiver_mode"] == "legacy" and not getattr(identity, "receiver_hash", None):
            return None
        row = self.resolve(identity)
        if row["conversation_id"] != cid or (write and row["role"] != "primary"):
            raise ClientError("receiver_scope_mismatch", 403)
        return row
