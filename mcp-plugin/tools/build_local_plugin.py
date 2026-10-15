"""Build the self-contained stdio plugin without credentials or dependencies."""

import argparse
import json
from pathlib import Path
import zipfile

from package_checks import (
    check,
    public_files,
    portable_markdown,
    release_metadata,
    integration_document,
)


def build(output):
    source = Path(__file__).resolve().parents[1]
    manifest = check(source)
    output = Path(output).resolve()
    if output.is_relative_to(source):
        raise ValueError("Write the archive outside the plugin source directory")
    names = [
        "plugin.json",
        "mcp.json",
        ".codex-plugin/plugin.json",
        ".mcp.json",
        "requirements.txt",
        "README.md",
        "DESKTOP-WAKE.md",
    ]
    files = [source / name for name in names]
    for directory, suffixes in [
        ("server", {".py"}),
        ("tools", {".py"}),
        ("skills", {".md", ".yaml"}),
        ("examples", {".json"}),
    ]:
        files.extend(public_files(source / directory, suffixes))
    if any(p.is_symlink() for p in files):
        raise ValueError("Symlinks are not allowed")
    entries = {
        p.relative_to(source).as_posix(): p.read_text(encoding="utf-8").encode() for p in files
    }
    for target, original in {
        "INSTALL.md": "docs/integration/CLIENT-SETUP.md",
        "AI-HOSTS.md": "docs/integration/AI-HOSTS.md",
        "F02-RECEIVERS.md": "docs/integration/RECEIVERS.md",
    }.items():
        entries[target] = integration_document(source.parent, Path(original).name)
    included = {"mcp-plugin/" + n for n in entries}
    for filename in list(entries):
        if filename.endswith(".md"):
            entries[filename] = portable_markdown(
                entries[filename].decode(), "mcp-plugin/" + filename, included
            ).encode()
    entries["RELEASE.json"] = json.dumps(
        release_metadata(source, entries, scope="standalone-local"), indent=2
    ).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, content in sorted(entries.items()):
            info = zipfile.ZipInfo(manifest["name"] + "/" + filename, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    print(build(parser.parse_args().output))
