"""Actual stdio SDK against the loopback F02 fixture, never a real AI host."""

import asyncio
import json
import os
from pathlib import Path
import secrets
import sys
import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".private/f02-notification-acceptance"
BASE = "http://127.0.0.1:19865"


async def main():
    access = json.loads((ROOT / ".private/test-v03/local-access.json").read_text(encoding="utf-8"))
    async with httpx.AsyncClient(base_url=BASE) as client:
        response = await client.post(
            "/admin/api/auth/login",
            headers={"Origin": BASE, "X-Admin-Request": "1"},
            json={"username": access["username"], "password": access["password"]},
        )
        response.raise_for_status()
        status = await client.get("/admin/api/status")
        status.raise_for_status()
        assert status.json()["environment"]["platforms"] == "simulated"
    context = json.loads((PRIVATE / "result.json").read_text(encoding="utf-8"))
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("WECHAT_", "FEISHU_"))}
    environment.update(PYTHONUTF8="1", WECHAT_NOTIFY_CREDENTIAL_FILE=str(PRIVATE / "client.json"))
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "mcp-plugin/server/http_bridge.py")],
        env=environment,
    )
    async with asyncio.timeout(90):
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                assert len(tools) == 18
                assert (
                    "level"
                    in next(t for t in tools if t.name == "sendMessage").inputSchema["properties"]
                )

                async def call(name, arguments=None):
                    result = await session.call_tool(name, arguments or {})
                    if result.isError:
                        raise RuntimeError("Isolated MCP failed: " + name)
                    value = json.loads(result.content[0].text)
                    assert "receiver_setup" not in value and "receiver_token" not in value
                    return value

                identity = await call("getCallerIdentity")
                assert identity["client_id"] == context["client_id"]
                cid = context["conversation_id"]
                await call("getConversationHistory", {"conversation_id": cid})
                args = {
                    "conversation_id": cid,
                    "text": "真实 stdio SDK：原接收权限与通知策略已核对。",
                    "dedup_key": "f02-mcp-" + secrets.token_hex(12),
                }
                sent = await call("sendMessage", args)
                assert sent["status"] in ("api_accepted", "no_error_reported")
                receipt = await call(
                    "getDeliveryStatus", {"conversation_id": cid, "dedup_key": args["dedup_key"]}
                )
                assert receipt["bot_id"] == sent["bot_id"] and receipt["status"] == sent["status"]
                urgent = await call(
                    "sendMessage",
                    {
                        **args,
                        "dedup_key": args["dedup_key"] + "-urgent",
                        "level": "urgent",
                        "dry_run": True,
                    },
                )
                assert (
                    urgent["bot_id"] == context["urgent_bot"]
                    and urgent["status"] == "dry_run_ready"
                )
                denied = await session.call_tool(
                    "getMessages", {"conversation_id": context["peer_id"]}
                )
                assert denied.isError
                print(
                    json.dumps(
                        {
                            "stdio_sdk": True,
                            "tools": len(tools),
                            "scoped_read": True,
                            "cross_conversation_denied": True,
                            "policy_receipt_matched": True,
                            "normal_bot": sent["bot_id"],
                            "real_host": False,
                        }
                    )
                )


if __name__ == "__main__":
    asyncio.run(main())
