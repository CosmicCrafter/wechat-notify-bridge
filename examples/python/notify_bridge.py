"""Small synchronous HTTP client example. No dependencies or automatic retries."""

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class NotifyBridge:
    def __init__(self, base_url, api_key, timeout=25, *, receiver_token=None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.receiver_token = receiver_token

    def request(self, method, path, *, body=None, query=None):
        url = self.base_url + path
        if query:
            url += "?" + urlencode(query)
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"}
        if self.receiver_token:
            headers["X-Notify-Receiver"] = self.receiver_token
        req = Request(
            url,
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with urlopen(req, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            # No key or request body in exceptions. Transport errors propagate: do not auto-resend.
            raise RuntimeError("Notify Bridge HTTP " + str(exc.code)) from None

    def identity(self):
        return self.request("GET", "/api/status")

    def register(self, conversation_key, name):
        return self.request(
            "POST", "/api/conversations", body={"conversation_key": conversation_key, "name": name}
        )

    def send(self, conversation_id, bot_id, text, dedup_key, *, dry_run=True):
        return self.request(
            "POST",
            "/api/messages",
            body=dict(
                conversation_id=conversation_id,
                bot_id=bot_id,
                text=text,
                dedup_key=dedup_key,
                dry_run=dry_run,
            ),
        )

    def receipt(self, conversation_id, bot_id, dedup_key):
        return self.request(
            "GET",
            "/api/deliveries",
            query=dict(conversation_id=conversation_id, bot_id=bot_id, dedup_key=dedup_key),
        )

    def inbox(self, conversation_id, after_id=0):
        return self.request(
            "GET",
            "/api/inbox",
            query=dict(conversation_id=conversation_id, after_id=after_id, limit=20),
        )

    def history(self, conversation_id, **cursor):
        return self.request(
            "GET", "/api/conversations/" + conversation_id + "/history", query=cursor
        )

    def claim(self, inbox_id, request_id, *, lease_seconds=120):
        return self.request(
            "POST",
            "/api/inbox/" + str(inbox_id) + "/claim",
            body={"request_id": request_id, "lease_seconds": lease_seconds},
        )

    def renew(self, inbox_id, claim_id, generation, *, lease_seconds=120):
        return self.request(
            "POST",
            "/api/inbox/" + str(inbox_id) + "/renew",
            body=dict(claim_id=claim_id, generation=generation, lease_seconds=lease_seconds),
        )

    def report(self, inbox_id, claim_id, request_id, status, result="", *, generation=None):
        return self.request(
            "POST",
            "/api/inbox/" + str(inbox_id) + "/report",
            body=dict(
                claim_id=claim_id,
                request_id=request_id,
                status=status,
                result=result,
                **({"generation": generation} if generation is not None else {}),
            ),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, help="Private client.json; never prints its contents"
    )
    parser.add_argument(
        "--identity-only", action="store_true", help="Only read identity; no registration or send"
    )
    parser.add_argument(
        "--conversation-key", help="Stable logical conversation ID (or NOTIFY_CONVERSATION_KEY)"
    )
    parser.add_argument("--event-id", help="Stable event dedup key (or NOTIFY_EVENT_ID)")
    parser.add_argument(
        "--send", action="store_true", help="Actually send one message; default is dry-run"
    )
    args = parser.parse_args()
    if args.config:
        try:
            config = json.loads(args.config.read_text(encoding="utf-8-sig"))
            if not isinstance(config, dict):
                raise ValueError()
        except (OSError, ValueError):
            parser.error("Cannot read private JSON configuration; contents were not printed")
    else:
        config = dict(
            base_url=os.environ.get("NOTIFY_BASE_URL"),
            api_key=os.environ.get("NOTIFY_API_KEY"),
            default_bot_id=os.environ.get("NOTIFY_BOT_ID"),
        )
    if (
        not all(
            isinstance(config.get(k), str) and config[k].strip() for k in ("base_url", "api_key")
        )
        or config["api_key"] == "CONFIGURE_SEPARATELY"
    ):
        parser.error("Configure base_url and api_key in a private file or environment")
    client = NotifyBridge(
        config["base_url"], config["api_key"], receiver_token=config.get("receiver_token")
    )
    bot_id = config.get("default_bot_id")
    identity = client.identity()
    if args.identity_only:
        print(
            json.dumps(
                {k: identity.get(k) for k in ("caller", "client_id", "bot_ids", "default_bot_id")},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if bot_id not in identity["bot_ids"]:
        raise SystemExit("Bot is not authorized for this client Key")
    conversation_key = args.conversation_key or os.environ.get("NOTIFY_CONVERSATION_KEY")
    event_id = args.event_id or os.environ.get("NOTIFY_EVENT_ID")
    if not conversation_key or not event_id:
        parser.error(
            "Set a stable --conversation-key and --event-id (or their NOTIFY_* environment variables)"
        )
    chat = client.register(conversation_key, "接入测试")
    result = client.send(chat["id"], bot_id, "通知桥接入测试", event_id, dry_run=not args.send)
    print(
        json.dumps(
            dict(
                caller=identity["caller"],
                conversation_id=chat["id"],
                reply_tag=chat["reply_tag"],
                delivery=result,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.send:
        print(
            json.dumps(
                client.inbox(chat["id"], int(os.environ.get("NOTIFY_AFTER_ID", "0"))),
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
