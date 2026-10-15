"""Anonymous documentation is usable without exposing management, credentials or messages."""

import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Mount
from wechat_bridge.app import create_app
from test_portal import portal, ADMIN

ROOT = Path(__file__).resolve().parents[2]


def test_public_documents_need_neither_login_nor_database():
    # No lifespan, database or administrator has been initialized for this app.
    client = TestClient(create_app(run_workers=False))
    try:
        redirect = client.get("/docs", follow_redirects=False)
        assert redirect.status_code == 307 and redirect.headers["location"] == "docs/"
        for path, content_type in [
            ("/docs/", "text/html"),
            ("/docs/index.md", "text/markdown"),
            ("/docs/integration/HTTP.html", "text/html"),
            ("/docs/integration/CLIENT-SETUP.md", "text/markdown"),
            ("/docs/integration/RECEIVERS.md", "text/markdown"),
            ("/docs/openapi.json", "application/json"),
            ("/docs/examples/python/notify_bridge.py", "text/plain"),
            ("/docs/download.zip", "application/zip"),
        ]:
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 200, path
            assert response.headers["content-type"].startswith(content_type)
            assert "location" not in response.headers and "set-cookie" not in response.headers
        page = client.get("/docs/").text
        assert "getCallerIdentity" in page and "公开开发文档" in page
        assert "<script" not in page and 'href="openapi.json"' in page
        schema = client.get("/docs/openapi.json").json()
        assert not any(p.startswith(("/admin", "/chat")) for p in schema["paths"])
        assert "X-Notify-Receiver" in json.dumps(schema)
    finally:
        client.close()


def test_anonymous_documentation_does_not_unlock_private_interfaces(portal):
    store, client, auth, *_ = portal
    client.cookies.clear()
    before = store.db.total_changes
    assert client.get("/docs/").status_code == 200
    for path in (
        "/admin/api/clients",
        "/admin/api/bots",
        "/admin/api/conversations",
        "/admin/api/developer-docs",
        "/admin/api/developer-kit",
        "/admin/api/account",
        "/admin/api/onboarding",
        "/api/inbox",
        "/api/status",
        "/openapi.json",
        "/chat/api/conversations",
    ):
        assert client.get(path, follow_redirects=False).status_code == 401, path
    assert (
        client.post("/admin/api/onboarding/package", json={"kind": "configured"}).status_code == 401
    )
    for path in (
        "/docs/onboarding-template.zip",
        "/docs/developer-docs.json",
        "/docs/.private/client.json",
        "/docs/%2e%2e/server/.env",
        "/docs/admin/api/clients",
        "/docs/data/wechat.sqlite3",
        "/docs/secrets/encryption.key",
    ):
        assert client.get(path).status_code in (401, 404), path
    assert store.db.total_changes == before
    # Existing internal reading still uses a genuine management session.
    internal = client.get("/admin/api/developer-docs", headers=ADMIN).json()
    assert client.get("/docs/RELEASE.json").json() == internal["_release"]
    assert client.get("/docs/openapi.json").content == (ROOT / "server/openapi.json").read_bytes()


def test_public_download_and_example_are_usable_anonymously(tmp_path):
    client = TestClient(create_app(run_workers=False))
    try:
        response = client.get("/docs/download.zip")
        assert "attachment" in response.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            assert "server/openapi.json" in z.namelist()
            assert "DEPLOYMENT.json" not in z.namelist()
            assert not any(
                ".private" in n or n.endswith((".env", ".db", ".key")) for n in z.namelist()
            )
        example = tmp_path / "notify_bridge.py"
        example.write_bytes(client.get("/docs/examples/python/notify_bridge.py").content)
        assert example.read_bytes() == (ROOT / "examples/python/notify_bridge.py").read_bytes()
        result = subprocess.run(
            [sys.executable, str(example), "--help"], capture_output=True, text=True, timeout=10
        )
        assert (
            result.returncode == 0
            and "--config" in result.stdout
            and "--identity-only" in result.stdout
        )
    finally:
        client.close()


def test_public_links_work_behind_existing_bridge_prefix():
    proxy = Starlette(routes=[Mount("/bridge", app=create_app(run_workers=False))])
    client = TestClient(proxy)
    try:
        response = client.get("/bridge/docs")
        assert response.status_code == 200 and response.url.path == "/bridge/docs/"
        assert client.get("/bridge/docs/integration/HTTP.html").status_code == 200
        assert client.get("/bridge/docs/integration/RECEIVERS.md").status_code == 200
        assert client.get("/bridge/docs/download.zip").status_code == 200
    finally:
        client.close()


@pytest.mark.skipif(not shutil.which("node"), reason="Node only needed to build public HTML")
def test_static_renderer_escapes_html_and_rejects_active_urls():
    data = dict(
        pages=[
            dict(
                path="index.html",
                title="test",
                markdown_path="index.md",
                markdown='# Test\n<script>alert(1)</script>\n\n[bad](javascript:alert(1))\n\n```python\nprint("ok")\n```',
            )
        ],
        release=dict(server_version="test", plugin_version="test"),
        theme="",
    )
    r = subprocess.run(
        [shutil.which("node"), str(ROOT / "frontend/render-docs.mjs"), str(ROOT / "frontend")],
        input=json.dumps(data),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    html = json.loads(r.stdout)["index.html"]
    assert "<script" not in html and "&lt;script&gt;" in html
    assert 'href="javascript:' not in html and 'class="language-python"' in html
