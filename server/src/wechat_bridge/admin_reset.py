"""Authorized local terminal maintenance; this module has no HTTP route."""

import argparse
import getpass
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from wechat_bridge.storage.admin_accounts import AdminAccounts, password_hash
from wechat_bridge.storage.client_registry import ClientError


def backup(db, directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        identity = os.environ.get("USERDOMAIN", "") + "\\" + os.environ["USERNAME"]
        subprocess.run(
            ["icacls.exe", str(directory), "/inheritance:r", "/grant:r", identity + ":(OI)(CI)F"],
            check=True,
            capture_output=True,
        )
    elif directory.stat().st_mode & 0o077:
        raise ValueError("Backup directory must be private (0700).")
    target = directory / (
        "before-admin-reset-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + secrets.token_hex(4)
        + ".sqlite3"
    )
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    destination = sqlite3.connect(target)
    try:
        db.backup(destination)
        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Consistent backup integrity check failed.")
    finally:
        destination.close()
    return target


def reset(database, backup_dir, password, *, name=None, initialize=False):
    path = Path(database).resolve(strict=True)
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        # Backup precedes even additive authentication setup. No ASGI app/workers loaded.
        snapshot = backup(db, backup_dir)
        accounts = AdminAccounts(db)
        encoded = password_hash(password)
        current = accounts.account()
        if current:
            if initialize:
                raise ValueError("Administrator already initialized; use reset mode.")
            accounts.change(
                name=name, encoded=encoded, source="terminal", expected_version=current["version"]
            )
        elif initialize and name:
            accounts.initialize(name, encoded)
            accounts.audit("terminal_initialize", "terminal")
        else:
            raise ValueError(
                "Administrator not initialized; explicit --initialize --username required."
            )
        return snapshot
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--authorize", required=True, choices=["RESET_ADMIN"])
    parser.add_argument("--username")
    parser.add_argument("--initialize", action="store_true")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.error(
            "Run from an interactive authorized server terminal; password arguments/pipes are unsupported."
        )
    password = getpass.getpass("New administrator password (15-128 characters): ")
    if password != getpass.getpass("Confirm password: "):
        parser.error("Passwords do not match.")
    try:
        snapshot = reset(
            args.database, args.backup_dir, password, name=args.username, initialize=args.initialize
        )
    except (ValueError, OSError, sqlite3.Error, ClientError):
        parser.error(
            "Reset not completed; inspect the private database/backup paths and account state. No credentials are printed."
        )
    print(
        "Administrator credential changed and management sessions revoked. Application Keys, Bot settings, messages and encryption key unchanged."
    )
    print("Consistent pre-reset snapshot: " + str(snapshot))
    print("Backup created and integrity checked; this command is not a restoration test.")


if __name__ == "__main__":
    main()
