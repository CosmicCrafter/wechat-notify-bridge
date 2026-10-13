"""Admin-only onboarding exports; existing credentials and grants are never rotated."""

import hashlib
import hmac
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from wechat_bridge.config import public_base, oauth_base
from wechat_bridge.services.onboarding import package, template_files


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["configured", "template", "rules"] = "configured"
    transport: Literal["local", "remote"] = "remote"
    target: Literal["codex", "chatgpt", "generic"] = "codex"
    credential_mode: Literal["existing", "new"] = "existing"
    client_id: str = Field(default="", max_length=64)
    client_name: str = Field(default="", max_length=32)
    bot_id: str = Field(default="", max_length=64)
    api_key: SecretStr = Field(default=SecretStr(""), max_length=256)
    private_ack: bool = False


def mount_onboarding(app, authorize_admin):
    @app.get(
        "/admin/api/onboarding", dependencies=[Depends(authorize_admin)], include_in_schema=False
    )
    def metadata():
        base = public_base()
        oauth = oauth_base()
        return {
            "base_url": base,
            "mcp_url": oauth + "/mcp" if oauth else "",
            "remote_available": urlsplit(oauth).scheme == "https",
        }

    @app.post(
        "/admin/api/onboarding/package",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def export(body: ExportRequest):
        base, oauth = public_base(), oauth_base()
        if body.kind != "rules":
            if not base:
                raise HTTPException(409, "public_base_not_configured")
            if body.target == "chatgpt" and body.transport != "remote":
                raise HTTPException(422, "chatgpt_requires_remote")
            if body.transport == "remote" and urlsplit(oauth).scheme != "https":
                raise HTTPException(422, "remote_requires_https")
        if body.kind == "configured" and body.transport == "local" and not body.private_ack:
            raise HTTPException(422, "private_package_confirmation_required")
        try:
            files = template_files()
        except (OSError, ValueError):
            raise HTTPException(503, "onboarding_template_unavailable") from None
        store = app.state.bridge.store
        async with app.state.bridge.lock:
            store.db.execute("BEGIN IMMEDIATE")
            try:
                client, bot, key = None, None, None
                if body.kind == "configured":
                    bot = store.bots.get(body.bot_id)
                    if not bot["enabled"]:
                        raise HTTPException(409, "bot_disabled")
                    if body.credential_mode == "new":
                        client, issued = store.clients.create(body.client_name)
                        store.bots.set_grants(client["id"], [bot["id"]], bot["id"])
                        key = issued if body.transport == "local" else None
                    else:
                        row = store.clients.get(body.client_id)
                        if not row["enabled"]:
                            raise HTTPException(409, "client_disabled")
                        if not store.bots.allowed(body.client_id, bot["id"]):
                            raise HTTPException(403, "bot_access_denied")
                        client = store.clients.public(row)
                        if body.transport == "local":
                            key = body.api_key.get_secret_value()
                            if not key or not hmac.compare_digest(
                                hashlib.sha256(key.encode()).hexdigest(), row["key_hash"]
                            ):
                                raise HTTPException(422, "client_key_mismatch")
                blob = package(
                    files,
                    kind=body.kind,
                    transport=body.transport,
                    target=body.target,
                    base_url=base,
                    mcp_url=oauth + "/mcp" if oauth else "",
                    client=client,
                    bot=bot,
                    key=key,
                )
                store.db.commit()
            except Exception:
                store.db.rollback()
                raise
        return Response(
            blob,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="notify-bridge-'
                + body.kind
                + "-"
                + body.transport
                + '.zip"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
