"""Scoped receiver transport and administrator-controlled pairing. No host identity claims."""

from dataclasses import replace
from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from typing import Literal
from wechat_bridge.storage.receivers import digest
from wechat_bridge.storage.client_registry import ClientError


async def receiver_identity(app, request, identity):
    store = app.state.bridge.store
    token = request.headers.get("X-Notify-Receiver")
    if token:
        if len(token) > 128 or not token.startswith("nrb_"):
            raise ClientError("receiver_access_denied", 403)
        identity = replace(identity, receiver_hash=digest(token))
    path = request.url.path
    if path == "/api/receivers/verify":
        store.receivers.resolve(identity, pending=True)
        return identity
    if path == "/api/receivers/exchange":
        if token:
            raise ClientError("receiver_scope_mismatch", 403)
        return identity
    bound = store.receivers.resolve(identity) if token else None
    cid = request.path_params.get("conversation_id") or request.query_params.get("conversation_id")
    if "inbox_id" in request.path_params:
        item = store.db.execute(
            "SELECT conversation_id FROM inbox WHERE id=?", (request.path_params["inbox_id"],)
        ).fetchone()
        cid = item[0] if item else None
    if request.method == "POST" and path in (
        "/api/messages",
        "/api/notifications",
        "/api/task-cards",
        "/api/conversations",
    ):
        try:
            body = await request.json()
        except ValueError:
            body = {}
        if isinstance(body, dict):
            cid = body.get("conversation_id")
            if path == "/api/conversations" and bound:
                if not isinstance(body.get("conversation_key"), str):
                    raise ClientError("invalid_receiver_conversation", 422)
                existing = store.db.execute(
                    "SELECT id FROM conversations WHERE client_id=? AND conversation_key=?",
                    (identity.id, body.get("conversation_key")),
                ).fetchone()
                if not existing or existing[0] != bound["conversation_id"]:
                    raise ClientError("receiver_scope_mismatch", 403)
    metadata = (
        path.endswith("/receiver") or path == "/api/conversations" and request.method == "GET"
    )
    if cid and not (metadata and not token):
        if not isinstance(cid, str):
            raise ClientError("invalid_receiver_conversation", 422)
        store.receivers.authorize(
            identity, cid, write=request.method not in ("GET", "HEAD", "OPTIONS")
        )
    if bound and cid and cid != bound["conversation_id"]:
        raise ClientError("receiver_scope_mismatch", 403)
    if bound and not cid and path in ("/api/messages", "/api/notifications", "/api/task-cards"):
        raise ClientError("receiver_conversation_required", 403)
    if bound and request.query_params.get("include_unaddressed", "false").lower() == "true":
        raise ClientError("receiver_unaddressed_denied", 403)
    return identity


class SecretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PairExchange(SecretRequest):
    pairing_code: SecretStr = Field(min_length=32, max_length=128)


class ReceiverProof(SecretRequest):
    challenge: SecretStr = Field(min_length=16, max_length=128)


class Pairing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["primary", "observer"] = "primary"
    host_type: Literal["unknown", "http", "codex", "claude", "chatgpt_work", "chatgpt"] = "unknown"
    label: str = Field(default="", max_length=80)
    replace: bool = False


def mount_receivers(app, authorize, authorize_admin):
    def store():
        return app.state.bridge.store

    @app.post("/api/receivers/exchange")
    async def exchange(body: PairExchange, caller=Depends(authorize)):
        async with app.state.bridge.lock:
            return store().receivers.exchange(caller, body.pairing_code.get_secret_value())

    @app.post("/api/receivers/verify")
    async def verify(body: ReceiverProof, caller=Depends(authorize)):
        async with app.state.bridge.lock:
            return store().receivers.verify(caller, body.challenge.get_secret_value())

    @app.get("/api/conversations/{conversation_id}/receiver")
    async def status(conversation_id: str, caller=Depends(authorize)):
        store().conversations.get(caller.id, conversation_id)
        return store().receivers.summary(conversation_id)

    @app.post(
        "/admin/api/conversations/{cid}/receiver/pair",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def pair(cid: str, body: Pairing):
        async with app.state.bridge.lock:
            row = store().portal.owner_chat(cid)
            client = (
                store()
                .db.execute("SELECT client_id FROM conversations WHERE id=?", (row["id"],))
                .fetchone()[0]
            )
            return store().receivers.issue(
                client,
                cid,
                role=body.role,
                host_type=body.host_type,
                label=body.label,
                pairing=True,
                replace=body.replace,
            )

    @app.post(
        "/admin/api/conversations/{cid}/receiver/{binding_id}/revoke",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def revoke(cid: str, binding_id: str):
        async with app.state.bridge.lock:
            store().portal.owner_chat(cid)
            return store().receivers.revoke(cid, binding_id)

    @app.get(
        "/admin/api/conversations/{cid}/receivers",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def bindings(cid: str):
        store().portal.owner_chat(cid)
        rows = (
            store()
            .db.execute(
                "SELECT id,role,status,host_type,label,created_at,verified_at,expires_at,revoked_at FROM receiver_bindings WHERE conversation_id=? ORDER BY created_at",
                (cid,),
            )
            .fetchall()
        )
        return {
            "receiver": store().receivers.summary(cid),
            "bindings": [dict(row) for row in rows],
            "audit": [
                dict(row)
                for row in store().db.execute(
                    "SELECT action,binding_id,source,created_at FROM receiver_audit WHERE conversation_id=? ORDER BY id DESC LIMIT 100",
                    (cid,),
                )
            ],
        }
