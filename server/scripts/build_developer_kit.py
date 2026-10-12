"""Build public developer assets from an explicit allowlist, never runtime configuration."""

from pathlib import Path
import json
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "server/src/wechat_bridge/web/admin"
files = [
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "server/openapi.json",
    "examples/python/notify_bridge.py",
    "mcp-plugin/README.md",
    "mcp-plugin/DESKTOP-WAKE.md",
    "mcp-plugin/examples/mcp-client.json",
    "mcp-plugin/examples/client.json",
]
files += [
    str(p.relative_to(ROOT)).replace("\\", "/") for p in sorted((ROOT / "docs").rglob("*.md"))
]
with zipfile.ZipFile(OUT / "developer-kit.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    archive.writestr(
        zipfile.ZipInfo("START-HERE.md", date_time=(2026, 1, 1, 0, 0, 0)),
        "# 通知桥开发接入包\n\n先读 DEPLOYMENT.json 获取实际服务地址（在线下载包提供），然后读 docs/integration/README.md，再读 docs/server/API.md。\n接口规范：server/openapi.json；Python 示例：examples/python/notify_bridge.py。\n本包不含密钥和服务端安装程序。请让管理员另行提供服务地址和专属客户端 Key。\n完整 MCP 插件和服务器源码：https://github.com/CosmicCrafter/wechat-notify-bridge\n文档中未包含的部署/插件源码链接请在完整仓库查看。\n",
    )
    for name in files:
        info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, (ROOT / name).read_bytes())
(OUT / "developer-docs.json").write_text(
    json.dumps(
        {
            "guide": (ROOT / "docs/integration/README.md").read_text(encoding="utf-8"),
            "api": (ROOT / "docs/server/API.md").read_text(encoding="utf-8"),
            "cards": (ROOT / "docs/server/TASK-CARDS.md").read_text(encoding="utf-8"),
        },
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
print("Built developer kit:", len(files), "public files")
