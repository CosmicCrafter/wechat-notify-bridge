"""Administrator auth endpoints; no password or session credential is logged."""

import asyncio
import hashlib
import hmac
from urllib.parse import urlsplit
from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from wechat_bridge.config import public_base
from wechat_bridge.storage.admin_accounts import (
    ADMIN_COOKIE,
    SESSION_TTL,
    password_hash,
    password_matches,
    username,
)
from wechat_bridge.storage.client_registry import ClientError


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=32)
    password: SecretStr = Field(min_length=1, max_length=128)


class ChangePassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old_password: SecretStr = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=15, max_length=128)


class ChangeUsername(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old_password: SecretStr = Field(min_length=1, max_length=128)
    username: str = Field(min_length=3, max_length=32)


def cookie_path():
    return urlsplit(public_base()).path.rstrip("/") + "/admin/"


def same_origin(request):
    p = urlsplit(public_base() or str(request.base_url))
    expected = p.scheme + "://" + p.netloc
    if request.headers.get("Origin") != expected or request.headers.get("X-Admin-Request") != "1":
        raise HTTPException(403, "admin_same_origin_required")


async def verify_admin_password(accounts, value):
    row = accounts.account()
    bucket = "current-password:" + str(row["version"] if row else 0)
    accounts.limit(bucket)
    if not row or not await asyncio.to_thread(password_matches, value, row["password_hash"]):
        accounts.failure(bucket)
        raise ClientError("invalid_admin_credentials", 401)
    if accounts.account()["version"] != row["version"]:
        raise ClientError("admin_state_changed", 409)
    accounts.db.execute("DELETE FROM admin_limits WHERE bucket=?", (bucket,))
    return row["version"]


def mount_admin_auth(app, authorize_admin):
    lock = asyncio.Lock()

    def accounts():
        return app.state.admin_accounts

    def bucket(request):
        return hashlib.sha256(
            ("login:" + str(request.client.host if request.client else "unknown")).encode()
        ).hexdigest()

    async def verify_old(value):
        return await verify_admin_password(accounts(), value)

    @app.get("/admin/api/auth/status", include_in_schema=False)
    async def status(request: Request):
        a = accounts()
        s = a.session(request.cookies.get(ADMIN_COOKIE, ""))
        result = {"configured": bool(a.account()), "authenticated": bool(s)}
        if s:
            result.update(a.metadata(), csrf=s["csrf"])
        return result

    @app.post("/admin/api/auth/login", include_in_schema=False)
    async def login(body: Login, request: Request, response: Response):
        same_origin(request)
        async with lock:
            a = accounts()
            b = bucket(request)
            a.limit(b)
            row = a.account()
            ok = await asyncio.to_thread(
                password_matches,
                body.password.get_secret_value(),
                row["password_hash"] if row else a.dummy_hash,
            )
            if (
                not row
                or not ok
                or not hmac.compare_digest(
                    body.username.casefold().encode(), row["username"].encode()
                )
            ):
                a.failure(b)
                raise ClientError("invalid_admin_credentials", 401)
            a.db.execute("DELETE FROM admin_limits WHERE bucket=?", (b,))
            token, csrf = a.issue(row["version"])
            a.audit("login")
        response.set_cookie(
            ADMIN_COOKIE,
            token,
            path=cookie_path(),
            max_age=SESSION_TTL,
            httponly=True,
            secure=urlsplit(public_base() or str(request.base_url)).scheme == "https",
            samesite="strict",
        )
        return dict(authenticated=True, csrf=csrf, **a.metadata())

    @app.post(
        "/admin/api/auth/logout", dependencies=[Depends(authorize_admin)], include_in_schema=False
    )
    async def logout(request: Request, response: Response):
        accounts().revoke(request.cookies.get(ADMIN_COOKIE, ""))
        response.delete_cookie(ADMIN_COOKIE, path=cookie_path())
        return {"authenticated": False}

    @app.get("/admin/api/account", dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def account():
        return accounts().metadata()

    @app.post(
        "/admin/api/account/password",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def change_password(body: ChangePassword, response: Response):
        async with lock:
            version = await verify_old(body.old_password.get_secret_value())
            encoded = await asyncio.to_thread(password_hash, body.password.get_secret_value())
            result = accounts().change(encoded=encoded, expected_version=version)
        response.delete_cookie(ADMIN_COOKIE, path=cookie_path())
        return dict(result, reauthentication_required=True)

    @app.post(
        "/admin/api/account/username",
        dependencies=[Depends(authorize_admin)],
        include_in_schema=False,
    )
    async def change_username(body: ChangeUsername, response: Response):
        async with lock:
            version = await verify_old(body.old_password.get_secret_value())
            result = accounts().change(name=username(body.username), expected_version=version)
        response.delete_cookie(ADMIN_COOKIE, path=cookie_path())
        return dict(result, reauthentication_required=True)
