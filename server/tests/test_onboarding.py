import io
import json
import zipfile

import pytest
from test_portal import portal, ADMIN


def unpack(response):
    assert response.status_code == 200, response.text[:200]
    assert response.headers["cache-control"] == "no-store"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        return {n: archive.read(n) for n in archive.namelist()}


@pytest.fixture(autouse=True)
def base_url(portal, monkeypatch):
    monkeypatch.setenv("WECHAT_PUBLIC_BASE_URL", "https://notify.example.com/bridge")
    monkeypatch.setenv("WECHAT_OAUTH_BASE_URL", "https://notify.example.com/wechat")


def test_configured_local_issues_only_selected_grant_and_keeps_key_private(portal):
    store, client, *_ = portal
    bot = store.bots.create("专用飞书", "feishu")
    files = unpack(
        client.post(
            "/admin/api/onboarding/package",
            headers=ADMIN,
            json={
                "transport": "local",
                "credential_mode": "new",
                "client_name": "包测试",
                "bot_id": bot["id"],
                "private_ack": True,
            },
        )
    )
    private = json.loads(files["wechat-notify-local/.private/client.json"])
    identity = store.clients.authenticate(private["api_key"])
    assert store.bots.grants(identity.id) == {"bot_ids": [bot["id"]], "default_bot_id": bot["id"]}
    assert private["default_bot_id"] == bot["id"]
    assert sum(private["api_key"].encode() in value for value in files.values()) == 1
    assert private["api_key"] not in "\n".join(store.db.iterdump())
    assert "wechat-notify-local/tools/configure_client.py" in files
    assert (
        json.loads(files[".agents/plugins/marketplace.json"])["plugins"][0]["source"]["path"]
        == "./wechat-notify-local"
    )


def test_existing_key_does_not_rotate_or_change_grants(portal):
    store, client, auth, *_ = portal
    key = auth["Authorization"][7:]
    identity = store.clients.authenticate(key)
    before = dict(store.clients.get(identity.id))
    grants = store.bots.grants(identity.id)
    body = {
        "transport": "local",
        "client_id": identity.id,
        "bot_id": "default",
        "api_key": key,
        "private_ack": True,
    }
    unpack(client.post("/admin/api/onboarding/package", headers=ADMIN, json=body))
    assert dict(store.clients.get(identity.id)) == before
    assert store.bots.grants(identity.id) == grants
    body["api_key"] = "wrong-secret"
    result = client.post("/admin/api/onboarding/package", headers=ADMIN, json=body)
    assert result.status_code == 422 and "wrong-secret" not in result.text


def test_remote_package_contains_no_secret_or_local_process(portal):
    store, client, auth, *_ = portal
    identity = store.clients.authenticate(auth["Authorization"][7:])
    files = unpack(
        client.post(
            "/admin/api/onboarding/package",
            headers=ADMIN,
            json={"client_id": identity.id, "bot_id": "default", "transport": "remote"},
        )
    )
    assert not any("/.private/" in n or "/server/" in n or "/tools/" in n for n in files)
    config = json.loads(files["wechat-notify-local/mcp.json"])
    assert config["mcpServers"]["wechat-notify"]["url"] == "https://notify.example.com/wechat/mcp"
    assert json.loads(files["wechat-notify-local/CONNECTION.json"])["client_id"] == identity.id


@pytest.mark.parametrize("kind", ["template", "rules"])
def test_generic_downloads_do_not_create_identities(portal, kind):
    store, client, *_ = portal
    before = store.clients.list()
    files = unpack(
        client.post(
            "/admin/api/onboarding/package",
            headers=ADMIN,
            json={"kind": kind, "transport": "local"},
        )
    )
    assert store.clients.list() == before
    if kind == "rules":
        assert not any(n.endswith(("mcp.json", "client.json")) for n in files)
    else:
        assert (
            json.loads(files["wechat-notify-local/.private/client.json"])["api_key"]
            == "CONFIGURE_SEPARATELY"
        )


