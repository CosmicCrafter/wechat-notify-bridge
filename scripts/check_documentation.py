"""Check effective documentation and public delivery contracts without writing files."""

import ast
import io
import json
from pathlib import Path
import posixpath
import re
import sys
import tomllib
from urllib.parse import unquote
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def heading_ids(text):
    counts, ids = {}, set()
    # Headings inside fenced examples are not document anchors.
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.M):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        ids.add(slug + ("-" + str(count) if count else ""))
    return ids


def check_links(entries, *, check_anchors=True, documents=None):
    for name, content in entries.items():
        if not name.endswith(".md") or documents is not None and name not in documents:
            continue
        for href in re.findall(r"\]\(([^)]+)\)", content.decode("utf-8")):
            if re.match(r"\w+:", href):
                continue
            path, _, anchor = unquote(href).partition("#")
            target = (
                posixpath.normpath(posixpath.join(posixpath.dirname(name), path)) if path else name
            )
            if target not in entries and not any(
                n.startswith(target.rstrip("/") + "/") for n in entries
            ):
                raise ValueError("Missing documentation target: " + name + " -> " + href)
            if (
                check_anchors
                and anchor
                and target.endswith(".md")
                and anchor not in heading_ids(entries[target].decode("utf-8"))
            ):
                raise ValueError("Missing documentation anchor: " + name + " -> " + href)


def check_schema(schema, version):
    if schema["info"]["version"] != version:
        raise ValueError("OpenAPI version differs from server version")
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            if method not in ("get", "post", "put", "patch", "delete") or not operation.get(
                "security"
            ):
                continue
            header = next(
                (
                    p
                    for p in operation.get("parameters", [])
                    if p.get("name") == "X-Notify-Receiver"
                ),
                None,
            )
            if not header or header.get("required") is not False:
                raise ValueError("Missing conditional receiver authorization: " + path)
            description = header.get("description", "").lower()
            if not all(
                word in description for word in ("protected", "legacy", "bearer", "possession")
            ):
                raise ValueError("Incomplete receiver authorization explanation: " + path)


def check_archive(blob, flavor, *, server_version, plugin_version):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(
            n.startswith("/") or ".." in n.split("/") or "\\" in n for n in names
        ):
            raise ValueError("Unsafe or duplicate package members")
        entries = {n: archive.read(n) for n in names}
    root = {"docs": "", "http": "notify-bridge-http/", "rules": "notify-bridge-rules/"}.get(
        flavor, "wechat-notify-local/"
    )
    required = ["RELEASE.json"]
    if flavor == "docs":
        required += [
            "START-HERE.md",
            "server/openapi.json",
            "examples/python/notify_bridge.py",
            "docs/integration/README.md",
        ]
        if any(n.startswith(("docs/history/", "docs/product-", "docs/f02/")) for n in names):
            raise ValueError("Historical material entered client documentation package")
    elif flavor == "http":
        required += [
            "README.md",
            "notify_bridge.py",
            "openapi.json",
            "F02-RECEIVERS.md",
            ".private/client.json",
        ]
    else:
        required += [
            "INSTALL.md",
            "AI-HOSTS.md",
            "F02-RECEIVERS.md",
            "skills/wechat-notify/SKILL.md",
        ]
        if flavor != "rules":
            required += ["plugin.json", ".codex-plugin/plugin.json", "mcp.json", ".mcp.json"]
        if flavor == "local":
            required += [
                "requirements.txt",
                "server/http_bridge.py",
                "server/receiver_store.py",
                "server/toolkit.py",
                "tools/configure_client.py",
            ]
        if flavor in ("remote", "rules") and any(
            n.startswith(root + p)
            for p in ("server/", "tools/", ".private/", "requirements.txt")
            for n in names
        ):
            raise ValueError("Local runtime or private data entered remote/rules package")
    if any(root + n not in entries for n in required):
        raise ValueError("Missing required package file: " + flavor)
    release = json.loads(entries[root + "RELEASE.json"])
    scopes = {
        "docs": ("developer-docs",),
        "http": ("onboarding-template",),
        "rules": ("onboarding-template",),
        "local": ("onboarding-template", "standalone-local"),
        "remote": ("onboarding-template", "standalone-remote"),
    }
    if release.get("fingerprint_scope") not in scopes[flavor]:
        raise ValueError("Missing public fingerprint scope")
    if (release["server_version"], release["plugin_version"]) != (server_version, plugin_version):
        raise ValueError("Incorrect package release version")
    if flavor in ("local", "remote"):
        for name in ("plugin.json", ".codex-plugin/plugin.json"):
            if json.loads(entries[root + name])["version"] != plugin_version:
                raise ValueError("Incorrect packaged plugin version")
    if flavor in ("docs", "http"):
        check_schema(
            json.loads(
                entries[root + ("server/openapi.json" if flavor == "docs" else "openapi.json")]
            ),
            server_version,
        )
    secret = re.compile(
        rb"\b(?:nb_|nrb_|nrp_|sk-)[A-Za-z0-9_-]{24,}|\b[0-9]{40}\b|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----"
    )
    for name, value in entries.items():
        if (
            Path(name).suffix in (".key", ".pem", ".sqlite3", ".db", ".enc")
            or Path(name).name == ".env"
        ):
            raise ValueError("Runtime secret/data file entered package: " + name)
        if ".private" not in name.split("/") and secret.search(value):
            raise ValueError("Credential-shaped value in public package member: " + name)
    check_links(entries)
    return len(entries)


