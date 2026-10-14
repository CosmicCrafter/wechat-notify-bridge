"""Host/HTTP packages reuse application identity and keep secrets in one private file."""

import io
import json
import zipfile
import tomllib
from test_portal import portal, ADMIN


def test_three_export_targets_share_existing_application_without_rotation(portal):
    store, client, *_ = portal
    app = client.post(
        "/admin/api/clients",
        headers=ADMIN,
        json={
            "name": "export-flow",
            "key_format": "nb",
            "bot_ids": ["default"],
            "default_bot_id": "default",
        },
    ).json()
    id = app["client"]["id"]
    key = app["api_key"]
    before = dict(store.clients.get(id))
    credentials = store.clients.credentials.list(id)
    for target in ("codex", "claude", "http"):
        r = client.post(
            "/admin/api/onboarding/package",
            headers=ADMIN,
            json={
                "target": target,
                "transport": "local",
                "credential_mode": "existing",
                "client_id": id,
                "bot_id": "default",
                "api_key": key,
                "private_ack": True,
            },
        )
        assert r.status_code == 200
        with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
            private = next(name for name in entries if name.endswith("/.private/client.json"))
            assert json.loads(entries[private])["api_key"] == key
            assert sum(key.encode() in body for body in entries.values()) == 1
            if target == "http":
                assert "notify-bridge-http/openapi.json" in entries
                assert not any(name.endswith(("mcp.json", "toolkit.py")) for name in entries)
            else:
                toml = next(
                    body
                    for name, body in entries.items()
                    if name.endswith("/codex-config.toml.example")
                )
                assert tomllib.loads(toml.decode())["mcp_servers"]["notify_bridge"]["command"]
                claude = next(
                    body
                    for name, body in entries.items()
                    if name.endswith("/claude-mcp.json.example")
                )
                assert json.loads(claude)["mcpServers"]["notify-bridge"]["type"] == "stdio"
        assert (
            dict(store.clients.get(id)) == before
            and store.clients.credentials.list(id) == credentials
        )
    assert len(store.clients.list()) == 3
