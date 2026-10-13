"""Build or check developer assets against their public source files."""

import argparse
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
FILES = [
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
INTRO = "# 通知桥开发接入包\n\n先读 DEPLOYMENT.json 获取实际服务地址（在线下载包提供），然后读 docs/integration/README.md，再读 docs/server/API.md。\n接口规范：server/openapi.json；Python 示例：examples/python/notify_bridge.py。\n本包不含密钥和服务端安装程序。请让管理员另行提供服务地址和专属客户端 Key。\n完整 MCP 插件和服务器源码：https://github.com/CosmicCrafter/wechat-notify-bridge\n文档中未包含的部署/插件源码链接请在完整仓库查看。\n"


def contents(root):
    names = FILES + [p.relative_to(root).as_posix() for p in sorted((root / "docs").rglob("*.md"))]
    entries = {"START-HERE.md": INTRO.encode("utf-8")}
    for name in names:
        path = root / name
        if path.is_symlink():
            raise ValueError("Symlinks are not developer kit inputs: " + name)
        # All allowlisted inputs are UTF-8 text. Match Git LF checkout on every OS.
        entries[name] = path.read_text(encoding="utf-8").encode("utf-8")
    docs = {
        key: (root / path).read_text(encoding="utf-8")
        for key, path in {
            "guide": "docs/integration/README.md",
            "setup": "docs/integration/CLIENT-SETUP.md",
            "api": "docs/server/API.md",
            "cards": "docs/server/TASK-CARDS.md",
        }.items()
    }
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
