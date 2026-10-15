"""Loopback acceptance server with independent encrypted data and fake platforms.

No receive workers, real Bot polling, real platform requests, or production files.
All channel factories use an in-process transport replacement, including newly
created connections. This is an HTTP/UI test version, not real recipient proof.
"""

# Imports follow environment isolation deliberately, before the application loads.
# ruff: noqa: E402

import asyncio
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import time
import re

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
from wechat_bridge.services.proxy import ProxyManager, GROUP


def platform(request, scope=None):
    if request.url.path.endswith("get_bot_qrcode"):
        return httpx.Response(
            200,
            json={"qrcode": "test-local", "qrcode_img_content": "http://127.0.0.1:19865/health"},
        )
    if "qrcode_status" in request.url.path:
        return httpx.Response(200, json={"status": "wait"})
    if request.url.path.endswith("tenant_access_token/internal"):
        secret = json.loads(request.content or b"{}").get("app_secret", "")
        if secret.startswith("test-invalid"):
            return httpx.Response(200, json={"code": 10003, "msg": "isolated credential rejection"})
        if secret.startswith("test-auth-timeout"):
            raise httpx.ConnectError("isolated auth unavailable", request=request)
        return httpx.Response(
            200, json={"code": 0, "tenant_access_token": secrets.token_urlsafe(24), "expire": 3600}
        )
    data = json.loads(request.content or b"{}")
    text = str(data)
    if "[test:timeout]" in text:
        raise httpx.ReadTimeout("test transport timeout", request=request)
    if "[test:reject]" in text:
        return httpx.Response(200, json={"ret": 400, "code": 99991663, "errmsg": "test rejection"})
    nonce = re.search(r"nb-test:[a-f0-9]{32}", text)
    if nonce and scope and "msg" in data:
        account = scope.account()
        if account:
            scope.ingest(
                {
                    "msgs": [
                        {
                            "message_id": secrets.token_hex(16),
                            "from_user_id": account["user_id"],
                            "message_type": 1,
                            "message_state": 2,
                            "context_token": account["context_token"],
                            "create_time_ms": int(time.time() * 1000),
                            "item_list": [{"type": 1, "text_item": {"text": nonce[0]}}],
                        }
                    ]
                },
                time.time(),
            )
    if "open-apis" in request.url.path:
        return httpx.Response(
            200, json={"code": 0, "data": {"message_id": "test-" + secrets.token_hex(8)}}
        )
    return httpx.Response(200, json={"ret": 0})


def make_proxy(store):
    nodes = [
        {
            "name": name,
            "type": "ss",
            "server": "8.8.8.8",
            "port": 443,
            "cipher": "aes-128-gcm",
            "password": secrets.token_urlsafe(24),
        }
        for name in ("日本 Pro 测试 A", "日本 Pro 测试 B", "美国 Pro 测试")
    ]
    selected = {"name": None}

    def control(request):
        if request.url.path == "/configs":
            return httpx.Response(204)
        if request.url.path == "/proxies/" + GROUP:
            if request.method == "PUT":
                selected["name"] = json.loads(request.content)["name"]
                return httpx.Response(204)
            return httpx.Response(200, json={"now": selected["name"]})
        if request.url.path.endswith("/delay"):
            return httpx.Response(200, json={"delay": 45 if "A" in request.url.path else 80})
        return httpx.Response(404)

    config = {
        "controller_url": "http://127.0.0.1:9090",
        "controller_secret": secrets.token_urlsafe(32),
        "allowed_hosts": ["connectors.api.openai.com"],
        "callback": {
            "host": "127.0.0.1",
            "port": 7890,
            "username": "local-test",
            "password": secrets.token_urlsafe(32),
        },
        "base_config": {"port": 7890, "proxies": nodes, "rules": ["MATCH,REJECT"]},
    }
    value = ProxyManager(
        store,
        config,
        transport=httpx.MockTransport(control),
        downloader=lambda url: (
            json.dumps({"proxies": nodes}, ensure_ascii=False).encode(),
            {"total": 100 * 2**30, "download": 4 * 2**30},
        ),
    )

    async def verify():
        return selected["name"] != "日本 Pro 测试 A"

    value.verify_selected = verify
    if not value.settings.get("subscription_url"):
        value.settings["subscription_url"] = "https://subscription.example.com/test"
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--first-install",
        action="store_true",
        help="Temporary F01 profile without an administrator, loopback 19866",
    )
    parser.add_argument("--port", type=int, help="Independent loopback-only acceptance port")
    parser.add_argument(
        "--directory", type=Path, help="Independent test profile beneath repository .private"
    )
    args = parser.parse_args()
    port = args.port or (19866 if args.first_install else 19865)
    if not 1024 <= port <= 65535:
        parser.error("Test port must be between 1024 and 65535")
    os.environ["WECHAT_PUBLIC_BASE_URL"] = f"http://127.0.0.1:{port}"
    private = args.directory or ROOT / (
        ".private/test-first-install-f01" if args.first_install else ".private/test-v03"
    )
    private = private.resolve()
    if not private.is_relative_to((ROOT / ".private").resolve()):
        parser.error("Test profile must stay beneath repository .private; no production data")
    private.mkdir(parents=True, exist_ok=True)
    key_path = private / "encryption.key"
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
    store = Store(private / "test.sqlite3", key_path.read_bytes())
    access_path = private / "local-access.json"
    accounts = AdminAccounts(store.db)
    if args.first_install and accounts.account():
        raise RuntimeError(
            "First-install test profile already has an account; existing data was not changed."
        )
    if not args.first_install and not accounts.account():
        access = {
            "username": "local-admin",
            "password": secrets.token_urlsafe(32),
        }
        accounts.initialize(access["username"], password_hash(access["password"]))
        access_path.write_text(json.dumps(access, indent=2), encoding="utf-8")
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
    transport = httpx.MockTransport(lambda request: platform(request, store))
    bridge = Bridge(store, transport)
    drivers = dict(BUILTIN_DRIVERS)

    def make_wechat(s, b):
        scope = WeChatStore(s, b)
        return Bridge(scope, httpx.MockTransport(lambda request: platform(request, scope)))

    drivers["wechat"] = ChannelDriver(
        make_wechat,
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
        drivers=drivers,
        pairing=Pairing(bridge, run_workers=False, transport=transport),
        proxy_factory=make_proxy,
    )
    app.state.test_environment = {
        "platforms": "simulated",
        "candidate": "v0.3",
        "receive_workers": False,
    }
    print(f"Isolated HTTP acceptance: http://127.0.0.1:{port}/admin/")
    print(
        "No administrator created in the separate F01 first-install test profile."
        if args.first_install
        else "Random local login stored in the private test profile/local-access.json; platform responses are simulated."
    )
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, access_log=False)
    finally:
        asyncio.run(bridge.close())
        store.close()


if __name__ == "__main__":
    main()
