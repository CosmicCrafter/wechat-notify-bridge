"""Loopback acceptance server with independent encrypted data and fake platforms.

No receive workers, real Bot polling, real platform requests, or production files.
All channel factories use an in-process transport replacement, including newly
created connections. This is an HTTP/UI test version, not real recipient proof.
"""

# Imports follow environment isolation deliberately, before the application loads.
# ruff: noqa: E402

import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server/src"))
for name in list(os.environ):
    if name.startswith(("WECHAT_", "FEISHU_")):
        del os.environ[name]
os.environ["WECHAT_PUBLIC_BASE_URL"] = "http://127.0.0.1:19865"

import httpx
import uvicorn
from cryptography.fernet import Fernet
from wechat_bridge.app import create_app
from wechat_bridge.channels.drivers import BUILTIN_DRIVERS, ChannelDriver
from wechat_bridge.channels.feishu.adapter import Feishu
from wechat_bridge.channels.wechat_store import WeChatStore
from wechat_bridge.services.bridge import Bridge
from wechat_bridge.storage.admin_accounts import AdminAccounts, password_hash
from wechat_bridge.storage.database import Store
from wechat_bridge.wechat.pairing import Pairing


def platform(request):
    if request.url.path.endswith("get_bot_qrcode"):
        return httpx.Response(
            200,
            json={"qrcode": "test-local", "qrcode_img_content": "http://127.0.0.1:19865/health"},
        )
    if "qrcode_status" in request.url.path:
        return httpx.Response(200, json={"status": "wait"})
    if request.url.path.endswith("tenant_access_token/internal"):
        return httpx.Response(
            200, json={"code": 0, "tenant_access_token": secrets.token_urlsafe(24), "expire": 3600}
        )
    data = json.loads(request.content or b"{}")
    text = str(data)
    if "[test:timeout]" in text:
        raise httpx.ReadTimeout("test transport timeout", request=request)
    if "[test:reject]" in text:
        return httpx.Response(200, json={"ret": 400, "code": 99991663, "errmsg": "test rejection"})
    if "open-apis" in request.url.path:
        return httpx.Response(
            200, json={"code": 0, "data": {"message_id": "test-" + secrets.token_hex(8)}}
        )
    return httpx.Response(200, json={"ret": 0})


def main():
    private = ROOT / ".private/test-v03"
    private.mkdir(parents=True, exist_ok=True)
    key_path = private / "encryption.key"
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
    store = Store(private / "test.sqlite3", key_path.read_bytes())
    access_path = private / "local-access.json"
    accounts = AdminAccounts(store.db)
    if not accounts.account():
        access = {
            "username": "local-admin",
            "password": secrets.token_urlsafe(32),
            "legacy_admin_key": secrets.token_urlsafe(32),
        }
        accounts.initialize(access["username"], password_hash(access["password"]))
        access_path.write_text(json.dumps(access, indent=2), encoding="utf-8")
    access = json.loads(access_path.read_text(encoding="utf-8"))
    if not store.account():
        store.bind(
            dict(
                bot_token=secrets.token_urlsafe(32),
                bot_id="test-wechat",
                user_id="test-owner",
                context_token=secrets.token_urlsafe(32),
                base_url="https://ilinkai.weixin.qq.com",
                bound_at=time.time(),
            )
        )
    transport = httpx.MockTransport(platform)
    bridge = Bridge(store, transport)
    drivers = dict(BUILTIN_DRIVERS)
    drivers["wechat"] = ChannelDriver(
        lambda s, b: Bridge(WeChatStore(s, b), transport),
        drivers["wechat"].status,
        drivers["wechat"].delivery,
        pairing=lambda adapter, workers: Pairing(adapter, run_workers=False, transport=transport),
    )
    drivers["feishu"] = ChannelDriver(
        lambda s, b: Feishu(s, transport=transport, bot_id=b),
        drivers["feishu"].status,
        drivers["feishu"].delivery,
        sync_task=drivers["feishu"].sync_task,
    )
    app = create_app(
        bridge,
        {},
        False,
        admin_hash=hashlib.sha256(access["legacy_admin_key"].encode()).hexdigest(),
        drivers=drivers,
        pairing=Pairing(bridge, run_workers=False, transport=transport),
    )
    print("Isolated HTTP acceptance: http://127.0.0.1:19865/admin/")
    print(
        "Random local login stored in .private/test-v03/local-access.json; platform responses are simulated."
    )
    try:
        uvicorn.run(app, host="127.0.0.1", port=19865, access_log=False)
    finally:
        asyncio.run(bridge.close())
        store.close()


if __name__ == "__main__":
    main()
