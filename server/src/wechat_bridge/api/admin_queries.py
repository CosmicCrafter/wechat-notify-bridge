"""Authenticated administrator read APIs; browsing never changes mobile reads."""

from fastapi import Depends, Query, HTTPException
from wechat_bridge.services.admin_queries import AdminQueries


def mount_admin_queries(app, authorize_admin):
    def views():
        return AdminQueries(app.state.bridge.store)

    @app.get(
        "/admin/api/overview", dependencies=[Depends(authorize_admin)], include_in_schema=False
    )
    async def overview():
        return views().overview()

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
