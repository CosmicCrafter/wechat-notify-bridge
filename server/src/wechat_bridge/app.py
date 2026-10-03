"""Authenticated HTTPS-facing API; run one worker behind the existing Nginx."""
from contextlib import asynccontextmanager, AsyncExitStack
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler

from wechat_bridge.services.bridge import Bridge
from wechat_bridge.wechat.protocol import BridgeError
from wechat_bridge.storage.database import Store
from wechat_bridge.wechat.pairing import Pairing
from wechat_bridge.storage.client_registry import ClientError
from wechat_bridge.api.portal import mount_portal
from wechat_bridge.mcp.server import mount_remote_mcp

from wechat_bridge.api.admin import mount_admin
from wechat_bridge.api.clients import mount_client_api
from wechat_bridge.api.proxy import mount_proxy
from wechat_bridge.services.proxy import ProxyManager
from wechat_bridge import __version__


def create_app(bridge=None, clients=None, run_workers=True, *, admin_hash=None, pairing=None):
    @asynccontextmanager
    async def lifespan(app):
        nonlocal bridge, clients, admin_hash, pairing
        owned = bridge is None
        if owned:
            secret_dir = Path(os.environ.get('WECHAT_SECRETS', '/run/secrets'))
            data_dir = Path(os.environ.get('WECHAT_DATA', '/data'))
            data_dir.mkdir(parents=True, exist_ok=True)
            store = Store(data_dir / 'wechat.sqlite3', (secret_dir / 'encryption.key').read_bytes().strip())
            if (secret_dir / 'bootstrap.enc').exists():
                store.bootstrap((secret_dir / 'bootstrap.enc').read_bytes())
            bridge = Bridge(store)
            clients = json.loads((secret_dir / 'clients.json').read_text())
            if (secret_dir / 'admin.json').exists():
                admin_hash = json.loads((secret_dir / 'admin.json').read_text())['key_sha256']
        pairing = pairing or Pairing(bridge, run_workers=run_workers)
        app.state.bridge = bridge
        bridge.store.clients.seed(clients or {})
        app.state.admin_hash = admin_hash
        app.state.pairing = pairing
        app.state.proxy = ProxyManager(bridge.store)
        if run_workers:
            app.state.proxy.start()
        if run_workers:
            await bridge.start()
        if app.state.oauth:
            app.state.oauth.initialize()
        event_task = None
        if app.state.events:
            app.state.events.initialize()
            if run_workers:
                event_task = asyncio.create_task(app.state.events.run())
        try:
            async with AsyncExitStack() as stack:
                if remote_mcp:
                    await stack.enter_async_context(remote_mcp.session_manager.run())
                yield
        finally:
            await app.state.proxy.close()
            if event_task:
                event_task.cancel()
                await asyncio.gather(event_task, return_exceptions=True)
            await pairing.close()
            if owned or run_workers:
                await bridge.close()
            if owned:
                bridge.store.close()

    app = FastAPI(title='Personal WeChat Notification API', version=__version__,
                  docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan,
                  servers=([{'url': os.environ['WECHAT_PUBLIC_BASE_URL']}]
                           if os.environ.get('WECHAT_PUBLIC_BASE_URL') else []))
    bearer = HTTPBearer(auto_error=False)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path.startswith('/admin/api/proxy'):
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail': 'invalid_proxy_settings'}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    @app.middleware('http')
    async def protect_browser_responses(request: Request, call_next):
        response = await call_next(request)
        response.headers.update({
            'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
            'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; "
                "img-src 'self' blob:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
        })
        return response

    async def authorize(auth: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if auth is None or auth.scheme.lower() != 'bearer':
            raise HTTPException(401, 'Bearer token required')
        if auth.credentials.startswith('wna_') and app.state.oauth:
            return await app.state.oauth.api_identity(auth.credentials)
        return app.state.bridge.store.clients.authenticate(auth.credentials)

    def authorize_admin(auth: HTTPAuthorizationCredentials | None = Depends(bearer)):
        expected = app.state.admin_hash
        if not expected:
            raise HTTPException(503, 'admin_not_configured')
        if (auth is None or auth.scheme.lower() != 'bearer'
                or not hmac.compare_digest(hashlib.sha256(auth.credentials.encode()).hexdigest(), expected)):
            raise HTTPException(401, 'Invalid administrator key')

    mount_portal(app, authorize_admin)

    @app.exception_handler(BridgeError)
    async def bridge_error(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': exc.reason}, status_code=exc.status)

    @app.exception_handler(ClientError)
    async def client_error(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': exc.code}, status_code=exc.status)

    mount_admin(app, authorize_admin)
    mount_proxy(app, authorize_admin)

    @app.get('/health')
    def health():
        return {'status': 'ok', 'version': __version__}

    mount_client_api(app, authorize)

    remote_mcp = mount_remote_mcp(app)
    return app


app = create_app()
