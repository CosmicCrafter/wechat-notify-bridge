"""Bundle public plugin sources for the installed server's on-demand ZIP builder."""

import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def build(root=ROOT, *, check=False):
    plugin = root / "mcp-plugin"
    names = [
        "plugin.json",
        "mcp.json",
        ".mcp.json",
        ".codex-plugin/plugin.json",
        "requirements.txt",
    ]
    for directory, extensions in [
        ("server", {".py"}),
        ("skills", {".md", ".yaml"}),
        ("tools", {".py"}),
    ]:
        names += [
            p.relative_to(plugin).as_posix()
            for p in sorted((plugin / directory).rglob("*"))
            if p.is_file() and p.suffix in extensions and "__pycache__" not in p.parts
        ]
    expected = {}
    for name in names:
        path = plugin / name
        if path.is_symlink():
            raise ValueError("Symlink in onboarding template")
        expected[name] = path.read_text(encoding="utf-8").encode("utf-8")
    expected["INSTALL.md"] = (
        (root / "docs/integration/CLIENT-SETUP.md").read_text(encoding="utf-8").encode("utf-8")
    )
    for destination, source in {
        "http-client.py": "examples/python/notify_bridge.py",
        "http-api.json": "server/openapi.json",
        "HTTP-INTEGRATION.md": "docs/integration/HTTP.md",
        "AI-HOSTS.md": "docs/integration/AI-HOSTS.md",
        "F02-RECEIVERS.md": "docs/integration/RECEIVERS.md",
    }.items():
        expected[destination] = (root / source).read_text(encoding="utf-8").encode()
    output = root / "server/src/wechat_bridge/web/admin/onboarding-template.zip"
    if check:
        try:
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                if (
                    len(names) != len(set(names))
                    or set(names) != set(expected)
                    or any(archive.read(n) != b for n, b in expected.items())
                ):
                    raise ValueError("stale")
        except (OSError, ValueError, zipfile.BadZipFile):
            raise SystemExit(
                "Stale onboarding template; run python server/scripts/build_developer_kit.py"
            ) from None
        return
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in expected.items():
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    build(check=parser.parse_args().check)
