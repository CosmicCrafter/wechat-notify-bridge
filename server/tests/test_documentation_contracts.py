"""Deliberately corrupt shipped contracts and ensure the existing CI gate rejects them."""

import copy
import io
import json
from pathlib import Path
import secrets
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from check_documentation import check_archive, check_links, check_schema, check_html_links
from wechat_bridge.services.onboarding import package, template_files


@pytest.mark.parametrize(
    "damage",
    [
        "missing_header",
        "missing_explanation",
        "required_for_legacy",
        "wrong_version",
        "missing_bearer",
    ],
)
def test_openapi_guard_fails_for_broken_receiver_contract(damage):
    schema = json.loads((ROOT / "server/openapi.json").read_text(encoding="utf-8"))
    check_schema(schema, "1.17.1")
    operation = schema["paths"]["/api/messages"]["post"]
    header = next(p for p in operation["parameters"] if p["name"] == "X-Notify-Receiver")
    if damage == "missing_header":
        operation["parameters"].remove(header)
    elif damage == "missing_explanation":
        header["description"] = "Receiver"
    elif damage == "required_for_legacy":
        header["required"] = True
    elif damage == "missing_bearer":
        operation.pop("security")
    else:
        schema["info"]["version"] = "0.0.0"
    with pytest.raises(ValueError):
        check_schema(schema, "1.17.1")


@pytest.mark.parametrize(
    "damage",
    [
        "missing_file",
        "wrong_version",
        "wrong_manifest",
        "broken_link",
        "missing_receiver_contract",
        "public_credential",
        "legacy_public_credential",
        "wrong_scope",
    ],
)
def test_download_guard_rejects_damaged_http_and_mcp_packages(damage):
    flavor = "http" if damage == "missing_receiver_contract" else "local"
    blob = package(
        template_files(),
        kind="template",
        transport="local",
        target="http" if flavor == "http" else "codex",
        base_url="https://notify.example.com/bridge",
        mcp_url="https://notify.example.com/wechat/mcp",
    )
    check_archive(blob, flavor, server_version="1.17.1", plugin_version="1.11.0")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        entries = {n: z.read(n) for n in z.namelist()}
    root = "notify-bridge-http/" if flavor == "http" else "wechat-notify-local/"
    if damage == "missing_file":
        del entries[root + "server/receiver_store.py"]
    elif damage == "wrong_version":
        value = json.loads(entries[root + "RELEASE.json"])
        value["plugin_version"] = "1.10.0"
        entries[root + "RELEASE.json"] = json.dumps(value).encode()
    elif damage == "wrong_manifest":
        value = json.loads(entries[root + "plugin.json"])
        value["version"] = "1.10.0"
        entries[root + "plugin.json"] = json.dumps(value).encode()
    elif damage == "missing_receiver_contract":
        value = json.loads(entries[root + "openapi.json"])
        value["paths"]["/api/messages"]["post"]["parameters"] = []
        entries[root + "openapi.json"] = json.dumps(value).encode()
    elif damage == "public_credential":
        entries[root + "INSTALL.md"] += ("\nnb_" + secrets.token_urlsafe(32)).encode()
    elif damage == "legacy_public_credential":
        entries[root + "INSTALL.md"] += (
            "\n" + "".join(secrets.choice("0123456789") for _ in range(40))
        ).encode()
    elif damage == "wrong_scope":
        value = json.loads(entries[root + "RELEASE.json"])
        value["fingerprint_scope"] = "developer-docs"
        entries[root + "RELEASE.json"] = json.dumps(value).encode()
    else:
        entries[root + "INSTALL.md"] += b"\n[missing](missing.md)\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, content in entries.items():
            z.writestr(name, content)
    with pytest.raises(ValueError):
        check_archive(buffer.getvalue(), flavor, server_version="1.17.1", plugin_version="1.11.0")


def test_links_check_real_headings_and_missing_targets():
    entries = {"guide.md": "[接收](api.md#接收授权)".encode(), "api.md": "# 接收授权\n".encode()}
    check_links(entries)
    for target in ("api.md#旧标题", "missing.md"):
        broken = dict(entries, **{"guide.md": ("[broken](" + target + ")").encode()})
        with pytest.raises(ValueError):
            check_links(broken)


@pytest.mark.parametrize("href", ["missing.html", "api.html#missing", "javascript:alert(1)"])
def test_public_html_guard_rejects_broken_or_active_links(href):
    entries = {
        "index.html": ('<a href="' + href + '">link</a>').encode(),
        "api.html": b'<h1 id="current">API</h1>',
    }
    with pytest.raises(ValueError):
        check_html_links(entries)
