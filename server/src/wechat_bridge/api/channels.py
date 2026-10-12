"""Administrator channel configuration and authenticated Feishu callbacks."""

from fastapi import BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from wechat_bridge.channels.feishu.security import verify
from wechat_bridge.core.errors import BridgeError
from wechat_bridge.api.schemas import PairStart, PairSession, PairVerify
from fastapi.responses import Response, JSONResponse
import os
import logging
from typing import Literal
from wechat_bridge.storage.client_registry import ClientError


class FeishuSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    app_id: str = Field(default="", max_length=100, pattern=r"^(cli_[a-zA-Z0-9]+)?$")
    owner_open_id: str = Field(default="", max_length=100, pattern=r"^(ou_[a-zA-Z0-9_-]+)?$")
    app_secret: str = Field(default="", max_length=256)
    verification_token: str = Field(default="", max_length=256)
    encrypt_key: str = Field(default="", max_length=256)


class BotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    platform: Literal["wechat", "feishu"]


class BotUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    enabled: bool


class BotGrants(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bot_ids: list[str] = Field(max_length=32)
    default_bot_id: str | None = None


def mount_channels(app, authorize_admin):
    @app.get("/admin/api/bots", dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def bots():
        return {"bots": app.state.channels.bots()}

    @app.post("/admin/api/bots", dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def create(body: BotCreate):
        return app.state.channels.registry.create(body.name, body.platform)

    @app.post(
        "/admin/api/bots/{bot_id}", dependencies=[Depends(authorize_admin)], include_in_schema=False
    )
    async def update(bot_id: str, body: BotUpdate):
        result = app.state.channels.registry.update(bot_id, body.name, body.enabled)
        await app.state.channels.reconcile()
        return result

    @app.post(
        "/admin/api/bots/{bot_id}/delete",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def delete_bot(bot_id: str):
        return await app.state.channels.delete(bot_id)

    @app.get(
        "/admin/api/clients/{client_id}/bots",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def grants(client_id: str):
        return app.state.channels.registry.grants(client_id)

    @app.post(
        "/admin/api/clients/{client_id}/bots",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def save_grants(client_id: str, body: BotGrants):
        async with app.state.bridge.lock:
            return app.state.channels.registry.set_grants(
                client_id, body.bot_ids, body.default_bot_id
            )

    @app.get(
        "/admin/api/bots/{bot_id}/feishu",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def bot_feishu_status(bot_id: str):
        if app.state.channels.registry.get(bot_id)["platform"] != "feishu":
            raise ClientError("bot_platform_conflict", 422)
        adapter = app.state.channels.adapter(bot_id)
        config = adapter.config()
        result = adapter.status()
        for field in ("app_secret", "verification_token", "encrypt_key"):
            result[field] = config.get(field, "")
        result["default_owner_open_id"] = os.environ.get("FEISHU_DEFAULT_OWNER_OPEN_ID", "")
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.post(
        "/admin/api/bots/{bot_id}/feishu",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def bot_feishu_save(bot_id: str, body: FeishuSettings):
        if app.state.channels.registry.get(bot_id)["platform"] != "feishu":
            raise ClientError("bot_platform_conflict", 422)
        adapter = app.state.channels.adapter(bot_id)
        async with adapter.lock:
            return adapter.configure(body.model_dump())

    @app.get(
        "/admin/api/bots/{bot_id}/pairing",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def pair_status(bot_id: str):
        pair = app.state.channels.pairing(bot_id)
        return dict(pairing=pair.snapshot(), service=pair.bridge.store.status())

    @app.post(
        "/admin/api/bots/{bot_id}/pairing/start",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def pair_start(bot_id: str, body: PairStart):
        if not app.state.channels.registry.get(bot_id)["enabled"]:
            raise ClientError("bot_disabled")
        return await app.state.channels.pairing(bot_id).start(body.replace)

    @app.get(
        "/admin/api/bots/{bot_id}/pairing/qr",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def pair_qr(bot_id: str, session_id: str):
        pair = app.state.channels.pairing(bot_id)
        if pair.session_id != session_id or not pair.png:
            raise ClientError("qr_unavailable", 404)
        return Response(pair.png, media_type="image/png")

    @app.post(
        "/admin/api/bots/{bot_id}/pairing/verify",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def pair_verify(bot_id: str, body: PairVerify):
        return await app.state.channels.pairing(bot_id).verify(body.session_id, body.code)

    @app.post(
        "/admin/api/bots/{bot_id}/pairing/cancel",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def pair_cancel(bot_id: str, body: PairSession):
        return await app.state.channels.pairing(bot_id).cancel(body.session_id)

    @app.get(
        "/admin/api/channels/feishu",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def status():
        return app.state.channels.feishu.status()

    @app.post(
        "/admin/api/channels/feishu",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def configure(body: FeishuSettings):
        adapter = app.state.channels.feishu
        async with adapter.lock:
            return adapter.configure(body.model_dump())

    @app.post("/channels/feishu/{bot_id}/callback", include_in_schema=False)
    @app.post("/channels/feishu/callback", include_in_schema=False)
    async def callback(
        request: Request, background_tasks: BackgroundTasks, bot_id: str = "feishu-default"
    ):
        if app.state.channels.registry.get(bot_id)["platform"] != "feishu":
            raise ClientError("bot_platform_conflict", 422)
        adapter = app.state.channels.adapter(bot_id)
        config = adapter.ready()
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 65536:
                raise HTTPException(413, "callback_too_large")
        value = verify(bytes(raw), request.headers, config)
        if value.get("type") == "url_verification":
            challenge = value.get("challenge")
            if not isinstance(challenge, str) or len(challenge) > 1024:
                raise HTTPException(422, "invalid_challenge")
            return {"challenge": challenge}
        event_type = value["header"].get("event_type")
        event = value.get("event")
        if not isinstance(event, dict):
            raise HTTPException(422, "invalid_feishu_event")
        # No HTTP or AI work in callbacks: persist locally and let existing wake consumers continue.
        if event_type == "im.message.receive_v1":
            try:
                result = adapter.receive_message(event)
                background_tasks.add_task(adapter.flush_commands)
                if result.get("task_id"):
                    background_tasks.add_task(
                        adapter.sync_task, result["conversation_id"], result["task_id"]
                    )
                return result
            except (ValueError, TypeError, AttributeError):
                raise BridgeError(422, "invalid_feishu_message") from None
        if event_type == "card.action.trigger":
            logging.getLogger(__name__).info("feishu_card_callback verified")
            try:
                result = adapter.receive_card(event)
            except Exception as exc:
                logging.getLogger(__name__).error(
                    "feishu_card_callback failed exception_type=%s", type(exc).__name__
                )
                raise
            logging.getLogger(__name__).info("feishu_card_callback responded")
            return result
        return {"ignored": True}
