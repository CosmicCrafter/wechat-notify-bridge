"""Administrator writes into the existing phone/caller ledger, never an Agent."""

import hashlib
import json
from wechat_bridge.storage.client_registry import ClientError


class AdminConversations:
    def __init__(self, store):
        self.store, self.db, self.portal = store, store.db, store.portal
        self.db.execute("""CREATE TABLE IF NOT EXISTS admin_conversation_requests (
            request_id TEXT PRIMARY KEY,client_id TEXT NOT NULL,payload_hash TEXT NOT NULL,
            conversation_id TEXT NOT NULL)""")

    def receiving(self, client_id):
        client = self.store.clients.get(client_id)
        if not client["enabled"]:
            raise ClientError("client_disabled", 409)
        if not self.store.clients.credentials.can_receive(client_id):
            raise ClientError("client_receive_unavailable", 409)
        return client

    def create(self, client_id, name, text, request_id, receiver_mode="legacy"):
        self.receiving(client_id)
        if not text.strip():
            raise ClientError("empty_message", 422)
        payload_hash = hashlib.sha256(
            json.dumps(
                [client_id, name, text] + ([receiver_mode] if receiver_mode != "legacy" else []),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            previous = self.db.execute(
                "SELECT * FROM admin_conversation_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            if previous:
                if previous["payload_hash"] != payload_hash:
                    raise ClientError("request_id_content_conflict", 409)
                cid = previous["conversation_id"]
                self.portal.owner_chat(cid, writable=True)
            else:
                chat = self.store.conversations.register(
                    client_id, "admin:" + request_id, name, receiver_mode
                )
                cid = chat["id"]
                self.db.execute(
                    "INSERT INTO admin_conversation_requests VALUES (?,?,?,?)",
                    (request_id, client_id, payload_hash, cid),
                )
            result = self.portal.reply(cid, text, request_id, source="admin", transaction=False)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return dict(result, conversation=self.portal.owner_chat(cid), receive_method="http_inbox")

    def reply(self, cid, text, request_id, attachment_ids):
        row = self.db.execute(
            "SELECT client_id FROM conversations WHERE id=? AND deleted=0", (cid,)
        ).fetchone()
        if not row:
            raise ClientError("conversation_not_found", 404)
        self.receiving(row[0])
        if not text.strip() and not attachment_ids:
            raise ClientError("empty_message", 422)
        return self.portal.reply(cid, text, request_id, attachment_ids, source="admin")
