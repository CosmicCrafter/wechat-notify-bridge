"""Composition root. Public ASGI factory and import path remain stable."""

import os
from fastapi import FastAPI
from wechat_bridge import __version__
from wechat_bridge.runtime.lifecycle import create_lifespan
from wechat_bridge.api.security import install_security
from wechat_bridge.api.portal import mount_portal
from wechat_bridge.api.admin import mount_admin
from wechat_bridge.api.clients import mount_client_api
from wechat_bridge.api.channels import mount_channels
from wechat_bridge.api.proxy import mount_proxy
from wechat_bridge.mcp.server import mount_remote_mcp


def create_app(bridge=None, clients=None, run_workers=True, *, admin_hash=None, pairing=None):
    app = FastAPI(
        title="Notify Bridge API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=create_lifespan(
            bridge, clients, run_workers, admin_hash=admin_hash, pairing=pairing
        ),
        servers=(
            [{"url": os.environ["WECHAT_PUBLIC_BASE_URL"]}]
            if os.environ.get("WECHAT_PUBLIC_BASE_URL")
            else []
        ),
    )
    authorize, authorize_admin = install_security(app)
    mount_portal(app, authorize_admin)
    mount_admin(app, authorize_admin)
    mount_proxy(app, authorize_admin)
    mount_channels(app, authorize_admin)

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    mount_client_api(app, authorize)
    app.state.remote_mcp = mount_remote_mcp(app)
    return app


app = create_app()
