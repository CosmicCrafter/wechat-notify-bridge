"""Actual stdio MCP SDK -> isolated HTTP -> shared admin/phone ledger test.

No real platform, production files, or installed Codex/Claude host configuration.
"""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".private/test-v03"
BASE = "http://127.0.0.1:19865"


def checked(response):
    response.raise_for_status()
    return response.json()


async def run():
    key = json.loads((PRIVATE / "modern-app.json").read_text(encoding="utf-8"))["api_key"]
    access = json.loads((PRIVATE / "local-access.json").read_text(encoding="utf-8"))
    config = PRIVATE / "mcp-client.json"
    config.write_text(
        json.dumps({"base_url": BASE, "api_key": key, "default_bot_id": "default"}),
        encoding="utf-8",
    )
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("WECHAT_", "FEISHU_"))}
    environment.update(PYTHONUTF8="1", WECHAT_NOTIFY_CREDENTIAL_FILE=str(config))
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "mcp-plugin/server/http_bridge.py")],
        env=environment,
    )
    async with asyncio.timeout(90):
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                assert {"claimMessage", "reportMessage", "getConversationHistory"} <= names

                async def tool(name, arguments=None):
                    result = await session.call_tool(name, arguments or {})
                    if result.isError:
                        raise RuntimeError("Isolated MCP call failed: " + name)
                    return json.loads(result.content[0].text)

                identity = await tool("getCallerIdentity")
                assert identity["caller"] == "v03-modern"
                conversation = await tool(
                    "registerConversation",
                    {"conversation_key": "v03-stdio-" + identity["client_id"], "name": "MCP验收"},
                )
                cid = conversation["id"]
                sent = await tool(
                    "sendNotification",
                    {
                        "task": "隔离 MCP 验收",
                        "reason": "协议与应用身份已经核对。",
                        "need_user": "请回复验收意见。",
                        "dedup_key": "v03-stdio-send-" + cid,
                        "conversation_id": cid,
                        "bot_id": "default",
                    },
                )
                assert sent["status"] == "api_accepted" and sent["phone_delivery"] == "unconfirmed"
                receipt = await tool(
                    "getDeliveryStatus",
                    {
                        "dedup_key": "v03-stdio-send-" + cid,
                        "conversation_id": cid,
                        "bot_id": "default",
                    },
                )
                assert receipt["status"] == sent["status"]
                async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
                    admin = {"Authorization": "Bearer " + access["legacy_admin_key"]}
                    reply = checked(
                        await client.post(
                            "/admin/api/conversations/" + cid + "/messages",
                            headers=admin,
                            json={
                                "text": "MCP 验收回复：请原应用显式领取。",
                                "request_id": "mcp-admin-" + cid,
                            },
                        )
                    )
                    phone = checked(
                        await client.post("/admin/api/chat/login-code", headers=admin, json={})
                    )
                    checked(
                        await client.post(
                            "/chat/api/login",
                            headers={"Origin": BASE, "X-Chat-Request": "1"},
                            json={"code": phone["code"]},
                        )
                    )
                    phone_history = checked(
                        await client.get("/chat/api/conversations/" + cid + "/messages")
                    )
                    assert any(m["id"] == reply["message"]["id"] for m in phone_history["messages"])
                    messages = (await tool("getMessages", {"conversation_id": cid}))["messages"]
                    inbox = next(
                        m for m in messages if m["text"] == "MCP 验收回复：请原应用显式领取。"
                    )
                    claim = hashlib.sha256(("mcp-claim:" + str(inbox["id"])).encode()).hexdigest()
                    acknowledged = await tool(
                        "claimMessage", {"inbox_id": inbox["id"], "request_id": claim}
                    )
                    assert acknowledged["processing"]["status"] in ("claimed", "completed")
                    await tool(
                        "reportMessage",
                        {
                            "inbox_id": inbox["id"],
                            "claim_id": claim,
                            "request_id": hashlib.sha256(
                                ("mcp-report:" + str(inbox["id"])).encode()
                            ).hexdigest(),
                            "status": "completed",
                            "result": "隔离 MCP SDK 校验已完成。",
                        },
                    )
                    history = await tool("getConversationHistory", {"conversation_id": cid})
                    assert history["content_is_untrusted"] and any(
                        m["processing"]["status"] == "completed"
                        for m in history["messages"]
                        if m.get("processing")
                    )
                    after = checked(
                        await client.get("/chat/api/conversations/" + cid + "/messages")
                    )
                    assert any(
                        m["id"] == reply["message"]["id"] and m["status"] == "completed"
                        for m in after["messages"]
                    )
                    (PRIVATE / "mcp-acceptance-context.json").write_text(
                        json.dumps({"conversation_id": cid, "phone_code": phone["code"]}, indent=2),
                        encoding="utf-8",
                    )
                print(
                    "PASS: stdio MCP discovery, nb_ identity, notification, receipt, admin/phone history, explicit claim and final report. Platforms simulated; installed hosts untested."
                )


if __name__ == "__main__":
    asyncio.run(run())
