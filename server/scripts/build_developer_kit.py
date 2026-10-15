"""Build or check developer assets against their public source files."""

import argparse
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
# Reader-oriented allowlist: historical designs and server deployment sources stay in the repository.
FILES = [
    "docs/integration/README.md",
    "docs/integration/CLIENT-SETUP.md",
    "docs/integration/AI-HOSTS.md",
    "docs/integration/HTTP.md",
    "docs/integration/RECEIVERS.md",
    "docs/server/API.md",
    "docs/server/BOTS.md",
    "docs/server/FEISHU.md",
    "docs/server/TASK-CARDS.md",
    "docs/server/IMAGES.md",
    "docs/server/CHAT.md",
    "docs/server/REMOTE-MCP.md",
    "docs/server/MCP-EVENTS.md",
    "docs/server/DELIVERY-RELIABILITY.md",
    "docs/wechat-markdown/微信Markdown排版指南.md",
    "server/openapi.json",
    "examples/python/notify_bridge.py",
]
DOCS = {
    "guide": "docs/integration/README.md",
    "setup": "docs/integration/CLIENT-SETUP.md",
    "api": "docs/server/API.md",
    "cards": "docs/server/TASK-CARDS.md",
    "operations": "docs/product-v3/OPERATIONS.md",
    "ai": "docs/integration/AI-HOSTS.md",
    "http": "docs/integration/HTTP.md",
}
INTRO = """# 通知桥接入文档包

先读 [接入指南](docs/integration/README.md)，按用途选择 [AI 安装](docs/integration/CLIENT-SETUP.md) 或 [HTTP 接入](docs/integration/HTTP.md)。
在线下载的 DEPLOYMENT.json 提供实际 base_url 和 mcp_url；不要自行拼接迁移后的 MCP 地址。
版本与公开源指纹见 RELEASE.json；接口规范 server/openapi.json，示例 examples/python/notify_bridge.py。
本包不含真实 Key、MCP 可执行插件或服务端安装程序。请管理员另行提供私有凭据或从向导下载对应接入包。
未收录的维护/源码资料链接会明确指向完整仓库；历史设计和验收记录不混入本包。
"""


def contents(root):
    import sys

    sys.path.insert(0, str(ROOT / "mcp-plugin/tools"))
    from package_checks import portable_markdown, release_metadata

    entries = {"START-HERE.md": INTRO.encode("utf-8")}
    for name in FILES:
        path = root / name
        if path.is_symlink():
            raise ValueError("Symlinks are not developer kit inputs: " + name)
        content = path.read_text(encoding="utf-8")
        if path.suffix == ".md":
            content = portable_markdown(content, name, set(FILES))
        entries[name] = content.encode("utf-8")
    release = release_metadata(root / "mcp-plugin", entries, scope="developer-docs")
    entries["RELEASE.json"] = json.dumps(release, ensure_ascii=False, indent=2).encode("utf-8")
    docs = {key: (root / path).read_text(encoding="utf-8") for key, path in DOCS.items()}
    docs.update(_sources=DOCS, _release=release)
    return entries, json.dumps(docs, ensure_ascii=False).encode("utf-8")


def build(root=ROOT, *, check=False):
    entries, docs = contents(root)
    out = root / "server/src/wechat_bridge/web/admin"
    if check:
        stale = []
        try:
            with zipfile.ZipFile(out / "developer-kit.zip") as archive:
                names = archive.namelist()
                if len(names) != len(set(names)) or set(names) != set(entries):
                    stale.append("developer-kit.zip member list")
                elif any(archive.read(name) != content for name, content in entries.items()):
                    stale.append("developer-kit.zip content")
        except (OSError, ValueError, zipfile.BadZipFile, KeyError):
            stale.append("developer-kit.zip unavailable or invalid")
        if (
            not (out / "developer-docs.json").is_file()
            or (out / "developer-docs.json").read_bytes() != docs
        ):
            stale.append("developer-docs.json")
        if stale:
            raise SystemExit(
                "Stale developer assets: "
                + ", ".join(stale)
                + "; run python server/scripts/build_developer_kit.py"
            )
        return
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out / "developer-kit.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    (out / "developer-docs.json").write_bytes(docs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    build(check=args.check)
    from build_onboarding_assets import build as build_onboarding

    build_onboarding(check=args.check)
    print("Developer assets: " + ("PASS" if args.check else "built"))
