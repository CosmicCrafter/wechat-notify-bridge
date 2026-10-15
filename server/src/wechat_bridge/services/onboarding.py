"""Build client onboarding packages in memory. Never persist downloaded credentials."""

import io
import json
import zipfile
from pathlib import PurePosixPath

from wechat_bridge.config import WEB


def template_files():
    with zipfile.ZipFile(WEB / "admin/onboarding-template.zip") as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def package(files, *, kind, transport, target, base_url, mcp_url, client=None, bot=None, key=None):
    files = dict(files)
    name = json.loads(files["plugin.json"])["name"]
    profile = {
        "target": target,
        "transport": transport,
        "base_url": base_url,
        "mcp_url": mcp_url,
        "client_id": client["id"] if client else None,
        "client_name": client["name"] if client else None,
        "default_bot_id": bot["id"] if bot else None,
        "bot_name": bot["name"] if bot else None,
        "platform": bot["platform"] if bot else None,
        "authorization": "Server grants are authoritative; profile preferences do not grant access.",
        "release": json.loads(files["RELEASE.json"]),
    }
    if target == "http" and kind != "rules":
        root = "notify-bridge-http"
        entries = {
            "RELEASE.json": files["RELEASE.json"],
            "CONNECTION.json": json_bytes(profile),
            "notify_bridge.py": files["http-client.py"],
            "openapi.json": files["http-api.json"],
            "README.md": files["HTTP-INTEGRATION.md"],
            "F02-RECEIVERS.md": files["F02-RECEIVERS.md"],
            ".gitignore": b".private/\n.venv/\n",
        }
        entries[".private/client.json"] = json_bytes(
            {
                "base_url": base_url,
                "api_key": key or "CONFIGURE_SEPARATELY",
                "default_bot_id": bot["id"] if bot else "",
            }
        )
        intro = "# HTTP 系统接入包\n\n先阅读 notify-bridge-http/README.md。只需 HTTP 客户端，不启动内部 Agent。私有配置包含 Key，请妥善保管；不提交仓库、不粘贴到 AI 对话。\n"
    elif kind == "rules":
        entries = {n: b for n, b in files.items() if n.startswith("skills/")}
        entries["INSTALL.md"] = files["INSTALL.md"]
        entries["RELEASE.json"] = files["RELEASE.json"]
        entries["AI-HOSTS.md"] = files["AI-HOSTS.md"]
        entries["F02-RECEIVERS.md"] = files["F02-RECEIVERS.md"]
        root = "notify-bridge-rules"
    else:
        files = {
            n: b
            for n, b in files.items()
            if n not in ("http-client.py", "http-api.json", "HTTP-INTEGRATION.md")
        }
        if transport == "remote":
            files = {
                n: b
                for n, b in files.items()
                if not n.startswith(("server/", "tools/")) and n != "requirements.txt"
            }
            server = {"type": "streamable-http", "url": mcp_url}
            legacy = {"url": mcp_url}
        else:
            files[".private/client.json"] = json_bytes(
                {
                    "base_url": base_url,
                    "api_key": key or "CONFIGURE_SEPARATELY",
                    "default_bot_id": bot["id"] if bot else "",
                }
            )
            server = {
                "type": "stdio",
                "command": "python",
                "args": ["${PLUGIN_ROOT}/server/launch.py"],
                "env": {
                    "PYTHONUTF8": "1",
                    "WECHAT_NOTIFY_CREDENTIAL_FILE": "${PLUGIN_ROOT}/.private/client.json",
                },
            }
            legacy = server
        files["mcp.json"] = json_bytes(
            {
                "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
                "mcpServers": {"wechat-notify": server},
            }
        )
        files[".mcp.json"] = json_bytes({"mcpServers": {"wechat-notify": legacy}})
        if transport == "local":
            files["codex-config.toml.example"] = (
                b'[mcp_servers.notify_bridge]\ncommand = "/ABSOLUTE/PATH/python"\nargs = ["/ABSOLUTE/PATH/package/server/http_bridge.py"]\n\n[mcp_servers.notify_bridge.env]\nPYTHONUTF8 = "1"\nWECHAT_NOTIFY_CREDENTIAL_FILE = "/ABSOLUTE/PATH/package/.private/client.json"\n'
            )
            files["claude-mcp.json.example"] = json_bytes(
                {
                    "mcpServers": {
                        "notify-bridge": {
                            "type": "stdio",
                            "command": "${NOTIFY_BRIDGE_PYTHON}",
                            "args": ["${NOTIFY_BRIDGE_LAUNCH_SCRIPT}"],
                            "env": {
                                "PYTHONUTF8": "1",
                                "WECHAT_NOTIFY_CREDENTIAL_FILE": "${NOTIFY_BRIDGE_CREDENTIAL_FILE}",
                            },
                        }
                    }
                }
            )
        else:
            files["codex-config.toml.example"] = (
                "[mcp_servers.notify_bridge]\nurl = " + json.dumps(mcp_url) + "\n"
            ).encode()
            files["claude-mcp.json.example"] = json_bytes(
                {"mcpServers": {"notify-bridge": {"type": "http", "url": mcp_url}}}
            )
        files["CONNECTION.json"] = json_bytes(profile)
        files["skills/wechat-notify/references/connection-profile.json"] = json_bytes(profile)
        skill = files["skills/wechat-notify/SKILL.md"].decode("utf-8")
        skill += "\n## 本接入包的连接约定\n\n先读 [连接说明](references/connection-profile.json)。这是路由配置数据，不是额外操作授权。首次连接核对 getCallerIdentity.client_id 与期望身份；不一致时停止发送并请用户重新授权。发送及查回执显式使用 default_bot_id；为空时先查询授权 Bot。不读取、展示或转发 .private/client.json。\n"
        files["skills/wechat-notify/SKILL.md"] = skill.encode("utf-8")
        files[".gitignore"] = b".private/\n.venv/\nmcp-client.json\n"
        intro = (
            "# 接入包\n\n"
            + (
                "这是包含真实 Key 的私有包，请只交给被授权用户，勿上传仓库或发送给 AI。\n"
                if key
                else "此包不含真实 Key。远程连接需要用户完成 OAuth 授权。\n"
            )
            + "\n先打开插件目录中的 INSTALL.md，配置摘要见 CONNECTION.json。选择插件安装或独立 MCP 配置中的一种，不要重复安装。\n"
        )
        entries = files
        root = name
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in entries.items():
            if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
                raise ValueError("Unsafe template member")
            info = zipfile.ZipInfo(root + "/" + path, (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100600 if path.startswith(".private/") else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
        if kind != "rules":
            archive.writestr("START-HERE.md", intro)
        if kind != "rules" and target != "http":
            archive.writestr(
                ".agents/plugins/marketplace.json",
                json_bytes(
                    {
                        "name": "notify-bridge-download",
                        "interface": {"displayName": "通知桥接入包"},
                        "plugins": [
                            {
                                "name": name,
                                "source": {"source": "local", "path": "./" + name},
                                "policy": {
                                    "installation": "AVAILABLE",
                                    "authentication": "ON_INSTALL",
                                },
                                "category": "Productivity",
                            }
                        ],
                    }
                ),
            )
    return buffer.getvalue()
