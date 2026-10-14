"""Private receiver storage stays outside model results and never overwrites an app Key."""

import asyncio
import json
from pathlib import Path
import secrets
import sys
import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mcp-plugin/server"))
from receiver_store import ReceiverSession


def test_receiver_setup_is_persisted_verified_and_removed_from_mcp_result(tmp_path):
    token = "nrb_" + secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    cid = secrets.token_hex(16)
    path = tmp_path / "private" / "receiver.json"
    receiver = ReceiverSession(
        {
            "base_url": "http://127.0.0.1:19865",
            "api_key": secrets.token_urlsafe(32),
            "receiver_file": str(path),
        }
    )

    def transport(request):
        assert request.headers["X-Notify-Receiver"] == token
        assert json.loads(request.content)["challenge"] == nonce
        return httpx.Response(
            200, json={"receiver": {"status": "active", "host_identity": "unverified"}}
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            result = await receiver.finish(
                client,
                {
                    "id": cid,
                    "receiver_setup": {
                        "conversation_id": cid,
                        "receiver_token": token,
                        "challenge": nonce,
                    },
                },
            )
            leaked = any(secret in json.dumps(result) for secret in (token, nonce))
            assert not leaked, "Private receiver material must never enter a tool result"
            assert result["host_identity"] == "unverified"

    asyncio.run(run())
    stored = json.loads(path.read_text())
    assert (
        stored["conversation_id"] == cid and "challenge" not in stored and "api_key" not in stored
    )


def test_wrong_service_and_application_config_are_rejected_without_overwrite(tmp_path):
    target = tmp_path / "existing.json"
    key = secrets.token_urlsafe(32)
    target.write_text(json.dumps({"api_key": key, "base_url": "http://127.0.0.1:19865"}))
    before = target.read_bytes()
    receiver = ReceiverSession(
        {"base_url": "http://127.0.0.1:19865", "api_key": key, "receiver_file": str(target)}
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: pytest.fail("No network call allowed"))
        ) as client:
            with pytest.raises(ValueError):
                await receiver.prepare(client)

    asyncio.run(run())
    assert target.read_bytes() == before
