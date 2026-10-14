"""Admin conversation commands reuse the owner ledger and task/attachment services."""

import asyncio
from contextlib import asynccontextmanager
from fastapi import Depends, Request, Query, HTTPException, Response
from pydantic import Field
from typing import Literal
from wechat_bridge.api.portal import WebReply, RenameChat, ArchiveChat, PinChat
from wechat_bridge.api.schemas import TaskAnswer
from wechat_bridge.storage.images import normalize, MAX_UPLOAD


class NewConversation(WebReply):
    client_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    name: str = Field(pattern=r"^[a-zA-Z0-9_\-\u4e00-\u9fff]{1,20}$")
    receiver_mode: Literal["legacy", "protected"] = "legacy"


def mount_admin_conversations(app, authorize_admin):
    def portal():
        return app.state.bridge.store.portal

    @asynccontextmanager
    async def writes(events=False):
        manager = getattr(app.state, "events", None)
        if events and manager:
            async with manager.lock:
                async with app.state.bridge.lock:
                    yield
        else:
            async with app.state.bridge.lock:
                yield

    @app.post(
        "/admin/api/conversations", dependencies=[Depends(authorize_admin)], include_in_schema=False
    )
    async def create(body: NewConversation):
        if body.attachment_ids:
            raise HTTPException(422, "first_message_text_required")
        async with writes():
            return app.state.admin_conversations.create(
                body.client_id, body.name, body.text, body.request_id, body.receiver_mode
            )

    @app.post(
        "/admin/api/conversations/{cid}/messages",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def reply(cid: str, body: WebReply):
        async with writes():
            return app.state.admin_conversations.reply(
                cid, body.text, body.request_id, body.attachment_ids
            )

    @app.post(
        "/admin/api/conversations/{cid}/pin",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def pin(cid: str, body: PinChat):
        async with writes():
            return portal().pin(cid, body.pinned)

    @app.post(
        "/admin/api/conversations/{cid}/rename",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def rename(cid: str, body: RenameChat):
        async with writes():
            portal().owner_chat(cid)
            row = (
                portal()
                .db.execute("SELECT client_id FROM conversations WHERE id=?", (cid,))
                .fetchone()
            )
            return {"conversation": portal().store.conversations.rename(row[0], cid, body.name)}

    @app.post(
        "/admin/api/conversations/{cid}/archive",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def archive(cid: str, body: ArchiveChat):
        async with writes(events=True):
            if body.visibility_only:
                return portal().store.lifecycle.archive(cid, body.archived)
            portal().owner_chat(cid)
            row = (
                portal()
                .db.execute("SELECT client_id FROM conversations WHERE id=?", (cid,))
                .fetchone()
            )
            portal().store.conversations.set_active(row[0], cid, not body.archived)
            if body.archived and getattr(app.state, "events", None):
                portal().db.execute(
                    "UPDATE mcp_event_subscriptions SET status='revoked' WHERE conversation=?",
                    (cid,),
                )
            return portal().owner_chat(cid)

    @app.post(
        "/admin/api/conversations/{cid}/delete",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def delete(cid: str):
        async with writes(events=True):
            return portal().delete_chat(cid)

    @app.get("/admin/api/tasks", dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def pending_tasks(before: int = Query(0, ge=0), q: str = Query("", max_length=80)):
        return portal().pending_tasks(before, 30, q)

    @app.post(
        "/admin/api/conversations/{cid}/tasks/{tid}/answer",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def answer(cid: str, tid: str, body: TaskAnswer):
        async with writes():
            result = portal().tasks.answer(cid, tid, body, source="admin")
        result["projection"] = await app.state.channels.project_task_answer(cid, tid)
        return result

    @app.post(
        "/admin/api/conversations/{cid}/tasks/{tid}/projection",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def projection(cid: str, tid: str):
        portal().owner_chat(cid, writable=True)
        result = await app.state.channels.project_task_answer(cid, tid)
        return {"task": portal().tasks.get(cid, tid), "projection": result}

    @app.post(
        "/admin/api/conversations/{cid}/images",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def upload(cid: str, request: Request):
        portal().owner_chat(cid, writable=True)
        async with portal().image_slots:
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > MAX_UPLOAD:
                    raise HTTPException(413, "image_too_large")
            normalized = await asyncio.to_thread(normalize, bytes(raw))
            async with writes():
                return portal().images.save(cid, normalized)

    @app.get(
        "/admin/api/conversations/{cid}/images/{image_id}",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def image(cid: str, image_id: str):
        portal().owner_chat(cid)
        row = portal().images.get(cid, image_id)
        return Response(portal().store.cipher.decrypt(row["encrypted"]), media_type=row["mime"])
