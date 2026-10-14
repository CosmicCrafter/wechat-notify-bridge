"""Acquire resources once and release in reverse order, including failed startup."""

from contextlib import asynccontextmanager, AsyncExitStack
import asyncio
import json
import os
from pathlib import Path

from wechat_bridge.services.bridge import Bridge
from wechat_bridge.storage.database import Store
from wechat_bridge.storage.admin_accounts import AdminAccounts
from wechat_bridge.wechat.pairing import Pairing
from wechat_bridge.services.proxy import ProxyManager
from wechat_bridge.channels import Channels


async def stop_task(task):
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def create_lifespan(
    bridge=None, clients=None, run_workers=True, *, admin_hash=None, pairing=None, drivers=None
):
    @asynccontextmanager
    async def lifespan(app):
        async with AsyncExitStack() as stack:
            active_bridge, seed, admin = bridge, clients, admin_hash
            if active_bridge is None:
                secrets = Path(os.environ.get("WECHAT_SECRETS", "/run/secrets"))
                data = Path(os.environ.get("WECHAT_DATA", "/data"))
                data.mkdir(parents=True, exist_ok=True)
                store = Store(
                    data / "wechat.sqlite3", (secrets / "encryption.key").read_bytes().strip()
                )
                stack.callback(store.close)
                if (secrets / "bootstrap.enc").exists():
                    store.bootstrap((secrets / "bootstrap.enc").read_bytes())
                seed = json.loads((secrets / "clients.json").read_text(encoding="utf-8"))
                if (secrets / "admin.json").exists():
                    admin = json.loads((secrets / "admin.json").read_text(encoding="utf-8"))[
                        "key_sha256"
                    ]
                active_bridge = Bridge(store)
            if bridge is None or run_workers:
                stack.push_async_callback(active_bridge.close)
            active_pairing = pairing or Pairing(active_bridge, run_workers=run_workers)
            stack.push_async_callback(active_pairing.close)
            channels = Channels(active_bridge, active_pairing, run_workers, drivers=drivers)
            stack.push_async_callback(channels.close)
            proxy = ProxyManager(active_bridge.store)
            stack.push_async_callback(proxy.close)
            app.state.admin_accounts = AdminAccounts(active_bridge.store.db)
            app.state.bridge, app.state.channels = active_bridge, channels
            app.state.admin_hash, app.state.pairing, app.state.proxy = admin, active_pairing, proxy
            active_bridge.store.clients.seed(seed or {})
            if run_workers:
                proxy.start()
                if any(
                    b["id"] == "default" and b["enabled"] for b in active_bridge.store.bots.list()
                ):
                    await active_bridge.start()
            await channels.reconcile()
            if app.state.oauth:
                app.state.oauth.initialize()
            if app.state.events:
                app.state.events.initialize()
                if run_workers:
                    task = asyncio.create_task(app.state.events.run(), name="bridge-event-delivery")
                    stack.push_async_callback(stop_task, task)
            if app.state.remote_mcp:
                await stack.enter_async_context(app.state.remote_mcp.session_manager.run())
            yield

    return lifespan
