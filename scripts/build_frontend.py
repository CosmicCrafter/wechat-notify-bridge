"""Build Vue assets, or verify source/output hashes without Node at deployment time."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "frontend"
OUTPUT = ROOT / "server/src/wechat_bridge/web"


def build(check=False):
    if not check:
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm:
            raise SystemExit("Node.js and npm are required to build frontend assets.")
        subprocess.run([npm, "run", "build"], cwd=SOURCE, check=True)
    manifest = json.loads((SOURCE / "build-manifest.json").read_text(encoding="utf-8"))
    actual = {
        str(p.relative_to(SOURCE)).replace("\\", "/")
        for p in (SOURCE / "src").rglob("*")
        if p.is_file()
    } | {"build.mjs", "package.json", "package-lock.json"}
    if actual != set(manifest["inputs"]):
        raise SystemExit("Frontend inputs changed. Run npm run build in frontend/.")
    for base, entries in [(SOURCE, manifest["inputs"]), (OUTPUT, manifest["outputs"])]:
        for name, expected in entries.items():
            p = base / name
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
                raise SystemExit(
                    "Stale frontend asset: " + name + "; run npm run build in frontend/."
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    build(parser.parse_args().check)
    print("Frontend assets: PASS")
