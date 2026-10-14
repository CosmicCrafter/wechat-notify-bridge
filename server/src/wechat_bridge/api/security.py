"""HTTP authentication, redacted validation errors and browser response policy."""

import hmac
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from wechat_bridge.core.errors import BridgeError
from wechat_bridge.storage.client_registry import ClientError


def install_security(app):
    bearer = HTTPBearer(auto_error=False)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path.startswith(
            ("/admin/api/auth", "/admin/api/account", "/admin/api/recovery")
        ):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "invalid_admin_request"}, status_code=422)
        if request.url.path.startswith("/admin/api/onboarding"):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "invalid_onboarding_settings"}, status_code=422)
        if request.url.path.startswith("/api/receivers"):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "invalid_receiver_request"}, status_code=422)
        if request.url.path.startswith("/admin/api/proxy"):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "invalid_proxy_settings"}, status_code=422)
        if request.url.path.startswith(
            ("/admin/api/bots", "/admin/api/channels", "/admin/api/pairing")
        ):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "invalid_bot_settings"}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    @app.middleware("http")
    async def protect_browser_responses(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; "
                "img-src 'self' blob:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            }
        )
        return response

    async def authorize(
        request: Request, auth: HTTPAuthorizationCredentials | None = Depends(bearer)
    ):
        if auth is None or auth.scheme.lower() != "bearer":
            raise HTTPException(401, "Bearer token required")
        if auth.credentials.startswith("wna_") and app.state.oauth:
            identity = await app.state.oauth.api_identity(auth.credentials)
        else:
            identity = app.state.bridge.store.clients.authenticate(auth.credentials)
        from wechat_bridge.api.receivers import receiver_identity

        return await receiver_identity(app, request, identity)

    async def authorize_admin(request: Request):
        from wechat_bridge.storage.admin_accounts import ADMIN_COOKIE
        from wechat_bridge.api.admin_auth import same_origin

        accounts = getattr(app.state, "admin_accounts", None)
        row = accounts.session(request.cookies.get(ADMIN_COOKIE, "")) if accounts else None
        if not row:
            if not accounts or not accounts.account():
                raise HTTPException(503, "admin_not_configured")
            raise HTTPException(401, "admin_login_required")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            same_origin(request)
            if not hmac.compare_digest(
                request.headers.get("X-Admin-CSRF", "").encode(), row["csrf"].encode()
            ):
                raise HTTPException(403, "admin_csrf_required")
        return {"source": "session"}

    @app.exception_handler(BridgeError)
    async def bridge_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": exc.reason}, status_code=exc.status)

    @app.exception_handler(ClientError)
    async def client_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": exc.code}, status_code=exc.status)

    return authorize, authorize_admin
