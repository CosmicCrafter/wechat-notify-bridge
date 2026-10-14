"""Owner controls and acknowledgement from a scoped external executor."""

from typing import Literal
import time
from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field


class Mute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    muted: bool


class Stop(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{16,80}$")


class MonitorReport(Stop):
    status: Literal["running", "stopped"]
    stop_id: str | None = Field(default=None, max_length=80)
    claim_id: str | None = Field(default=None, max_length=80)
    generation: int | None = Field(default=None, ge=1)


def mount_lifecycle(app, authorize, authorize_admin):
    def store():
        return app.state.bridge.store

    @app.post(
        "/admin/api/conversations/{cid}/subscriptions/{sid}/cancel",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def cancel_subscription(cid: str, sid: str):
        from wechat_bridge.storage.client_registry import ClientError

        store().portal.owner_chat(cid)
        if not app.state.events:
            raise ClientError("subscription_not_found", 404)
        async with app.state.events.lock:
            row = (
                store()
                .db.execute(
                    "SELECT id FROM mcp_event_subscriptions WHERE id=? AND conversation=?",
                    (sid, cid),
                )
                .fetchone()
            )
            if not row:
                raise ClientError("subscription_not_found", 404)
            store().db.execute(
                "UPDATE mcp_event_subscriptions SET status='cancelled' WHERE id=?", (sid,)
            )
            store().receivers.audit(cid, None, "subscription_cancelled", "admin")
        return {"cancelled": True}

    @app.get("/api/conversations/{conversation_id}/lifecycle")
    async def status(conversation_id: str, caller=Depends(authorize)):
        store().conversations.get(caller.id, conversation_id)
        return store().lifecycle.public(conversation_id)

    @app.post("/api/conversations/{conversation_id}/monitor")
    async def monitor(conversation_id: str, body: MonitorReport, caller=Depends(authorize)):
        async with app.state.bridge.lock:
            return store().lifecycle.report(
                caller,
                conversation_id,
                body.request_id,
                body.status,
                body.stop_id,
                body.claim_id,
                body.generation,
            )

    @app.post(
        "/admin/api/conversations/{cid}/mute",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def mute(cid: str, body: Mute):
        async with app.state.bridge.lock:
            return store().lifecycle.mute(cid, body.muted)

    @app.post(
        "/admin/api/conversations/{cid}/stop",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def stop(cid: str, body: Stop):
        async with app.state.bridge.lock:
            return store().lifecycle.stop(cid, body.request_id)

    @app.get(
        "/admin/api/conversations/{cid}/subscriptions",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def subscriptions(cid: str):
        store().portal.owner_chat(cid)
        rows = (
            store()
            .db.execute(
                "SELECT id,cursor,expires,status,attempts,next_attempt,verified_at,last_delivery_at,last_http_status FROM mcp_event_subscriptions WHERE conversation=? ORDER BY expires DESC",
                (cid,),
            )
            .fetchall()
            if app.state.events
            else []
        )
        return {
            "subscriptions": [
                dict(row, state="expired" if row["expires"] <= time.time() else row["status"])
                for row in rows
            ],
            "recovery": "persistent_inbox",
            "webhook_receipt_is_execution": False,
        }
