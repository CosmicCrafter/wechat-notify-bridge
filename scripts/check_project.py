"""Check documentation links, shared copies and built frontend integrity."""

import re
import shutil
import subprocess
import sys
import os
from pathlib import Path

from sync_shared import ROOT, sync
from build_frontend import build as build_frontend
from check_documentation import check as check_documentation, check_links


def check():
    sync(check=True)
    build_frontend(check=True)
    subprocess.run(
        [sys.executable, str(ROOT / "server/scripts/build_developer_kit.py"), "--check"], check=True
    )
    node = shutil.which("node")
    if node:
        for script in sorted((ROOT / "frontend/src").rglob("*.js")):
            subprocess.run([node, "--check", str(script)], check=True)
        subprocess.run(
            [node, "--check", str(ROOT / "server/src/wechat_bridge/web/admin/app.js")], check=True
        )
    subprocess.run([sys.executable, str(ROOT / "mcp-plugin/tools/package_checks.py")], check=True)
    ignored = {
        ".git",
        ".idea",
        ".pytest_cache",
        ".venv",
        ".private",
        ".data",
        ".secrets",
        "build",
        "dist",
        "__pycache__",
        "node_modules",
    }
    broken = []
    for file in ROOT.rglob("*.md"):
        if file.is_symlink() or any(part in ignored for part in file.relative_to(ROOT).parts):
            continue
        for target in re.findall(r"\]\(([^)]+)\)", file.read_text(encoding="utf-8")):
            if re.match(r"\w+:|#", target):
                continue
            path = target.split("#")[0]
            if path and not (file.parent / path).exists():
                broken.append(f"{file.relative_to(ROOT)}: {target}")
    if broken:
        raise SystemExit("Broken relative links:\n" + "\n".join(broken))
    entries = {}
    for directory, folders, files in os.walk(ROOT):
        folders[:] = [name for name in folders if name not in ignored and not name.startswith(".")]
        for name in files:
            path = Path(directory) / name
            if not path.is_symlink():
                entries[path.relative_to(ROOT).as_posix()] = (
                    path.read_bytes() if path.suffix == ".md" else b""
                )
    historical = ("docs/history/", "docs/product-v2/", "docs/product-v3/handoff/", "docs/f02/")
    active = {
        name
        for name in entries
        if not name.startswith(historical) and name != "docs/product-v3/IMPLEMENTATION.md"
    }
    check_links(entries, documents=active)
    print("Documentation contracts:", check_documentation())


if __name__ == "__main__":
    check()
    print("Documentation, shared files and frontend integrity: PASS")
