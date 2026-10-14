"""Optional operator-scoped receiver file. Never expose its capabilities to MCP results."""

import json
import os
from pathlib import Path
import secrets
import subprocess
from api_errors import request_json


class ReceiverSession:
    def __init__(self, config):
        name = config.get("receiver_file") or os.environ.get("WECHAT_NOTIFY_RECEIVER_FILE")
        self.path = Path(name).expanduser().absolute() if name else None
        self.value = {}
        self.base = config["base_url"]
        self.key = config["api_key"]

    def save(self, value):
        if self.path is None:
            raise ValueError("host_receiver_storage_unverified")
        if self.path.exists() and self.path.is_symlink():
            raise ValueError("Unsafe receiver file")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_name(self.path.name + "." + secrets.token_hex(8) + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False)
            if os.name == "nt":
                who = os.environ.get("USERDOMAIN", "") + "\\" + os.environ["USERNAME"]
                subprocess.run(
                    ["icacls.exe", str(tmp), "/inheritance:r", "/grant:r", who + ":F"],
                    check=True,
                    capture_output=True,
                )
            tmp.replace(self.path)
        finally:
            if tmp.exists():
                tmp.unlink()
        self.value = value

    @property
    def headers(self):
        return {
            "Authorization": "Bearer " + self.key,
            **(
                {"X-Notify-Receiver": self.value["receiver_token"]}
                if self.value.get("receiver_token")
                else {}
            ),
        }

    async def prepare(self, client):
        if self.path and self.path.exists():
            if self.path.is_symlink():
                raise ValueError("Unsafe receiver file")
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or (
                value.get("base_url") and value["base_url"].rstrip("/") != self.base
            ):
                raise ValueError("Receiver file belongs to another service")
            if "api_key" in value or not (value.get("receiver_token") or value.get("pairing_code")):
                raise ValueError(
                    "Receiver and application credentials require separate files; existing file was not changed"
                )
            self.value = value
            if value.get("pairing_code"):
                setup = await request_json(
                    client,
                    self.base + "/api/receivers/exchange",
                    "/api/receivers/exchange",
                    headers={"Authorization": "Bearer " + self.key},
                    payload={"pairing_code": value["pairing_code"]},
                )
                self.save({**setup, "base_url": self.base})
            await self.verify(client)

    async def verify(self, client):
        if self.value.get("challenge"):
            result = await request_json(
                client,
                self.base + "/api/receivers/verify",
                "/api/receivers/verify",
                headers=self.headers,
                payload={"challenge": self.value["challenge"]},
            )
            value = {k: v for k, v in self.value.items() if k != "challenge"}
            value["receiver"] = result["receiver"]
            self.save(value)

    async def finish(self, client, result):
        if isinstance(result, dict) and "receiver_setup" in result:
            setup = result["receiver_setup"]
            self.save({**setup, "base_url": self.base})
            await self.verify(client)
            result = {k: v for k, v in result.items() if k != "receiver_setup"}
            result.update(
                receiver=self.value.get("receiver"),
                receiver_storage="operator_scoped_private_file",
                host_identity="unverified",
            )
        return result
