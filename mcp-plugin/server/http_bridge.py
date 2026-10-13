"""MCP adapter for the server-hosted WeChat API. No local WeChat session."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from mcp.server.fastmcp import FastMCP
from credential_store import dpapi
from api_errors import request_json

mcp = FastMCP("WeChat Notifications API", log_level="WARNING")


def configuration():
    key = os.environ.get("WECHAT_NOTIFY_API_KEY")
    if key:
        value = {
            "api_key": key,
            "base_url": os.environ.get("WECHAT_NOTIFY_BASE_URL", ""),
            "default_bot_id": os.environ.get("WECHAT_NOTIFY_BOT_ID", ""),
        }
    else:
        path = Path(
            os.environ.get("WECHAT_NOTIFY_CREDENTIAL_FILE")
            or Path.home() / ".config/wechat-notify-bridge/client.json"
        ).expanduser()
        try:
            raw = path.read_bytes()
            value = json.loads(dpapi(raw, decrypt=True) if path.suffix == ".dpapi" else raw)
        except Exception:
            raise ValueError("Cannot read private client configuration.") from None
    if not isinstance(value, dict):
        raise ValueError("Client configuration must be a JSON object")
    base, key = value.get("base_url"), value.get("api_key")
    if (
        not isinstance(base, str)
        or not isinstance(key, str)
        or not base
        or not key
        or key == "CONFIGURE_SEPARATELY"
    ):
        raise ValueError(
            "Configure the service URL and API key in the private client configuration."
        )
    p = urlsplit(base)
    local = p.scheme == "http" and p.hostname in ("127.0.0.1", "::1", "localhost")
    if (
        (p.scheme != "https" and not local)
        or not p.hostname
        or p.username
        or p.password
        or p.query
        or p.fragment
    ):
        raise ValueError("HTTPS is required except for a loopback-only local service.")
    bot = value.get("default_bot_id", "")
    if bot and (
        not isinstance(bot, str) or not __import__("re").fullmatch(r"[a-zA-Z0-9_-]{1,64}", bot)
    ):
        raise ValueError("Invalid default bot ID")
    return {**value, "base_url": base.rstrip("/"), "api_key": key}


def settings():
    config = configuration()
    return config["base_url"], config["api_key"]


async def request(path, payload=None, params=None):
    config = configuration()
    base, key = config["base_url"], config["api_key"]
    bot = config.get("default_bot_id")
    if (
        bot
        and path in ("/api/messages", "/api/notifications", "/api/task-cards")
        and payload is not None
        and not payload.get("bot_id")
    ):
        payload = {**payload, "bot_id": bot}
    if bot and path == "/api/deliveries" and not (params or {}).get("bot_id"):
        params = {**(params or {}), "bot_id": bot}
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        return await request_json(
            client,
            base + path,
            path,
            headers={"Authorization": "Bearer " + key},
            payload=payload,
            params=params,
        )


from toolkit import register_tools


async def request_proxy(path, payload=None, params=None):
    return await request(path, payload, params)


register_tools(mcp, request_proxy)

if __name__ == "__main__":
    mcp.run(transport="stdio")
