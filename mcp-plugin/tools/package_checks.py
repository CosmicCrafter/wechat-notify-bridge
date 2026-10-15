"""Offline package checks; complements official schema and Skill validation."""

import json
from pathlib import Path
import re
import hashlib
import posixpath
from urllib.parse import quote

REPOSITORY = "https://github.com/CosmicCrafter/wechat-notify-bridge/blob/main/"


def portable_markdown(text, name, included):
    """Keep bundled links local; make omitted repository sources explicit online links."""

    def target(match):
        href = match[1]
        if re.match(r"\w+:|#", href):
            return match[0]
        path, separator, anchor = href.partition("#")
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), path))
        if resolved in included:
            return match[0]
        if resolved.startswith("../") or resolved.startswith("/"):
            raise ValueError("Documentation link escapes repository: " + name)
        return (
            "]("
            + REPOSITORY
            + quote(resolved, safe="/")
            + (separator + anchor if separator else "")
            + ")"
        )

    return re.sub(r"\]\(([^)]+)\)", target, text)


def release_metadata(plugin, entries):
    """Public source fingerprint only; never hash or include configured credentials."""
    plugin = Path(plugin)
    version = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))["version"]
    api = plugin.parent / "server/openapi.json"
    if api.is_file():
        server = json.loads(api.read_text(encoding="utf-8"))["info"]["version"]
    else:
        server = json.loads((plugin / "RELEASE.json").read_text(encoding="utf-8"))["server_version"]
    digest = hashlib.sha256()
    for name, value in sorted(entries.items()):
        if ".private" in name.split("/"):
            raise ValueError("Release metadata accepts public inputs only")
        digest.update(name.encode() + b"\0" + value + b"\0")
    return dict(
        format_version=1,
        server_version=server,
        plugin_version=version,
        public_source_sha256=digest.hexdigest(),
    )


def check(source):
    source = Path(source).resolve()
    main = json.loads((source / "plugin.json").read_text(encoding="utf-8"))
    legacy = json.loads((source / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", main["name"]) and len(main["name"]) <= 64
    assert re.fullmatch(r"\d+\.\d+\.\d+", main["version"])
    assert (main["name"], main["version"]) == (legacy["name"], legacy["version"])
    assert not {"skills", "mcpServers", "interface", "apps"} & main.keys()
    ui = main["extensions"]["com.openai"]["interface"]
    assert 0 < len(ui["shortDescription"]) <= 30
    for key in ("displayName", "shortDescription"):
        assert ui[key] == legacy["interface"][key]
    assert (source / legacy["skills"]).is_dir() and (source / legacy["mcpServers"]).is_file()
    modern = json.loads((source / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    compat = json.loads((source / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert modern.keys() == compat.keys()
    for name, server in modern.items():
        if server["type"] == "stdio":
            assert server["command"] == compat[name]["command"]
            assert server["args"] == compat[name]["args"]
            for arg in server["args"]:
                if arg.startswith("${PLUGIN_ROOT}/"):
                    assert (source / arg.removeprefix("${PLUGIN_ROOT}/")).is_file()
        else:
            assert server["type"] == "streamable-http"
            assert server["url"] == compat[name]["url"]
    skills = list((source / "skills").glob("*/SKILL.md"))
    assert skills
    for entry in skills:
        text = entry.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        frontmatter = text.split("---", 2)[1]
        assert re.search(r"^name: " + re.escape(entry.parent.name) + r"$", frontmatter, re.M)
        assert re.search(r"^description: .+", frontmatter, re.M)
        for ref in re.findall(r"\]\(([^)]+)\)", text):
            if "://" in ref or ref.startswith("#"):
                continue
            target = (entry.parent / ref.split("#")[0]).resolve()
            assert target.is_relative_to(entry.parent.resolve()) and target.is_file(), ref
    return main


def public_files(directory, suffixes):
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError("Symlinks are not allowed in plugin packages")
        if path.is_file() and path.suffix in suffixes:
            yield path


if __name__ == "__main__":
    import sys

    check(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1])
    print("Plugin identity, configuration and Skill references: PASS")
