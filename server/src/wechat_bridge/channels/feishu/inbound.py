"""Authenticated inbound routing and task answers; no outgoing network calls."""

import hashlib
import json
import time
from wechat_bridge.api.schemas import TaskAnswer
from wechat_bridge.channels.feishu.cards import card
from wechat_bridge.config import chat_url
from wechat_bridge.storage.client_registry import ClientError
from wechat_bridge.core.errors import BridgeError


class FeishuInbound:
    def receive_message(self, event):
        config = self.ready()
        sender, msg = event.get("sender", {}), event.get("message", {})
        if (
            sender.get("sender_type") != "user"
            or sender.get("sender_id", {}).get("open_id") != config["owner_open_id"]
            or msg.get("chat_type") != "p2p"
            or msg.get("message_type") != "text"
        ):
            return {"ignored": True}
        message_id = msg.get("message_id")
        content = json.loads(msg.get("content", "{}"))
        text = content.get("text", "")
        if (
            not isinstance(message_id, str)
            or not message_id
            or not isinstance(text, str)
            or not text.strip()
            or len(text) > 20000
        ):
            raise BridgeError(422, "invalid_feishu_message")
        cid, routed, text, tag = self.conversations.route(text)
        original_text = content["text"]
        if msg.get("parent_id"):
            parent = self.state.parent(self.scope_name, msg["parent_id"])
            selected_cid = cid
            cid, routed = None, "unknown"
            if parent and parent["conversation_id"]:
                try:
                    chat = self.store.portal.owner_chat(parent["conversation_id"], writable=True)
                    client = self.store.db.execute(
                        "SELECT client_id FROM conversations WHERE id=?", (chat["id"],)
                    ).fetchone()
                    if not self.store.bots.allowed(client[0], self.bot_id):
                        raise ClientError("bot_access_denied", 403)
                    if selected_cid and selected_cid != parent["conversation_id"]:
                        routed, text = "conflict", original_text
                    else:
                        cid, routed = parent["conversation_id"], "direct"
                except ClientError:
                    routed = "unknown"
        elif cid:
            mode = self.store.db.execute(
                "SELECT receiver_mode FROM conversations WHERE id=?", (cid,)
            ).fetchone()
            if mode and mode[0] == "protected" and not (tag and tag.startswith("[conversation:")):
                cid, routed, text = None, "unassigned", original_text
        now = time.time()
        stamp = msg.get("create_time", "")
        at = min(now, int(stamp) / 1000) if isinstance(stamp, str) and stamp.isdigit() else now
        observer = getattr(self.store, "connection_tests", None)
        if observer and observer.receive(self.bot_id, text, at):
            self.store.set(self.scope_name + ":last_event_at", now)
            return {"accepted": True, "connection_test": True}
        identity = hashlib.sha256(
            (self.scope_name + ":" + config["app_id"] + ":" + message_id).encode()
        ).hexdigest()
        if self.store.db.execute("SELECT 1 FROM inbox WHERE identity=?", (identity,)).fetchone():
            return {"accepted": True, "duplicate": True}
        candidates = []
        if (
            routed == "direct"
            and msg.get("parent_id")
            and not text.lstrip().startswith("/")
            and now - at < 600
        ):
            parent = (
                self.state.parent(self.scope_name, msg["parent_id"])
                if msg.get("parent_id")
                else None
            )
            rows = self.store.db.execute(
                "SELECT t.* FROM task_cards t JOIN channel_outgoing o ON o.key=t.outgoing_key "
                "WHERE o.channel=? AND o.status='api_accepted' AND t.status='pending' AND t.expires_at>? AND t.created_at<=?",
                (self.scope_name, now, at),
            ).fetchall()
            for row in rows:
                if cid and row["conversation_id"] != cid:
                    continue
                if msg.get("parent_id") and (not parent or parent["key"] != row["outgoing_key"]):
                    continue
                try:
                    self.store.portal.owner_chat(row["conversation_id"], writable=True)
                    owner = self.store.db.execute(
                        "SELECT client_id FROM conversations WHERE id=?", (row["conversation_id"],)
                    ).fetchone()
                    task = self.store.portal.tasks.public(row)
                    if task["mode"] == "input" and self.store.bots.allowed(owner[0], self.bot_id):
                        candidates.append(row)
                except ClientError:
                    continue
        if len(candidates) == 1 and len(text) <= 2000:
            target = candidates[0]
            answer = self.store.portal.tasks.answer(
                target["conversation_id"],
                target["id"],
                TaskAnswer(request_id="feishu_" + identity[:32], text=text),
                source="feishu",
                bot_id=self.bot_id,
                inbox_identity=identity,
            )
            self.store.set(self.scope_name + ":last_event_at", now)
            return dict(
                accepted=True,
                duplicate=answer["duplicate"],
                task_id=target["id"],
                conversation_id=target["conversation_id"],
            )
        reply_hint = (
            "当前有多个待填写任务，请长按对应卡片，选择「回复」后重新发送内容。刚才的内容尚未提交给任何任务。"
            if len(candidates) > 1
            else None
        )
        if len(candidates) == 1 and len(text) > 2000:
            reply_hint = "回复内容过长，请缩短至 2000 字以内后重新发送。"
        command = (
            text.strip()
            if text.strip() in ("/help", "/status", "/list", "/web") and routed == "shared"
            else None
        )
        body = dict(text=text, source="feishu", item_types=[1], attachments=[], bot_id=self.bot_id)
        if tag:
            body["routing_tag"] = tag
        db = self.store.db
        db.execute("BEGIN IMMEDIATE")
        try:
            cursor = db.execute(
                "INSERT OR IGNORE INTO inbox(identity,received_at,message_at,encrypted,kind,conversation_id,route_status,bot_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    identity,
                    now,
                    at,
                    self.state.encrypt(body),
                    "command" if command or reply_hint else "message",
                    cid,
                    routed,
                    self.bot_id,
                ),
            )
            if cursor.rowcount and cid and not reply_hint:
                self.store.portal.add(
                    cid,
                    "user",
                    "feishu",
                    text,
                    "pending",
                    inbox_id=cursor.lastrowid,
                    at=at,
                    bot_id=self.bot_id,
                )
            if cursor.rowcount and (command or reply_hint) and now - at < 600:
                reply = reply_hint or self.command_text(command)
                db.execute(
                    "INSERT INTO channel_commands(id,channel,created_at,encrypted) VALUES (?,?,?,?)",
                    (identity, self.scope_name, now, self.state.encrypt({"text": reply})),
                )
            self.store.set(self.scope_name + ":last_event_at", now)
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {"accepted": True, "duplicate": cursor.rowcount == 0}

    def receive_card(self, event):
        config = self.ready()
        if event.get("operator", {}).get("open_id") != config["owner_open_id"]:
            return {"toast": {"type": "error", "content": "仅配对用户可以回复"}}
        try:
            action, context = event.get("action", {}), event.get("context", {})
            value = action.get("value") or {}
            cid, tid = value.get("conversation_id"), value.get("task_id")
            row = self.store.portal.tasks.row(cid, tid)
            parent = self.state.parent(self.scope_name, context.get("open_message_id", ""))
            if not parent or parent["key"] != row["outgoing_key"]:
                raise ClientError("invalid_task_callback", 403)
            client = self.store.db.execute(
                "SELECT client_id FROM conversations WHERE id=?", (cid,)
            ).fetchone()
            if not self.store.bots.allowed(client[0], self.bot_id):
                raise ClientError("bot_access_denied", 403)
            fields = action.get("form_value") or {}
            body = TaskAnswer(
                request_id="feishu_" + hashlib.sha256((cid + tid).encode()).hexdigest()[:32],
                choice_id=value.get("choice_id") or fields.get("choice_id") or None,
                choice_ids=fields.get("choice_ids") or None,
                text=fields.get("reply_text") or "",
                field_values={k[6:]: v for k, v in fields.items() if k.startswith("field_")},
            )
            answer = self.store.portal.tasks.answer(
                cid, tid, body, source="feishu", bot_id=self.bot_id
            )
            chat = self.store.portal.owner_chat(cid)
            label = "[" + chat["caller"] + "-" + chat["name"] + "]"
            projected = card("", label, chat_url(cid), answer["task"])
            self.store.set(self.scope_name + ":last_event_at", time.time())
            return dict(
                toast=dict(
                    type="success",
                    content="已提交" if not answer["duplicate"] else "已提交，请勿重复操作",
                ),
                card=dict(type="raw", data=projected),
            )
        except (ClientError, ValueError, TypeError, AttributeError):
            return {
                "toast": {"type": "error", "content": "请检查填写内容；任务可能已结束或会话已归档"}
            }
