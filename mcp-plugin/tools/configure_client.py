"""Prepare a downloaded local package; never print or send its credentials."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="Create a virtual environment and install requirements",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if sys.version_info < (3, 12):
        raise SystemExit("Python 3.12 or newer is required")
    config_path = root / ".private/client.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not config.get("api_key") or config["api_key"] == "CONFIGURE_SEPARATELY":
        raise SystemExit(
            "Fill the private client.json configuration first. Do not paste keys into AI chat."
        )
    interpreter = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if args.prepare:
        venv.EnvBuilder(with_pip=True).create(root / ".venv")
        subprocess.run(
            [str(interpreter), "-m", "pip", "install", "-r", str(root / "requirements.txt")],
            check=True,
        )
    if not interpreter.is_file():
        raise SystemExit(
            "Run this script with --prepare first, or use the manual MCP instructions."
        )
    config["python"] = str(interpreter)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    config_path.chmod(0o600)
    server = {
        "command": str(interpreter),
        "args": [str(root / "server/http_bridge.py")],
        "env": {"WECHAT_NOTIFY_CREDENTIAL_FILE": str(config_path), "PYTHONUTF8": "1"},
    }
    (root / "mcp-client.json").write_text(
        json.dumps({"mcpServers": {"wechat-notify": server}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Plugin hosts may cache only public plugin files. Keep the private file in
    # the original installation directory and reference its absolute path.
    for filename in ("mcp.json", ".mcp.json"):
        path = root / filename
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["mcpServers"]["wechat-notify"] = {
            **server,
            "type": "stdio",
            "args": ["${PLUGIN_ROOT}/server/http_bridge.py"],
        }
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "Prepared. Import mcp-client.json into your MCP client, or follow INSTALL.md for the plugin route."
    )
    print("No host configuration was changed. No notification was sent.")


if __name__ == "__main__":
    main()
