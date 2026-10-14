"""Small deterministic notification policy and authoritative Bot grants."""

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_bot: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    urgent_bot: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    fallback_bot: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    urgent_enabled: bool = False
    interval_seconds: int = Field(default=60, ge=30, le=86400)


class Preference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bot_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")


def mount_notification_routes(app, authorize_admin):
    def routing():
        return app.state.channels.notifications

    @app.get(
        "/admin/api/clients/{client_id}/notification-policy",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def policy(client_id: str):
        app.state.bridge.store.clients.get(client_id)
        return {
            "policy": routing().policy(client_id),
            "bot_ids": app.state.bridge.store.bots.grants(client_id)["bot_ids"],
        }

    @app.post(
        "/admin/api/clients/{client_id}/notification-policy",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def save(client_id: str, body: Policy):
        async with app.state.bridge.lock:
            return routing().save_policy(client_id, body.model_dump())

    @app.get(
        "/admin/api/conversations/{cid}/notification-preference",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def preference(cid: str):
        app.state.bridge.store.portal.owner_chat(cid)
        owner = app.state.bridge.store.db.execute(
            "SELECT client_id FROM conversations WHERE id=?", (cid,)
        ).fetchone()[0]
        return {
            "bot_id": routing().preference(cid),
            "bot_ids": [
                bot
                for bot in app.state.bridge.store.bots.grants(owner)["bot_ids"]
                if bot != (routing().policy(owner) or {}).get("urgent_bot")
            ],
        }

    @app.post(
        "/admin/api/conversations/{cid}/notification-preference",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def save_preference(cid: str, body: Preference):
        async with app.state.bridge.lock:
            return routing().save_preference(cid, body.bot_id)

    @app.get(
        "/admin/api/notification-routes",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def records(client_id: str | None = None, conversation_id: str | None = None):
        return {"routes": routing().rows(client_id, conversation_id)}
