"""Documentation facts and copyable examples must survive actual contract drift."""

import copy
import io
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from fastapi.testclient import TestClient
from wechat_bridge.app import create_app

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from build_api_reference import build, render

sys.path.insert(0, str(ROOT / "server/scripts"))
from build_developer_kit import validate_diagram


def test_reference_follows_openapi_defaults_limits_and_missing_response_models(tmp_path):
    schema = json.loads((ROOT / "server/openapi.json").read_text(encoding="utf-8"))
    changed = copy.deepcopy(schema)
    changed["components"]["schemas"]["Message"]["properties"]["text"]["maxLength"] = 23456
    changed["components"]["schemas"]["Message"]["properties"]["dry_run"]["default"] = True
    text = render(changed)
    assert "23456" in text and "未声明完整 JSON 模型" in text
    assert "可选 / true" in text
    for path, item in schema["paths"].items():
        for method in {"get", "post", "put", "patch", "delete"} & item.keys():
            assert f"### {method.upper()} {path}" in text
    (tmp_path / "server").mkdir()
    (tmp_path / "server/openapi.json").write_text(json.dumps(schema), encoding="utf-8")
    build(tmp_path)
    (tmp_path / "server/openapi.json").write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="Stale OpenAPI Markdown"):
        build(tmp_path, check=True)


@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        "<foreignObject/>",
        '<image href="https://example.invalid/x"/>',
        '<rect onload="alert(1)"/>',
        '<rect fill="url(https://example.invalid/x)"/>',
        '<g xml:base="//example.invalid/"/>',
        '<text xmlns="http://www.w3.org/1999/xhtml">foreign</text>',
    ],
)
def test_passive_diagrams_reject_active_or_external_content(payload):
    with pytest.raises(ValueError):
        validate_diagram('<svg xmlns="http://www.w3.org/2000/svg">' + payload + "</svg>")


def test_public_skill_and_diagrams_are_real_allowlisted_sources():
    client = TestClient(create_app(run_workers=False))
    assert (
        client.get("/docs/skill/SKILL.md").content
        == (ROOT / "mcp-plugin/skills/wechat-notify/SKILL.md").read_bytes()
    )
    llms = client.get("/docs/llms.txt").text
    assert "skill/SKILL.md" in llms and "tutorials/FIRST-INTEGRATION.md" in llms
    for name in ["receiver-boundary.svg", "inbox-lease.svg", "onboarding-sequence.svg"]:
        response = client.get("/docs/assets/" + name)
        assert response.status_code == 200 and response.headers["content-type"].startswith(
            "image/svg+xml"
        )
        assert response.content == (ROOT / "docs/assets" / name).read_bytes()
    # The dimensions prevent late-loading figures from shifting a requested heading.
    page = client.get("/docs/explanations/RELIABLE-CONVERSATIONS.html").text
    assert 'width="720" height="375" loading="lazy"' in page
    assert validate_diagram((ROOT / "docs/assets/inbox-lease.svg").read_text(encoding="utf-8")) == {
        "width": 720,
        "height": 375,
    }
    assert client.get("/docs/assets/private.svg").status_code == 404
    client.close()


@pytest.mark.parametrize("receipt", [False, True])
def test_copyable_http_query_example_never_sends_or_prints_credentials(tmp_path, receipt):
    markdown = (ROOT / "docs/integration/HTTP.md").read_text(encoding="utf-8")
    code = re.search(r"```python\n(.*?)```", markdown, re.S)[1]
    script = tmp_path / "read_replies.py"
    script.write_text(code, encoding="utf-8")
    (tmp_path / "notify_bridge.py").write_bytes(
        (ROOT / "examples/python/notify_bridge.py").read_bytes()
    )
    key = secrets.token_urlsafe(30)
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            assert self.headers["Authorization"] == "Bearer " + key
            calls.append(("GET", self.path))
            body = (
                {"status": "not_found", "message_id": None}
                if receipt
                else {
                    "messages": [{"id": 9, "text": "private-body-do-not-print"}],
                    "next_after_id": 9,
                }
            )
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    config = tmp_path / "private.json"
    config.write_text(
        json.dumps(
            dict(
                base_url=f"http://127.0.0.1:{server.server_port}",
                api_key=key,
                default_bot_id="test",
            )
        ),
        encoding="utf-8",
    )
    args = [sys.executable, str(script), "--config", str(config), "--conversation-id", "test-chat"]
    if receipt:
        args += ["--event-id", "original-event"]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=15)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
    assert r.returncode == 0, r.stderr
    assert key not in r.stdout + r.stderr and "private-body-do-not-print" not in r.stdout + r.stderr
    assert len(calls) == 1 and calls[0][0] == "GET"
    assert ("/api/deliveries?" if receipt else "/api/inbox?") in calls[0][1]
