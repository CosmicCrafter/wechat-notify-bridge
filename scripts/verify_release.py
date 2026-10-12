"""Verify a handoff ZIP without consulting the original checkout or exposing secrets."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile


def verify(path):
    with tempfile.TemporaryDirectory(prefix="bridge-release-") as directory:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Duplicate archive members")
            for name in names:
                parts = PurePosixPath(name).parts
                if "\\" in name or ".." in parts or name.startswith("/"):
                    raise ValueError("Unsafe archive path")
                if any(
                    p
                    in {
                        ".private",
                        ".secrets",
                        ".data",
                        ".venv",
                        "node_modules",
                        "__pycache__",
                        ".git",
                    }
                    for p in parts
                ):
                    raise ValueError("Private or generated directory in release")
                if (
                    Path(name).suffix in {".key", ".pem", ".sqlite3", ".db", ".enc", ".pyc"}
                    or Path(name).name == ".env"
                ):
                    raise ValueError("Private runtime file in release")
            archive.extractall(directory)
        root = Path(directory) / "notify-bridge"
        subprocess.run(
            [sys.executable, str(root / "scripts/check_project.py")], cwd=root, check=True
        )
        manifest = json.loads((root / "frontend/build-manifest.json").read_text(encoding="utf-8"))
        assert len(manifest["outputs"]) == 9
        print(
            f"Release verified: {len(names)} files; SHA256 {hashlib.sha256(Path(path).read_bytes()).hexdigest()}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    verify(parser.parse_args().archive)
