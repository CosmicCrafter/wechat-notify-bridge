"""Archive, mute and external stop acknowledgement are independent control planes."""

import hashlib
import json
import time
from wechat_bridge.storage.client_registry import ClientError


class Lifecycle:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript("""CREATE TABLE IF NOT EXISTS conversation_runtime (
          conversation_id TEXT PRIMARY KEY,muted INTEGER NOT NULL DEFAULT 0,
          monitor_status TEXT NOT NULL DEFAULT 'not_declared',owner_binding TEXT,
          reported_at REAL,stop_id TEXT,stop_requested_at REAL,stop_deadline REAL,
          stopped_at REAL,stop_message_id INTEGER,stop_inbox_id INTEGER);
          CREATE TABLE IF NOT EXISTS monitor_reports (
          conversation_id TEXT NOT NULL,request_id TEXT NOT NULL,payload_hash TEXT NOT NULL,PRIMARY KEY(conversation_id,request_id));
        """)

    def row(self, cid):
        self.db.execute(
            "INSERT OR IGNORE INTO conversation_runtime(conversation_id) VALUES (?)", (cid,)
        )
        return self.db.execute(
            "SELECT * FROM conversation_runtime WHERE conversation_id=?", (cid,)
        ).fetchone()

    def public(self, cid):
        row = self.db.execute(
            "SELECT * FROM conversation_runtime WHERE conversation_id=?", (cid,)
        ).fetchone()
        value = (
            dict(row)
            if row
            else {"conversation_id": cid, "muted": 0, "monitor_status": "not_declared"}
        )
        value["muted"] = bool(value["muted"])
        if value["monitor_status"] == "stop_requested" and value["stop_deadline"] <= time.time():
            value["monitor_status"] = "stop_unconfirmed"
        value["physical_execution_verified"] = False
        return value

    def assert_can_close(self, cid):
        if self.public(cid)["monitor_status"] in ("running", "stop_requested", "stop_unconfirmed"):
            raise ClientError("external_stop_confirmation_required", 409)

    def archive(self, cid, archived):
        self.store.portal.owner_chat(cid)
        self.db.execute("UPDATE conversations SET archived=? WHERE id=?", (int(archived), cid))
        self.store.receivers.audit(cid, None, "archive" if archived else "unarchive", "owner")
        return self.store.portal.owner_chat(cid)

    def mute(self, cid, muted):
        self.store.portal.owner_chat(cid)
        self.row(cid)
        self.db.execute(
            "UPDATE conversation_runtime SET muted=? WHERE conversation_id=?", (int(muted), cid)
        )
        self.store.receivers.audit(cid, None, "mute" if muted else "unmute", "owner")
        return self.public(cid)

    def stop(self, cid, request_id):
        self.store.portal.owner_chat(cid, writable=True)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.row(cid)
            if row["stop_id"]:
                self.db.commit()
                return self.public(cid)
            now = time.time()
            result = self.store.portal.reply(
                cid,
                "【请求结束外部监控】请实际停止后报告确认；本消息不代表监控已停止。",
                request_id,
                source="admin",
                transaction=False,
            )
            mid = result["message"]["id"]
            iid = self.db.execute(
                "SELECT inbox_id FROM chat_messages WHERE id=?", (mid,)
            ).fetchone()[0]
            raw = self.db.execute("SELECT encrypted FROM inbox WHERE id=?", (iid,)).fetchone()[0]
            content = json.loads(self.store.cipher.decrypt(raw))
            content.update(
                kind="control", control={"action": "stop_monitor", "request_id": request_id}
            )
            self.db.execute(
                "UPDATE inbox SET encrypted=? WHERE id=?",
                (self.store.cipher.encrypt(json.dumps(content, ensure_ascii=False).encode()), iid),
            )
            self.db.execute(
                "UPDATE conversation_runtime SET monitor_status='stop_requested',stop_id=?,stop_requested_at=?,stop_deadline=?,stop_message_id=?,stop_inbox_id=? WHERE conversation_id=?",
                (request_id, now, now + 300, mid, iid, cid),
            )
            self.store.receivers.audit(cid, row["owner_binding"], "stop_requested", "owner")
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.public(cid)

    def report(
        self, identity, cid, request_id, status, stop_id=None, claim_id=None, generation=None
    ):
        binding = self.store.receivers.authorize(identity, cid, write=True)
        if not binding:
            raise ClientError("receiver_protected_conversation_required", 409)
        payload = hashlib.sha256(str((status, stop_id)).encode()).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.row(cid)
            previous = self.db.execute(
                "SELECT payload_hash FROM monitor_reports WHERE conversation_id=? AND request_id=?",
                (cid, request_id),
            ).fetchone()
            if previous:
                if previous[0] != payload:
                    raise ClientError("request_id_content_conflict", 409)
                self.db.commit()
                return dict(self.public(cid), duplicate=True)
            if status == "running":
                if row["monitor_status"] != "not_declared":
                    raise ClientError("monitor_state_conflict", 409)
                self.db.execute(
                    "UPDATE conversation_runtime SET monitor_status='running',owner_binding=?,reported_at=? WHERE conversation_id=?",
                    (binding["id"], time.time(), cid),
                )
            else:
                if (
                    not row["stop_id"]
                    or stop_id != row["stop_id"]
                    or row["monitor_status"] != "stop_requested"
                ):
                    raise ClientError("monitor_stop_request_required", 409)
                if row["owner_binding"] and row["owner_binding"] != binding["id"]:
                    raise ClientError("monitor_owner_changed", 409)
                claim = self.db.execute(
                    "SELECT * FROM inbox_claims WHERE inbox_id=?", (row["stop_inbox_id"],)
                ).fetchone()
                if (
                    not claim
                    or claim["claim_id"] != claim_id
                    or claim["generation"] != generation
                    or claim["binding_id"] != binding["id"]
                    or claim["lease_expires"] <= time.time()
                ):
                    raise ClientError("monitor_stop_claim_required", 409)
                self.db.execute(
                    "UPDATE inbox_claims SET status='completed',updated_at=?,result=? WHERE inbox_id=?",
                    (
                        time.time(),
                        self.store.cipher.encrypt("执行端已确认停止".encode()),
                        row["stop_inbox_id"],
                    ),
                )
                self.store.claims.audit(
                    row["stop_inbox_id"], generation, binding["id"], "stop_confirmed"
                )
                self.db.execute(
                    "UPDATE conversation_runtime SET monitor_status='stopped',stopped_at=?,reported_at=? WHERE conversation_id=?",
                    (time.time(), time.time(), cid),
                )
                self.db.execute("UPDATE conversations SET active=0 WHERE id=?", (cid,))
                for item in self.db.execute(
                    "SELECT id FROM receiver_bindings WHERE conversation_id=? AND status IN ('active','pending')",
                    (cid,),
                ).fetchall():
                    self.store.receivers.revoke(cid, item["id"], source="executor_stop_ack")
                self.db.execute(
                    "UPDATE chat_messages SET status='completed' WHERE id=?",
                    (row["stop_message_id"],),
                )
            self.db.execute(
                "INSERT INTO monitor_reports VALUES (?,?,?)", (cid, request_id, payload)
            )
            self.store.receivers.audit(cid, binding["id"], "monitor_" + status, "executor")
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return dict(self.public(cid), duplicate=False)
