"""Feishu application bot: send journal, owner-only replies and native task answers."""

import asyncio
import hashlib
import json
import time

import httpx

from wechat_bridge.channels.feishu.cards import card
from wechat_bridge.config import chat_url
from wechat_bridge.services.commands import format_time
from wechat_bridge.channels.registry import BotConversations
from wechat_bridge.core.errors import BridgeError
from wechat_bridge.channels.feishu.inbound import FeishuInbound
from fastapi import HTTPException

BASE = "https://open.feishu.cn/open-apis"


class Rejected(Exception):
    def __init__(self, code):
        self.code = (
            str(code)
            if type(code) is int
            else code
            if code in ("invalid_auth_response", "invalid_response", "card_content_too_large")
            else "invalid_upstream_code"
        )


class Feishu(FeishuInbound):
    def __init__(self, store, transport=None, *, bot_id="feishu-default"):
        self.store, self.state = store, store.channels
        self.bot_id, self.scope_name = bot_id, "feishu:" + bot_id
        self.conversations = BotConversations(store.bots, bot_id)
        self.lock = asyncio.Lock()
        self.http = None
        self.transport = transport
        self.token, self.token_until = "", 0

    def config(self):
        return self.state.settings(self.scope_name)

    def prepare_config(self, value):
        value = dict(value)
        previous = self.config()
        for name in ("app_id", "owner_open_id", "app_secret", "verification_token", "encrypt_key"):
            if not value.get(name):
                value[name] = previous.get(name, "")
        if any(
            previous.get(k) and value.get(k) != previous[k] for k in ("app_id", "owner_open_id")
        ):
            # A different bot/owner must never inherit private history or old callback targets.
            raise BridgeError(409, "feishu_owner_mismatch")
        required = ("app_id", "app_secret", "owner_open_id", "verification_token", "encrypt_key")
        if value["enabled"] and any(not value.get(k) for k in required):
            raise BridgeError(422, "incomplete_feishu_configuration")
        for bot in self.store.bots.list():
            other = (
                self.state.settings("feishu:" + bot["id"]) if bot["platform"] == "feishu" else {}
            )
            if (
                bot["id"] != self.bot_id
                and value.get("app_id")
                and other.get("app_id") == value["app_id"]
            ):
                raise BridgeError(409, "bot_binding_conflict")
        if previous and (
            not value["enabled"]
            or any(
                value.get(f) != previous.get(f)
                for f in (
                    "app_id",
                    "owner_open_id",
                )
            )
        ):
            self.store.bots.assert_safe_change(self.bot_id)
        return value

    def configure(self, value):
        value = self.prepare_config(value)
        self.store.db.execute("SAVEPOINT configure_feishu")
        try:
            self.state.save_settings(self.scope_name, value)
            self.store.db.execute(
                "UPDATE bots SET enabled=? WHERE id=?", (int(value["enabled"]), self.bot_id)
            )
            self.store.db.execute("RELEASE configure_feishu")
        except Exception:
            self.store.db.execute("ROLLBACK TO configure_feishu")
            self.store.db.execute("RELEASE configure_feishu")
            raise
        self.token, self.token_until = "", 0
        return self.status()

    async def validate_credentials(self, value):
        candidate = self.prepare_config(value)
        if not all(
            candidate.get(k)
            for k in ("app_id", "app_secret", "owner_open_id", "verification_token", "encrypt_key")
        ):
            raise BridgeError(422, "incomplete_feishu_configuration")
        try:
            # Never reuse the old token to validate changed credentials. Do not persist first.
            await self.fetch_access_token(candidate)
        except Rejected as exc:
            detail = {"code": "feishu_credentials_rejected"}
            if exc.code.isdigit():
                detail["platform_code"] = int(exc.code)
            raise HTTPException(422, detail) from None
        except httpx.HTTPError:
            raise BridgeError(503, "feishu_credentials_unavailable") from None
        except (ValueError, TypeError, AttributeError):
            raise BridgeError(502, "feishu_credentials_response_invalid") from None

    def ready(self):
        config = self.config()
        if not config.get("enabled") or not self.store.bots.get(self.bot_id)["enabled"]:
            raise BridgeError(409, "feishu_not_enabled")
        return config

    def status(self):
        config = self.config()
        configured = self.store.bots.configured(self.bot_id)
        return dict(
            enabled=bool(config.get("enabled") and self.store.bots.get(self.bot_id)["enabled"]),
            configured=all(
                config.get(k)
                for k in (
                    "app_id",
                    "app_secret",
                    "owner_open_id",
                    "verification_token",
                    "encrypt_key",
                )
            ),
            app_id=config.get("app_id", ""),
            owner_open_id=config.get("owner_open_id", ""),
            credentials_saved=bool(config.get("app_secret")),
            callback_security_saved=bool(
                config.get("verification_token") and config.get("encrypt_key")
            ),
            callback_url=(chat_url() or "").split("/chat/")[0]
            + "/channels/feishu/"
            + self.bot_id
            + "/callback"
            if chat_url()
            else None,
            bot_id=self.bot_id,
            last_event_at=self.store.get(self.scope_name + ":last_event_at"),
            connection_status="pending_configuration"
            if not configured
            else "configured"
            if config.get("enabled") and self.store.bots.get(self.bot_id)["enabled"]
            else "disabled",
            capabilities=[
                "message",
                "notification",
                "reply",
                "single",
                "multiple",
                "confirm",
                "input",
                "form",
            ],
        )

    def digest(self, config, key, identity, cid):
        return self.state.digest(
            self.scope_name,
            [config["app_id"], config["owner_open_id"]],
            key,
            identity.id if identity else None,
            cid,
        )

    def public_receipt(self, row, duplicate=False):
        message = self.store.db.execute(
            "SELECT id,conversation_id FROM chat_messages WHERE outgoing_key=?", (row["key"],)
        ).fetchone()
        result = dict(
            channel="feishu",
            bot_id=self.bot_id,
            status="unconfirmed_do_not_retry" if row["status"] == "attempting" else row["status"],
            duplicate=duplicate,
            attempted_at=row["attempted_at"],
            error_code=row["error_code"],
            phone_delivery="unconfirmed",
            diagnostics=self.state.decrypt(row["encrypted"]),
            message_id=message["id"] if message else None,
            conversation_url=chat_url(message["conversation_id"], message["id"])
            if message
            else None,
        )
        task = self.store.db.execute(
            "SELECT * FROM task_cards WHERE outgoing_key=?", (row["key"],)
        ).fetchone()
        if task:
            result["task"] = self.store.portal.tasks.public(task)
        return result

    def delivery(self, key, caller, cid):
        config = self.config()
        if not config:
            return {"status": "not_found"}
        row = self.state.receipt(self.digest(config, key, caller, cid))
        return self.public_receipt(row) if row else {"status": "not_found"}

    def client(self):
        if self.http is None:
            self.http = httpx.AsyncClient(
                timeout=20, trust_env=False, follow_redirects=False, transport=self.transport
            )
        return self.http

    async def access_token(self, config):
        if self.token_until > time.time():
            return self.token
        self.token, self.token_until = await self.fetch_access_token(config)
        return self.token

    async def fetch_access_token(self, config):
        response = await self.client().post(
            BASE + "/auth/v3/tenant_access_token/internal",
            json=dict(app_id=config["app_id"], app_secret=config["app_secret"]),
        )
        response.raise_for_status()
        value = response.json()
        if type(value.get("code")) is not int:
            raise ValueError("invalid_auth_response")
        if value["code"] != 0:
            raise Rejected(value["code"])
        token, expires = value.get("tenant_access_token"), value.get("expire")
        if not isinstance(token, str) or not token or type(expires) is not int or expires < 120:
            raise ValueError("invalid_auth_response")
        return token, time.time() + min(expires, 7200) - 60

    async def send(
        self,
        text,
        dedup_key,
        caller,
        *,
        kind="message",
        dry_run=False,
        identity=None,
        conversation_id=None,
        task_card=None,
        retry_preparation=False,
        expected_digest=None,
    ):
        if not text.strip() or len(text) > 20000 or not dedup_key.strip() or len(dedup_key) > 200:
            raise BridgeError(422, "Invalid text or dedup_key")
        if task_card and (not identity or not conversation_id):
            raise BridgeError(422, "Task cards require a client identity and conversation")
        async with self.lock:
            config = self.ready()
            cid, label = conversation_id, "[" + caller + "]"
            if identity:
                identity = self.store.clients.revalidate(identity)
                self.store.bots.select(identity, self.bot_id)
                if not cid:
                    chats = self.store.conversations.rows(identity.id)
                    if len(chats) > 1:
                        raise BridgeError(409, "conversation_required")
                    cid = chats[0]["id"] if chats else None
                if cid:
                    label = self.store.conversations.label(identity.id, cid)
            elif cid:
                raise BridgeError(401, "client_identity_required")
            digest = self.digest(config, dedup_key, identity, conversation_id)
            if expected_digest and digest != expected_digest:
                raise BridgeError(409, "delivery_destination_changed")
            canonical = (
                json.dumps({"text": text, "task": task_card}, ensure_ascii=False, sort_keys=True)
                if task_card
                else text
            )
            fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
            previous = self.state.receipt(digest)
            if previous:
                if previous["message_hash"] != fingerprint:
                    raise BridgeError(409, "dedup_key already belongs to different content")
                evidence = self.state.decrypt(previous["encrypted"])
                if not retry_preparation:
                    return self.public_receipt(previous, True)
                if (
                    previous["status"] != "not_sent"
                    or evidence.get("platform_request_started") is not False
                    or evidence.get("phase") != "preparation"
                ):
                    raise BridgeError(409, "delivery_retry_unsafe")
                if not self.store.delivery_journal.request(digest):
                    raise BridgeError(409, "delivery_retry_history_incomplete")
            elif retry_preparation:
                raise BridgeError(409, "delivery_retry_history_incomplete")
            if dry_run:
                return dict(
                    channel="feishu", status="dry_run_ready", sent_now=False, network_checked=False
                )
            now, message_id, task_id = time.time(), None, None
            db = self.store.db
            db.execute("BEGIN IMMEDIATE")
            try:
                if previous:
                    db.execute(
                        "UPDATE channel_outgoing SET status='attempting',attempted_at=?,finished_at=NULL,error_code=NULL WHERE key=?",
                        (now, digest),
                    )
                    message = db.execute(
                        "SELECT id FROM chat_messages WHERE outgoing_key=?", (digest,)
                    ).fetchone()
                    message_id = message[0] if message else None
                    task = db.execute(
                        "SELECT id FROM task_cards WHERE outgoing_key=?", (digest,)
                    ).fetchone()
                    task_id = task[0] if task else None
                    db.execute(
                        "UPDATE chat_messages SET status='attempting' WHERE outgoing_key=?",
                        (digest,),
                    )
                else:
                    db.execute(
                        "INSERT INTO channel_outgoing(key,channel,conversation_id,message_hash,status,attempted_at) "
                        "VALUES (?,?,?,?,'attempting',?)",
                        (digest, self.scope_name, cid, fingerprint, now),
                    )
                if cid and not previous:
                    task_id = (
                        self.store.portal.tasks.create(cid, digest, task_card, now)
                        if task_card
                        else None
                    )
                    message_id = self.store.portal.add(
                        cid,
                        "assistant",
                        "feishu",
                        text,
                        "attempting",
                        outgoing_key=digest,
                        at=now,
                        task_id=task_id,
                        bot_id=self.bot_id,
                    )
                if identity:
                    self.store.delivery_journal.begin(
                        digest,
                        identity.id,
                        self.bot_id,
                        cid,
                        dict(
                            text=text,
                            dedup_key=dedup_key,
                            kind=kind,
                            conversation_id=conversation_id,
                            task_card=task_card,
                        ),
                    )
                db.commit()
            except Exception:
                db.rollback()
                raise
            diagnostics, status, error, provider_hash = {}, "unconfirmed_do_not_retry", None, None
            diagnostics.update(phase="preparation", platform_request_started=False)
            started = time.monotonic()
            try:
                projected = card(
                    text,
                    label,
                    chat_url(cid, message_id),
                    self.store.portal.tasks.get(cid, task_id) if task_id else None,
                )
                token = await self.access_token(config)
                payload = dict(
                    receive_id=config["owner_open_id"],
                    msg_type="interactive",
                    content=json.dumps(projected, ensure_ascii=False),
                    uuid=digest[:32],
                )
                if len(payload["content"].encode()) > 28000:
                    raise Rejected("card_content_too_large")
                diagnostics.update(phase="platform_send", platform_request_started=True)
                response = await self.client().post(
                    BASE + "/im/v1/messages",
                    params={"receive_id_type": "open_id"},
                    headers={"Authorization": "Bearer " + token},
                    json=payload,
                )
                diagnostics["http_status"] = response.status_code
                response.raise_for_status()
                value = response.json()
                if type(value.get("code")) is not int:
                    raise ValueError("invalid_response")
                if value["code"] != 0:
                    raise Rejected(value["code"])
                provider_id = value.get("data", {}).get("message_id")
                if not isinstance(provider_id, str) or not provider_id:
                    raise ValueError("missing_message_id")
                provider_hash = hashlib.sha256(provider_id.encode()).hexdigest()
                diagnostics["provider_message_id"] = provider_id
                status = "api_accepted"
            except Rejected as exc:
                status, error = "api_rejected", exc.code
            except Exception as exc:
                error = type(exc).__name__
            if not diagnostics["platform_request_started"] and status != "api_accepted":
                status = "not_sent"
            diagnostics["duration_ms"] = round((time.monotonic() - started) * 1000)
            db.execute("BEGIN IMMEDIATE")
            try:
                chat = (
                    db.execute("SELECT deleted FROM conversations WHERE id=?", (cid,)).fetchone()
                    if cid
                    else None
                )
                if chat and chat["deleted"]:
                    provider_hash, diagnostics = None, {}
                db.execute(
                    "UPDATE channel_outgoing SET status=?,finished_at=?,error_code=?,provider_hash=?,encrypted=? WHERE key=?",
                    (
                        status,
                        time.time(),
                        error,
                        provider_hash,
                        self.state.encrypt(diagnostics),
                        digest,
                    ),
                )
                db.execute(
                    "UPDATE chat_messages SET status=? WHERE outgoing_key=?", (status, digest)
                )
                self.store.delivery_journal.finish(digest, status, error, diagnostics)
                db.commit()
            except Exception:
                db.rollback()
                raise
            return self.public_receipt(self.state.receipt(digest))

    async def project_task(self, cid, task_id):
        """Project a committed answer; never roll back the canonical decision."""
        state_key = "task_projection:" + task_id
        async with self.lock:
            row = self.store.portal.tasks.row(cid, task_id)
            parent = self.state.receipt(row["outgoing_key"])
            data = self.state.decrypt(parent["encrypted"]) if parent else {}
            provider = data.get("provider_message_id") if data else None
            if not provider:
                result = {"status": "unavailable", "error": "projection_missing_delivery"}
                self.store.set(state_key, result)
                return result
            version = row["updated_at"]
            chat = self.store.portal.owner_chat(cid)
            projected = card(
                "",
                "[" + chat["caller"] + "-" + chat["name"] + "]",
                chat_url(cid),
                self.store.portal.tasks.get(cid, task_id),
            )
            self.store.set(state_key, {"status": "pending", "at": time.time()})
            try:
                from urllib.parse import quote

                config = self.ready()
                token = await self.access_token(config)
                response = await self.client().patch(
                    BASE + "/im/v1/messages/" + quote(provider, safe=""),
                    headers={"Authorization": "Bearer " + token},
                    json={"content": json.dumps(projected, ensure_ascii=False)},
                )
                response.raise_for_status()
                value = response.json()
                if type(value.get("code")) is not int or value["code"] != 0:
                    raise ValueError("projection_rejected")
                current = self.store.db.execute(
                    "SELECT updated_at FROM task_cards WHERE id=?", (task_id,)
                ).fetchone()
                result = {
                    "status": "synced" if current and current[0] == version else "pending",
                    "at": time.time(),
                }
            except Exception as exc:
                # Only fixed diagnostics, never upstream text, tokens, or message content.
                result = {"status": "failed", "error": type(exc).__name__, "at": time.time()}
            self.store.set(state_key, result)
            return result

    def command_text(self, command):
        if command == "/web":
            code = self.store.portal.issue_code()
            return (
                "## 打开对话页\n\n登录码：`"
                + code
                + "`\n\n请点击下方入口，输入登录码。仅本人可访问。"
            )
        if command == "/list":
            chats = self.store.conversations.list()
            return "## 当前会话\n\n" + (
                "\n".join("- " + chat["reply_tag"] for chat in chats)
                if chats
                else "暂无会话，请先在 Admin 创建客户端并登记聊天。"
            )
        if command == "/status":
            return (
                "## 飞书通知桥\n\n连接配置：已启用\n\n最近接收："
                + format_time(self.store.get(self.scope_name + ":last_event_at"))
                + "\n\n客户端列表：`/list`"
            )
        return "## 通知桥使用说明\n\n- `/list` 查看会话\n- `/status` 查看通道状态\n- `/web` 获取对话页登录码\n\n回复时使用 `[客户端-会话] 内容`，或引用该会话的通知回复。任务卡片可直接在飞书中提交。客户端密钥在 Admin 创建。"

    async def flush_commands(self):
        for _ in range(20):
            row = self.store.db.execute(
                "SELECT * FROM channel_commands WHERE channel=? AND status='pending' ORDER BY created_at LIMIT 1",
                (self.scope_name,),
            ).fetchone()
            if not row:
                return
            if time.time() - row["created_at"] > 600:
                status = "expired"
            else:
                try:
                    result = await self.send(
                        self.state.decrypt(row["encrypted"])["text"],
                        "feishu-command-" + row["id"],
                        "通知桥",
                    )
                    status = result["status"]
                except Exception:
                    # A command never retries under a different event key.
                    status = "unconfirmed_do_not_retry"
            self.store.db.execute(
                "UPDATE channel_commands SET status=?,encrypted=NULL WHERE id=?",
                (status, row["id"]),
            )

    async def sync_task(self, cid, tid):
        # Keep the existing caller API's result contract on the shared projector.
        result = await self.project_task(cid, tid)
        return {
            "synced": "api_updated",
            "unavailable": "unconfirmed_do_not_retry",
            "pending": "unconfirmed_do_not_retry",
            "failed": "unconfirmed_do_not_retry",
        }[result["status"]]

    async def close(self):
        if self.http:
            await self.http.aclose()
