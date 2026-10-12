"""Check documentation links, shared copies and built frontend integrity."""

import re
import shutil
import subprocess
import sys

from sync_shared import ROOT, sync
from build_frontend import build as build_frontend


def check():
    sync(check=True)
    build_frontend(check=True)
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


if __name__ == "__main__":
    check()
    print("Documentation, shared files and frontend integrity: PASS")