def check(root=ROOT):
    sys.path[:0] = [str(root / "server/src"), str(root / "mcp-plugin/tools")]
    from wechat_bridge import __version__
    from wechat_bridge.app import create_app
    from wechat_bridge.api.schemas import Message, Notice, TaskCard
    from wechat_bridge.services.onboarding import package, template_files
    from package_checks import check as check_plugin

    plugin = check_plugin(root / "mcp-plugin")
    project = tomllib.loads((root / "server/pyproject.toml").read_text(encoding="utf-8"))
    frontend = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    if project["project"]["version"] != __version__ or frontend["version"] != __version__:
        raise ValueError("Server/project/frontend release versions differ")
    if "插件 " + plugin["version"] not in (root / "mcp-plugin/README.md").read_text(
        encoding="utf-8"
    ):
        raise ValueError("Plugin README release version differs")
    schema = json.loads((root / "server/openapi.json").read_text(encoding="utf-8"))
    check_schema(schema, __version__)
    actual = create_app(run_workers=False).openapi()
    actual.pop("servers", None)
    schema.pop("servers", None)
    if schema != actual:
        raise ValueError("OpenAPI differs from effective routes/models")
    tools = ast.parse((root / "server/src/wechat_bridge/mcp/tools.py").read_text(encoding="utf-8"))
    names = {
        n.name
        for n in ast.walk(tools)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "tool"
            for d in n.decorator_list
        )
    }
    guide = (root / "docs/integration/README.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| (\w+) \| (?:GET|POST) ", guide, re.M))
    if names != documented:
        raise ValueError("MCP/HTTP guide tool inventory differs from registered tools")
    readme = (root / "mcp-plugin/README.md").read_text(encoding="utf-8")
    if "## " + str(len(names)) + " 个工具" not in readme:
        raise ValueError("Plugin README tool count differs")
    paths = {re.sub(r"\{[^}]+\}", "{}", p): set(methods) for p, methods in schema["paths"].items()}
    for method, path in re.findall(r"^\| \w+ \| (GET|POST) ([^ ]+) \|", guide, re.M):
        if method.lower() not in paths.get(re.sub(r"\{[^}]+\}", "{}", path), set()):
            raise ValueError("MCP/HTTP guide points to missing route: " + path)
    api_text = (root / "docs/server/API.md").read_text(encoding="utf-8")
    if "X-Notify-Receiver" not in api_text or "legacy" not in api_text:
        raise ValueError("HTTP guide omits conditional receiver authorization")
    for example in re.findall(r"```json\s*\n(.*?)```", api_text, re.S):
        value = json.loads(example)
        if (
            isinstance(value, dict)
            and "dedup_key" in value
            and any(key in value for key in ("text", "need_user", "prompt"))
        ):
            model = TaskCard if "prompt" in value else Notice if "need_user" in value else Message
            model.model_validate(value)
    template = template_files()
    for kind, transport, target, flavor in [
        ("template", "local", "codex", "local"),
        ("template", "remote", "codex", "remote"),
        ("template", "local", "http", "http"),
        ("rules", "local", "generic", "rules"),
    ]:
        blob = package(
            template,
            kind=kind,
            transport=transport,
            target=target,
            base_url="https://notify.example.com/bridge",
            mcp_url="https://notify.example.com/wechat/mcp",
        )
        check_archive(blob, flavor, server_version=__version__, plugin_version=plugin["version"])
    check_archive(
        (root / "server/src/wechat_bridge/web/admin/developer-kit.zip").read_bytes(),
        "docs",
        server_version=__version__,
        plugin_version=plugin["version"],
    )
    return dict(
        server_version=__version__,
        plugin_version=plugin["version"],
        tools=len(names),
        public_package_types=5,
    )


if __name__ == "__main__":
    print(json.dumps(check(), ensure_ascii=False))
