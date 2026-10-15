"""Build the same plugin for cloud/local OAuth hosts; never package API keys."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
import zipfile
from package_checks import check, public_files, release_metadata, integration_document


def build(base_url, output, *, mcp_url=None):
    base = base_url.rstrip("/")
    p = urlsplit(base)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError("An HTTPS service base URL without credentials/query/fragment is required")
    endpoint = mcp_url or base + "/mcp"
    u = urlsplit(endpoint)
    if (
        u.scheme != "https"
        or not u.hostname
        or u.username
        or u.password
        or u.query
        or u.fragment
        or u.netloc != p.netloc
    ):
        raise ValueError("MCP URL must be HTTPS on the service origin")
    source = Path(__file__).resolve().parents[1]
    manifest = check(source)
    compat = json.loads((source / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    name = manifest["name"]
    mcp = {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        "mcpServers": {"wechat-notify": {"type": "streamable-http", "url": endpoint}},
    }
    legacy = {"mcpServers": {"wechat-notify": {"url": endpoint}}}
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_relative_to(source):
        raise ValueError("Write the archive outside the plugin source directory")
    entries = {
        filename: (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        for filename, value in [
            ("plugin.json", manifest),
            (".codex-plugin/plugin.json", compat),
            ("mcp.json", mcp),
            (".mcp.json", legacy),
        ]
    }
    for path in public_files(source / "skills", {".md", ".yaml"}):
        entries[path.relative_to(source).as_posix()] = path.read_text(encoding="utf-8").encode()
    for target, original in {
        "INSTALL.md": "docs/integration/CLIENT-SETUP.md",
        "AI-HOSTS.md": "docs/integration/AI-HOSTS.md",
        "F02-RECEIVERS.md": "docs/integration/RECEIVERS.md",
    }.items():
        entries[target] = integration_document(source.parent, Path(original).name)
    entries["CONNECTION.json"] = json.dumps(
        {
            "base_url": base,
            "mcp_url": endpoint,
            "transport": "remote",
            "client_id": None,
            "authorization": "User OAuth consent is required; this template grants no permissions.",
        },
        indent=2,
    ).encode()
    entries["README.md"] = (
        "# 远程 MCP 插件\n\n先读 INSTALL.md，实际地址在 CONNECTION.json。无需本机 Python。\n"
        "用户必须完成 OAuth 授权并核对身份；管理端系统设置可生成本人手机登录码，微信也可发 /web。纯飞书不要求绑定微信。\n"
        "不包含 API Key 或访问令牌；不要将验证码、凭据交给 AI。独立 ZIP 的宿主安装方式见 INSTALL.md 路径 B。\n"
    ).encode()
    entries["RELEASE.json"] = json.dumps(
        release_metadata(source, entries, scope="standalone-remote"), indent=2
    ).encode()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, content in sorted(entries.items()):
            info = zipfile.ZipInfo(name + "/" + filename, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mcp-url", help="Explicit MCP URL when OAuth keeps a legacy prefix")
    args = parser.parse_args()
    print(build(args.base_url, args.output, mcp_url=args.mcp_url))
