"""Authenticated client routes for messages, conversations and delivery receipts."""

import base64
from typing import Literal

from fastapi import Depends, HTTPException, Query

from wechat_bridge.core.errors import BridgeError
from wechat_bridge.storage.client_registry import ClientError

from wechat_bridge.api.schemas import (
    ConversationRegistration,
    ConversationState,
    Message,
    Notice,
    TaskCard,
    TaskUpdate,
    InboxClaim,
    InboxReport,
    InboxRenew,
)


def mount_client_api(app, authorize):
    @app.get("/api/status")
    async def status(caller=Depends(authorize)):
        chats = app.state.bridge.store.conversations.list(caller.id)
        if caller.receiver_hash:
            cid = app.state.bridge.store.receivers.resolve(caller)["conversation_id"]
            chats = [chat for chat in chats if chat["id"] == cid]
        hub = app.state.channels
        legacy_status = (
            app.state.bridge.store.status()
            if hub.registry.allowed(caller.id, "default")
            else {"status": "running"}
        )
        return dict(
            legacy_status,
            caller=caller.name,
            client_id=caller.id,
            conversation_count=len(chats),
            conversations=chats,
            channels=hub.status(caller),
            bots=hub.bots(caller),
            **hub.registry.grants(caller.id),
        )

    @app.get("/api/conversations")
    async def conversation_list(include_closed: bool = False, caller=Depends(authorize)):
        chats = app.state.bridge.store.conversations.list(caller.id, include_closed)
        if caller.receiver_hash:
            cid = app.state.bridge.store.receivers.resolve(caller)["conversation_id"]
            chats = [chat for chat in chats if chat["id"] == cid]
        return {
            "caller": caller.name,
            "conversations": chats,
            "active_count": sum(chat["active"] for chat in chats),
        }

    @app.post("/api/conversations")
    async def conversation_register(body: ConversationRegistration, caller=Depends(authorize)):
        bridge = app.state.bridge
        async with bridge.lock:
            bridge.store.clients.revalidate(caller)
            existing = bridge.store.db.execute(
                "SELECT id FROM conversations WHERE client_id=? AND conversation_key=?",
                (caller.id, body.conversation_key),
            ).fetchone()
            bridge.store.db.execute("BEGIN IMMEDIATE")
            try:
                result = bridge.store.conversations.register(
                    caller.id, body.conversation_key, body.name, body.receiver_mode
                )
                if not existing and body.receiver_mode == "protected":
                    result["receiver_setup"] = bridge.store.receivers.issue(
                        caller.id,
                        result["id"],
                        host_type=body.host_type,
                        source="client:" + caller.id,
                    )
                bridge.store.db.commit()
            except Exception:
                bridge.store.db.rollback()
                raise
            return result

    @app.post("/api/conversations/{conversation_id}/state")
    async def conversation_state(
        conversation_id: str, body: ConversationState, caller=Depends(authorize)
    ):
        bridge = app.state.bridge
        async with bridge.lock:
            bridge.store.clients.revalidate(caller)
            return bridge.store.conversations.set_active(caller.id, conversation_id, body.active)

    @app.get("/api/conversations/{conversation_id}/images/{image_id}")
    async def client_image(conversation_id: str, image_id: str, caller=Depends(authorize)):
        store = app.state.bridge.store
        store.conversations.get(caller.id, conversation_id)
        row = store.portal.images.get(conversation_id, image_id)
        return dict(
            store.portal.images.public(row),
            data=base64.b64encode(store.cipher.decrypt(row["encrypted"])).decode("ascii"),
        )

    @app.get("/api/conversations/{conversation_id}/history")
    async def history(
        conversation_id: str,
        before: int = Query(0, ge=0),
        after: int = Query(0, ge=0),
        around: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        caller=Depends(authorize),
    ):
        store = app.state.bridge.store
        store.conversations.get(caller.id, conversation_id)
        if sum(bool(x) for x in (before, after, around)) > 1:
            raise HTTPException(422, "one_cursor_only")
        return dict(
            store.portal.history(conversation_id, before, after, around, limit),
            content_is_untrusted=True,
        )

    @app.get("/api/deliveries")
    async def delivery(
        dedup_key: str = Query(min_length=1, max_length=200),
        conversation_id: str | None = Query(default=None, min_length=1, max_length=64),
        channel: Literal["wechat", "feishu"] | None = None,
        bot_id: str | None = Query(default=None, min_length=1, max_length=64),
        caller=Depends(authorize),
    ):
        store = app.state.bridge.store
        if caller.receiver_hash and not conversation_id:
            conversation_id = store.receivers.resolve(caller)["conversation_id"]
        if conversation_id:
            store.conversations.get(caller.id, conversation_id)
        return app.state.channels.delivery(channel, dedup_key, caller, conversation_id, bot_id)

    @app.get("/api/wake/events")
    async def wake_events(
        conversation_id: str = Query(min_length=1, max_length=64),
        after_id: int | None = Query(default=None, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
        caller=Depends(authorize),
    ):
        store = app.state.bridge.store
        store.conversations.get(caller.id, conversation_id, require_active=True)
        clause, ids = store.bots.scope(caller.id)
        # IDs only: observing arrival must not mark messages read or expose text.
        if after_id is None:
            cursor = store.db.execute(
                "SELECT COALESCE(MAX(id),0) FROM inbox WHERE conversation_id=? AND kind='message' AND route_status='direct' AND "
                + clause,
                (conversation_id, *ids),
            ).fetchone()[0]
            return {"events": [], "next_after_id": cursor}
        rows = store.db.execute(
            "SELECT id FROM inbox WHERE conversation_id=? AND kind='message' AND route_status='direct' AND id>? AND "
            + clause
            + " ORDER BY id LIMIT ?",
            (conversation_id, after_id, *ids, limit),
        ).fetchall()
        ids = [r["id"] for r in rows]
        return {"events": [{"id": id} for id in ids], "next_after_id": ids[-1] if ids else after_id}

    @app.get("/api/inbox")
    async def inbox(
        after_id: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
        conversation_id: str | None = Query(default=None, min_length=1, max_length=64),
        include_unaddressed: bool = False,
        caller=Depends(authorize),
    ):
        store = app.state.bridge.store
        if caller.receiver_hash and include_unaddressed:
            raise ClientError("receiver_unaddressed_denied", 403)
        if caller.receiver_hash and not conversation_id:
            conversation_id = store.receivers.resolve(caller)["conversation_id"]
        if conversation_id:
            store.conversations.get(caller.id, conversation_id)
        items = store.inbox(
            after_id,
            limit,
            conversation_id,
            include_unaddressed,
            bot_scope=store.bots.scope(caller.id),
        )
        return {
            "messages": [dict(item, processing=store.claims.public(item["id"])) for item in items],
            "next_after_id": items[-1]["id"] if items else after_id,
            "content_is_untrusted": True,
        }

    @app.post("/api/inbox/{inbox_id}/claim")
    async def claim(inbox_id: int, body: InboxClaim, caller=Depends(authorize)):
        async with app.state.bridge.lock:
            return app.state.bridge.store.claims.claim(
                caller, inbox_id, body.request_id, body.lease_seconds
            )

    @app.post("/api/inbox/{inbox_id}/report")
    async def report(inbox_id: int, body: InboxReport, caller=Depends(authorize)):
        async with app.state.bridge.lock:
            return app.state.bridge.store.claims.report(
                caller,
                inbox_id,
                body.claim_id,
                body.request_id,
                body.status,
                body.result,
                body.generation,
            )

    @app.post("/api/inbox/{inbox_id}/renew")
    async def renew(inbox_id: int, body: InboxRenew, caller=Depends(authorize)):
        async with app.state.bridge.lock:
            return app.state.bridge.store.claims.renew(
                caller, inbox_id, body.claim_id, body.generation, body.lease_seconds
            )

    async def send(
        text,
        dedup_key,
        caller,
        kind,
        dry_run,
        conversation_id,
        channel,
        bot_id,
        retry_preparation=False,
    ):
        try:
            return await app.state.channels.send(
                channel,
                bot_id,
                text=text,
                dedup_key=dedup_key,
                caller=caller.name,
                kind=kind,
                dry_run=dry_run,
                identity=caller,
                conversation_id=conversation_id,
                **({"retry_preparation": True} if retry_preparation else {}),
            )
        except ClientError:
            raise
        except BridgeError as exc:
            raise HTTPException(exc.status, exc.reason) from None
        except Exception:
            raise HTTPException(
                503,
                "Operation failed; delivery unconfirmed. Query the same dedup_key before retrying.",
            ) from None

    @app.post("/api/messages")
    async def message(body: Message, caller=Depends(authorize)):
        return await send(
            body.text,
            body.dedup_key,
            caller,
            "message",
            body.dry_run,
            body.conversation_id,
            body.channel,
            body.bot_id,
            body.retry_preparation,
        )

    @app.post("/api/notifications")
    async def notification(body: Notice, caller=Depends(authorize)):
        labels = {"info": "通知", "warning": "需要处理", "urgent": "紧急提醒"}
        text = f"## {labels[body.level]} · {body.task}\n\n**当前情况**\n\n{body.reason}\n\n**需要你处理**\n\n{body.need_user}"
        return await send(
            text,
            body.dedup_key,
            caller,
            "notification",
            body.dry_run,
            body.conversation_id,
            body.channel,
            body.bot_id,
        )

    @app.post("/api/task-cards")
    async def task_card(body: TaskCard, caller=Depends(authorize)):
        definition = body.definition()
        bridge = app.state.bridge
        return await app.state.channels.send(
            body.channel,
            body.bot_id,
            text=bridge.store.portal.tasks.summary(definition),
            dedup_key=body.dedup_key,
            caller=caller.name,
            kind="task_card",
            dry_run=body.dry_run,
            identity=caller,
            conversation_id=body.conversation_id,
            task_card=definition,
        )

    @app.get("/api/conversations/{conversation_id}/tasks/{task_id}")
    async def task_read(conversation_id: str, task_id: str, caller=Depends(authorize)):
        store = app.state.bridge.store
        store.conversations.get(caller.id, conversation_id)
        app.state.channels.task_bot(conversation_id, task_id, caller)
        return {"task": store.portal.tasks.get(conversation_id, task_id)}

    @app.post("/api/conversations/{conversation_id}/tasks/{task_id}/state")
    async def task_update(
        conversation_id: str, task_id: str, body: TaskUpdate, caller=Depends(authorize)
    ):
        bridge = app.state.bridge
        async with bridge.lock:
            bridge.store.clients.revalidate(caller)
            bridge.store.conversations.get(caller.id, conversation_id, require_active=True)
            app.state.channels.task_bot(conversation_id, task_id, caller)
            result = bridge.store.portal.tasks.update(conversation_id, task_id, body)
        card_delivery = await app.state.channels.sync_task(conversation_id, task_id)
        if card_delivery:
            result["card_delivery"] = card_delivery
        return result

    @app.get("/openapi.json")
    def schema(caller=Depends(authorize)):
        return app.openapi()
