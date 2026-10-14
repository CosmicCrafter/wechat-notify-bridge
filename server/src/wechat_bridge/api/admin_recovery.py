"""Recovery binding and password reset, with uniform public request responses."""

import asyncio
from fastapi import Depends, Request, Response, BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from typing import Literal
from wechat_bridge.api.admin_auth import same_origin, cookie_path, verify_admin_password
from wechat_bridge.storage.admin_accounts import ADMIN_COOKIE, password_hash


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bot_id: str = Field(min_length=1, max_length=64)
    old_password: SecretStr = Field(min_length=1, max_length=128)


class Code(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: str = Field(min_length=16, max_length=64)
    code: SecretStr = Field(min_length=8, max_length=8)

    @field_validator("code")
    @classmethod
    def numeric(cls, value):
        raw = value.get_secret_value()
        if not raw.isascii() or not raw.isdigit():
            raise ValueError("Invalid code format")
        return value


class Recovery(Code):
    password: SecretStr = Field(min_length=15, max_length=128)


class CodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=32)
    platform: Literal["wechat", "feishu"]


class RemoveBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old_password: SecretStr = Field(min_length=1, max_length=128)
    enabled: bool


async def old_password(accounts, password):
    return await verify_admin_password(accounts, password)


def mount_admin_recovery(app, authorize_admin):
    def service():
        return app.state.admin_recovery

    @app.get(
        "/admin/api/account/recovery",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def bindings():
        return {"bindings": service().bindings()}

    @app.post(
        "/admin/api/account/recovery/bind",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def bind(body: Binding):
        async with service().lock:
            version = await old_password(service().accounts, body.old_password.get_secret_value())
            return await service().issue("binding", bot_id=body.bot_id, expected_version=version)

    @app.post(
        "/admin/api/account/recovery/verify",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def verify(body: Code):
        async with service().lock:
            return service().bind(body.challenge_id, body.code.get_secret_value())

    @app.post(
        "/admin/api/account/recovery/{bot_id}/remove",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def remove(bot_id: str, body: RemoveBinding):
        async with service().lock:
            await old_password(service().accounts, body.old_password.get_secret_value())
            return service().remove(bot_id)

    @app.post("/admin/api/recovery/request", include_in_schema=False)
    async def request_code(body: CodeRequest, request: Request, background_tasks: BackgroundTasks):
        same_origin(request)
        async with service().lock:
            return await service().issue(
                "recovery",
                username=body.username,
                platform=body.platform,
                background_tasks=background_tasks,
            )

    @app.post("/admin/api/recovery/complete", include_in_schema=False)
    async def recover(body: Recovery, request: Request, response: Response):
        same_origin(request)
        async with service().lock:
            row = service().check(body.challenge_id, body.code.get_secret_value(), "recovery")
            encoded = await asyncio.to_thread(password_hash, body.password.get_secret_value())
            service().accounts.change(
                encoded=encoded, source="recovery", expected_version=row["version"]
            )
        response.delete_cookie(ADMIN_COOKIE, path=cookie_path())
        return {"reauthentication_required": True}
