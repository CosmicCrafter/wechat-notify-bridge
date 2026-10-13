"""HTTP authentication, redacted validation errors and browser response policy."""

import hashlib
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
        if request.url.path.startswith("/admin/api/onboarding"):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "invalid_onboarding_settings"}, status_code=422)
        if request.url.path.startswith("/admin/api/proxy"):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "invalid_proxy_settings"}, status_code=422)
        if request.url.path.startswith(("/admin/api/bots", "/admin/api/channels")):
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

    async def authorize(auth: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if auth is None or auth.scheme.lower() != "bearer":
            raise HTTPException(401, "Bearer token required")
        if auth.credentials.startswith("wna_") and app.state.oauth:
            return await app.state.oauth.api_identity(auth.credentials)
        return app.state.bridge.store.clients.authenticate(auth.credentials)

    def authorize_admin(auth: HTTPAuthorizationCredentials | None = Depends(bearer)):
        expected = app.state.admin_hash
        if not expected:
            raise HTTPException(503, "admin_not_configured")
        if (
            auth is None
            or auth.scheme.lower() != "bearer"
            or not hmac.compare_digest(
                hashlib.sha256(auth.credentials.encode()).hexdigest(), expected
            )
        ):
            raise HTTPException(401, "Invalid administrator key")

    @app.exception_handler(BridgeError)
    async def bridge_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": exc.reason}, status_code=exc.status)

    @app.exception_handler(ClientError)
    async def client_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": exc.code}, status_code=exc.status)

    return authorize, authorize_admin
