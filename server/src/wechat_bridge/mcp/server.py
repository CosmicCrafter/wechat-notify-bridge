"""Streamable HTTP tools over the same authenticated API as the stdio adapter."""
from urllib.parse import urlsplit
import time

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.routes import create_auth_routes, build_metadata
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from wechat_bridge.mcp.oauth import Provider, SCOPE, mount_consent
from wechat_bridge.config import public_base
from wechat_bridge.mcp.tools import register_tools
from wechat_bridge.mcp.events import Events, EventGateway
from wechat_bridge.mcp.errors import request_json


def mount_remote_mcp(app):
    base = public_base()
    if not base:
        app.state.oauth = None
        app.state.events = None
        return None
    provider = Provider(app, base)
    app.state.oauth = provider
    app.state.events = Events(provider)
    registration = ClientRegistrationOptions(enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE])
    revocation = RevocationOptions(enabled=True)
    issuer = AnyHttpUrl(base)
    routes = create_auth_routes(provider, issuer, client_registration_options=registration, revocation_options=revocation)
    metadata = build_metadata(issuer, None, registration, revocation).model_dump(mode='json', exclude_none=True)
    # The SDK handles public DCR clients as well as client-secret clients.
    metadata['token_endpoint_auth_methods_supported'] = ['none', 'client_secret_post', 'client_secret_basic']
    metadata['revocation_endpoint_auth_methods_supported'] = metadata['token_endpoint_auth_methods_supported']

    @app.get('/.well-known/oauth-authorization-server', include_in_schema=False)
    async def discovery(): return JSONResponse(metadata)

    issuer_path = urlsplit(base).path.rstrip('/')
    if issuer_path:
        app.add_api_route('/.well-known/oauth-authorization-server'+issuer_path, discovery, include_in_schema=False)
    registration_attempts = {}
    for route in routes:
        if route.path == '/.well-known/oauth-authorization-server': continue
        if route.path in ('/token', '/register', '/revoke'):
            endpoint, path = route.endpoint, route.path
            async def guarded(scope, receive, send, original=endpoint, guarded_path=path):
                request = Request(scope, receive)
                if request.method == 'POST':
                    chunks, size = [], 0
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > 65536:
                            await JSONResponse({'error':'request_too_large'}, status_code=413)(scope, receive, send)
                            return
                        chunks.append(chunk)
                    raw = b''.join(chunks)
                    async def replay(): return {'type':'http.request', 'body':raw, 'more_body':False}
                    request = Request(scope, replay)
                    receive = replay
                    if guarded_path == '/token':
                        form = await request.form()
                        if form.get('resource') != provider.resource:
                            await JSONResponse({'error':'invalid_target'}, status_code=400)(scope, receive, send)
                            return
                    elif guarded_path == '/revoke':
                        form = await request.form()
                        # SDK 1.x requires this optional RFC 7009 field even for a public client.
                        values = list(form.multi_items())
                        if 'client_secret' not in form:
                            values.append(('client_secret', ''))
                        raw = str(httpx.QueryParams(values)).encode()
                    else:
                        now = time.time(); ip = request.client.host if request.client else 'unknown'
                        recent = [x for x in registration_attempts.get(ip, []) if x > now-60]
                        if len(recent) >= 20:
                            await JSONResponse({'error':'registration_rate_limited'}, status_code=429)(scope, receive, send)
                            return
                        registration_attempts[ip] = recent+[now]
                        if len(registration_attempts) > 2000:
                            registration_attempts.clear()
                await original(scope, receive, send)
            route.endpoint = guarded
            route.app = guarded
        app.router.routes.append(route)
    mount_consent(app, provider)

    mcp = FastMCP('WeChat Notifications', token_verifier=provider,
        auth=AuthSettings(issuer_url=issuer, resource_server_url=AnyHttpUrl(provider.resource),
                          required_scopes=[SCOPE], validate_token_resource=True),
        json_response=True, stateless_http=True, max_request_body_size=65536,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=[urlsplit(base).netloc], allowed_origins=[urlsplit(base).scheme+'://'+urlsplit(base).netloc]))

    async def request_api(path, payload=None, params=None):
        token = get_access_token()
        if not token: raise ValueError('OAuth authorization required')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base, timeout=30) as client:
            return await request_json(client, 'http://internal'+path, path,
                headers={'Authorization':'Bearer '+token.token}, payload=payload, params=params)

    register_tools(mcp, request_api)
    mcp_app = mcp.streamable_http_app()
    app.mount('/', EventGateway(mcp_app, app.state.events, urlsplit(base).netloc))
    return mcp
