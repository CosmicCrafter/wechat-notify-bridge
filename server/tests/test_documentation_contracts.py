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
from check_documentation import (
    check_archive,
    check_links,
    check_schema,
    check_html_links,
    check_onboarding_guidance,
)
from wechat_bridge.services.onboarding import package, template_files
from wechat_bridge import __version__


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
    check_schema(schema, __version__)
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
        check_schema(schema, __version__)


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
    check_archive(blob, flavor, server_version=__version__, plugin_version="1.11.0")
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
        check_archive(
            buffer.getvalue(), flavor, server_version=__version__, plugin_version="1.11.0"
        )


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


@pytest.mark.parametrize("damage", ["menu", "mcp_url", "feishu"])
def test_onboarding_guidance_rejects_old_menu_or_missing_entry(tmp_path, damage):
    paths = (
        "README.md",
        "docs/integration/CLIENT-SETUP.md",
        "docs/server/新增飞书Bot操作指南.md",
        "frontend/src/admin/pages/Developer.vue",
        "mcp-plugin/README.md",
    )
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((ROOT / name).read_text(encoding="utf-8"), encoding="utf-8")
    check_onboarding_guidance(tmp_path)
    target = tmp_path / (paths[3] if damage == "menu" else paths[0])
    text = target.read_text(encoding="utf-8")
    if damage == "menu":
        text = text.replace("接入应用", "接入密钥")
    else:
        text = text.replace("mcp_url" if damage == "mcp_url" else "系统设置→手机端登录", "omitted")
    target.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        check_onboarding_guidance(tmp_path)
