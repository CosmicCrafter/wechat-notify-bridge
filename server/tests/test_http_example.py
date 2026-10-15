"""Run the shipped CLI using private JSON or legacy environment, without platform traffic."""

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

EXAMPLE = Path(__file__).resolve().parents[2] / "examples/python/notify_bridge.py"


@pytest.mark.parametrize("mode", ["config_identity", "config_dry_run", "environment"])
def test_cli_private_config_and_legacy_environment(tmp_path, mode):
    key = secrets.token_urlsafe(32)
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, value):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def do_GET(self):
            assert self.headers["Authorization"] == "Bearer " + key
            calls.append(("GET", self.path, None))
            self.respond(dict(client_id="cli-app", caller="example", bot_ids=["test"], default_bot_id="test"))

        def do_POST(self):
            assert self.headers["Authorization"] == "Bearer " + key
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(("POST", self.path, body))
            if self.path == "/api/conversations":
                self.respond(dict(id="cli-chat", reply_tag="[example]"))
            else:
                assert self.path == "/api/messages" and body["dry_run"] is True
                self.respond(dict(status="dry_run_ready"))

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    config = dict(base_url=f"http://127.0.0.1:{http.server_port}", api_key=key, default_bot_id="test")
    path = tmp_path / "client.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    command = [sys.executable, str(EXAMPLE)]
    env = {k:v for k,v in os.environ.items() if not k.startswith("NOTIFY_")}
    env["NO_PROXY"] = "127.0.0.1"
    if mode.startswith("config"):
        command += ["--config", str(path)]
        if mode == "config_identity":
            command += ["--identity-only"]
        else:
            command += ["--conversation-key", "stable-job", "--event-id", "stable-event"]
    else:
        env.update(NOTIFY_BASE_URL=config["base_url"], NOTIFY_API_KEY=key, NOTIFY_BOT_ID="test", NOTIFY_CONVERSATION_KEY="stable-job", NOTIFY_EVENT_ID="stable-event")
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8", timeout=15)
    finally:
        http.shutdown()
        http.server_close()
        worker.join(timeout=3)
    assert result.returncode == 0, result.stderr
    assert key not in result.stdout + result.stderr
    if mode == "config_identity":
        assert len(calls) == 1 and calls[0][:2] == ("GET", "/api/status")
    else:
        assert calls[1][2]["conversation_key"] == "stable-job"
        assert calls[2][2]["dedup_key"] == "stable-event"
        assert json.loads(result.stdout)["delivery"]["status"] == "dry_run_ready"


def test_bad_private_file_does_not_echo_content(tmp_path):
    secret = secrets.token_urlsafe(32)
    path = tmp_path / "broken.json"
    path.write_text(secret, encoding="utf-8")
    result = subprocess.run([sys.executable, str(EXAMPLE), "--config", str(path)], capture_output=True, text=True)
    assert result.returncode != 0 and secret not in result.stdout + result.stderr
