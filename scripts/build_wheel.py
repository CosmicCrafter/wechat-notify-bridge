"""Build a service wheel in a clean temporary tree; stale build/ cannot leak in."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from build_frontend import build

ROOT = Path(__file__).resolve().parents[1]


def package(output):
    build(check=True)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bridge-wheel-") as directory:
        stage = Path(directory)
        for name in ("pyproject.toml", "requirements.txt"):
            shutil.copy2(ROOT / "server" / name, stage / name)
        shutil.copytree(
            ROOT / "server/src/wechat_bridge",
            stage / "src/wechat_bridge",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                str(stage),
                "--wheel-dir",
                str(output),
            ],
            check=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ROOT / "dist"))
    package(parser.parse_args().output)
