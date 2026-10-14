"""Authenticated administrator read APIs; browsing never changes mobile reads."""

from fastapi import Depends, Query, HTTPException
from wechat_bridge.services.admin_queries import AdminQueries
from wechat_bridge.core.errors import BridgeError
from wechat_bridge.storage.client_registry import Identity


def mount_admin_queries(app, authorize_admin):
    def views():
        return AdminQueries(app.state.bridge.store)

    @app.get(
        "/admin/api/overview", dependencies=[Depends(authorize_admin)], include_in_schema=False
    )
    async def overview():
        return views().overview()

    @app.post(
        "/admin/api/deliveries/{key}/retry-preparation",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def retry_preparation(key: str):
        store = app.state.bridge.store
        row = store.delivery_journal.request(key)
        if not row:
            raise BridgeError(409, "delivery_retry_history_incomplete")
        bot = store.bots.get(row["bot_id"])
        if bot["platform"] != "feishu":
            raise BridgeError(409, "delivery_retry_unsafe")
        client = store.clients.get(row["client_id"])
        identity = Identity(client["id"], client["name"], client["key_hash"], client["legacy_name"])
        store.bots.select(identity, bot["id"])
        return await app.state.channels.adapter(bot["id"]).send(
            **row["request"],
            caller=client["name"],
            identity=identity,
            retry_preparation=True,
            expected_digest=key,
        )

    @app.get(
        "/admin/api/conversations", dependencies=[Depends(authorize_admin)], include_in_schema=False
    )
    async def conversations(
        q: str = Query("", max_length=80),
        client_id: str | None = Query(None, max_length=64),
        archived: bool | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(30, ge=1, le=100),
    ):
        return views().conversations(
            q=q, client_id=client_id, archived=archived, offset=offset, limit=limit
        )

    @app.get(
        "/admin/api/conversations/{cid}/messages",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def history(
        cid: str,
        before: int = Query(0, ge=0),
        after: int = Query(0, ge=0),
        around: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
    ):
        if sum(bool(x) for x in (before, after, around)) > 1:
            raise HTTPException(422, "one_cursor_only")
        return views().history(cid, before=before, after=after, around=around, limit=limit)

    @app.get(
        "/admin/api/conversations/{cid}/message-states",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def message_states(cid: str, ids: str = Query(min_length=1, max_length=2200)):
        values = ids.split(",")
        if len(values) > 100 or any(
            not v.isascii() or not v.isdigit() or len(v) > 20 for v in values
        ):
            raise HTTPException(422, "invalid_message_ids")
        return views().message_states(cid, [int(v) for v in values])

    @app.get(
        "/admin/api/deliveries", dependencies=[Depends(authorize_admin)], include_in_schema=False
    )
    async def deliveries(
        client_id: str | None = Query(None, max_length=64),
        bot_id: str | None = Query(None, max_length=64),
        conversation_id: str | None = Query(None, max_length=64),
        status: str | None = Query(None, max_length=40),
        q: str = Query("", max_length=200),
        after: float = Query(0, ge=0),
        before: float = Query(0, ge=0),
        offset: int = Query(0, ge=0),
        limit: int = Query(30, ge=1, le=100),
    ):
        return views().deliveries(
            client_id=client_id,
            bot_id=bot_id,
            cid=conversation_id,
            status=status,
            q=q,
            after=after,
            before=before,
            offset=offset,
            limit=limit,
        )
