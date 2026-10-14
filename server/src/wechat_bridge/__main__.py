"""Loopback-only local entry point; server deployments retain the ASGI entry."""

import argparse
import os
from pathlib import Path

from cryptography.fernet import Fernet


def initialize(directory):
    """Create one fresh local installation; refuse mixed or partial credentials."""
    directory = Path(directory).resolve()
    private = directory / "secrets"
    required = ("encryption.key", "clients.json")
    if private.exists():
        if not all((private / name).is_file() for name in required):
            raise RuntimeError(
                "Incomplete secrets directory. Restore the original files; do not rotate encryption.key."
            )
        return
    if (directory / "data/wechat.sqlite3").exists():
        raise RuntimeError("Existing database has no secrets. Restore its original encryption key.")
    private.mkdir(parents=True, mode=0o700)
    files = {
        private / "encryption.key": Fernet.generate_key(),
        private / "clients.json": b"{}",
    }
    for path, value in files.items():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)


def main():
    parser = argparse.ArgumentParser(description="Run a private Notify Bridge on this computer.")
    parser.add_argument("--directory", type=Path, default=Path.home() / ".notify-bridge")
    parser.add_argument("--port", type=int, default=8092)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    initialize(args.directory)
    directory = args.directory.resolve()
    os.environ["WECHAT_DATA"] = str(directory / "data")
    os.environ["WECHAT_SECRETS"] = str(directory / "secrets")
    os.environ["WECHAT_PUBLIC_BASE_URL"] = f"http://127.0.0.1:{args.port}"
    os.environ["WECHAT_OAUTH_BASE_URL"] = os.environ["WECHAT_PUBLIC_BASE_URL"]
    print(f"Management: http://127.0.0.1:{args.port}/admin/")
    print(
        "Management uses an administrator username and password; legacy administrator Keys are disabled."
    )
    print(
        "For first setup, use the authorized admin_reset terminal tool with --initialize --username."
    )
    import uvicorn

    uvicorn.run(
        "wechat_bridge.app:app", host="127.0.0.1", port=args.port, workers=1, access_log=False
    )


if __name__ == "__main__":
    main()