def test_export_auth_permissions_validation_and_loopback_policy(portal, monkeypatch):
    store, client, auth, *_ = portal
    path = "/admin/api/onboarding/package"
    for headers in ({}, auth):
        assert client.post(path, headers=headers, json={"kind": "rules"}).status_code == 401
    identity = store.clients.authenticate(auth["Authorization"][7:])
    bot = store.bots.create("未授权", "feishu")
    assert (
        client.post(
            path, headers=ADMIN, json={"client_id": identity.id, "bot_id": bot["id"]}
        ).status_code
        == 403
    )
    invalid = client.post(
        path, headers=ADMIN, json={"target": "invalid", "api_key": "PRIVATE-SENTINEL"}
    )
    assert invalid.status_code == 422 and "PRIVATE-SENTINEL" not in invalid.text
    assert (
        client.post(
            path,
            headers=ADMIN,
            json={"transport": "local", "client_id": identity.id, "bot_id": "default"},
        ).status_code
        == 422
    )
    monkeypatch.setenv("WECHAT_PUBLIC_BASE_URL", "http://127.0.0.1:8092")
    monkeypatch.setenv("WECHAT_OAUTH_BASE_URL", "http://127.0.0.1:8092")
    assert client.get("/admin/api/onboarding", headers=ADMIN).json()["remote_available"] is False
    assert (
        client.post(
            path, headers=ADMIN, json={"kind": "template", "transport": "remote"}
        ).status_code
        == 422
    )


def test_packaging_failure_rolls_back_new_key(portal, monkeypatch):
    store, client, *_ = portal
    from wechat_bridge.api import onboarding

    def fail(*args, **kwargs):
        raise RuntimeError("fixture packaging failure")

    monkeypatch.setattr(onboarding, "package", fail)
    before = store.clients.list()
    with pytest.raises(RuntimeError, match="fixture packaging failure"):
        client.post(
            "/admin/api/onboarding/package",
            headers=ADMIN,
            json={
                "transport": "local",
                "credential_mode": "new",
                "client_name": "失败包",
                "bot_id": "default",
                "private_ack": True,
            },
        )
    assert store.clients.list() == before


def test_downloaded_local_package_starts_and_discovers_tools(portal, monkeypatch, tmp_path):
    import asyncio
    import sys
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    expected = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            assert self.path == "/api/status"
            assert self.headers["Authorization"] == "Bearer " + expected["key"]
            payload = json.dumps(
                {
                    "caller": "包连通测试",
                    "client_id": expected["client_id"],
                    "bots": [{"id": "default"}],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        url = "http://127.0.0.1:" + str(http.server_port)
        monkeypatch.setenv("WECHAT_PUBLIC_BASE_URL", url)
        monkeypatch.setenv("WECHAT_OAUTH_BASE_URL", url)
        files = unpack(
            portal[1].post(
                "/admin/api/onboarding/package",
                headers=ADMIN,
                json={
                    "transport": "local",
                    "credential_mode": "new",
                    "client_name": "包连通测试",
                    "bot_id": "default",
                    "private_ack": True,
                },
            )
        )
        for name, content in files.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        root = tmp_path / "wechat-notify-local"
        config = json.loads((root / ".private/client.json").read_text("utf-8"))
        expected.update(
            key=config["api_key"], client_id=portal[0].clients.authenticate(config["api_key"]).id
        )

        async def check():
            parameters = StdioServerParameters(
                command=sys.executable,
                args=[str(root / "server/launch.py")],
                env={
                    "PYTHONUTF8": "1",
                    "WECHAT_NOTIFY_CREDENTIAL_FILE": str(root / ".private/client.json"),
                    "WECHAT_NOTIFY_PYTHON": sys.executable,
                    "NO_PROXY": "127.0.0.1",
                },
            )
            async with asyncio.timeout(20):
                async with stdio_client(parameters) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        assert {'getCallerIdentity','getConversationHistory','claimMessage','reportMessage'} <= {tool.name for tool in (await session.list_tools()).tools}
                        result = await session.call_tool("getCallerIdentity", {})
                        assert not result.isError
                        assert (
                            json.loads(result.content[0].text)["client_id"] == expected["client_id"]
                        )

        asyncio.run(check())
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=5)
