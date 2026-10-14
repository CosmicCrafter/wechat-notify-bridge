"""Owner assignment of unassociated platform replies; never guess a conversation."""

import json
from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from wechat_bridge.storage.client_registry import ClientError


class Assignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str = Field(pattern=r"^[a-f0-9]{32}$")


def mount_inbound_routes(app, authorize_admin):
    @app.get(
        "/admin/api/unassigned", dependencies=[Depends(authorize_admin)], include_in_schema=False
    )
    async def unassigned(after: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)):
        store = app.state.bridge.store
        rows = store.db.execute(
            "SELECT * FROM inbox WHERE id>? AND kind='message' AND route_status!='direct' ORDER BY id LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        return {
            "messages": [
                {
                    "id": row["id"],
                    "received_at": row["received_at"],
                    "bot_id": row["bot_id"],
                    "reason": row["route_status"],
                    **json.loads(store.cipher.decrypt(row["encrypted"])),
                }
                for row in rows[:limit]
            ],
            "next_after": rows[limit - 1]["id"] if len(rows) > limit else None,
        }

    @app.post(
        "/admin/api/unassigned/{inbox_id}/assign",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def assign(inbox_id: int, body: Assignment):
        store = app.state.bridge.store
        async with app.state.bridge.lock:
            chat = store.portal.owner_chat(body.conversation_id, writable=True)
            cid = chat["id"]
            db = store.db
            client = db.execute(
                "SELECT client_id FROM conversations WHERE id=?", (cid,)
            ).fetchone()[0]
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT * FROM inbox WHERE id=? AND kind='message'", (inbox_id,)
                ).fetchone()
                if not row:
                    raise ClientError("inbox_message_not_found", 404)
                if row["bot_id"] and not store.bots.allowed(client, row["bot_id"]):
                    raise ClientError("bot_access_denied", 403)
                duplicate = row["route_status"] == "direct"
                if duplicate and row["conversation_id"] != cid:
                    raise ClientError("inbox_assignment_conflict", 409)
                if not duplicate:
                    content = json.loads(store.cipher.decrypt(row["encrypted"]))
                    db.execute(
                        "UPDATE inbox SET conversation_id=?,route_status='direct' WHERE id=?",
                        (cid, inbox_id),
                    )
                    store.portal.add(
                        cid,
                        "user",
                        content.get("source", "wechat"),
                        content.get("text", ""),
                        "pending",
                        inbox_id=inbox_id,
                        at=row["message_at"],
                        attachments=content.get("attachments", []),
                        bot_id=row["bot_id"],
                    )
                    store.receivers.audit(
                        cid, None, "unassigned_assigned:" + str(inbox_id), "admin"
                    )
                db.commit()
            except Exception:
                db.rollback()
                raise
            return {
                "assigned": True,
                "conversation_id": cid,
                "inbox_id": inbox_id,
                "duplicate": duplicate,
            }
