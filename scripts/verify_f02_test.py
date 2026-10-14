"""Real loopback F02 HTTP closure; only the platform-substituted test instance.

Creates a new isolated application and test Bot; does not reuse production data.
Private results stay in ignored .private. No real host or phone delivery claim.
"""

import json
import secrets
import sys
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:19865"
PRIVATE = ROOT / ".private/f02-notification-acceptance"
sys.path.insert(0, str(ROOT / "mcp-plugin/server"))
from receiver_store import ReceiverSession  # noqa: E402


def checked(response):
    if not response.is_success:
        raise RuntimeError("Isolated F02 HTTP failed: " + str(response.status_code))
    return response.json()


def main():
    access = json.loads((ROOT / ".private/test-v03/local-access.json").read_text(encoding="utf-8"))
    PRIVATE.mkdir(parents=True, exist_ok=True)
    suffix = secrets.token_hex(4)
    with httpx.Client(base_url=BASE, timeout=30) as client:
        origin = {"Origin": BASE, "X-Admin-Request": "1"}
        login = checked(
            client.post(
                "/admin/api/auth/login",
                headers=origin,
                json={"username": access["username"], "password": access["password"]},
            )
        )
        admin = {**origin, "X-Admin-CSRF": login["csrf"]}
        environment = checked(client.get("/admin/api/status"))["environment"]
        assert environment["platforms"] == "simulated" and environment["receive_workers"] is False

        def new_bot(name):
            bot = checked(
                client.post(
                    "/admin/api/bots",
                    headers=admin,
                    json={"name": name + suffix, "platform": "feishu"},
                )
            )
            bot_id = bot["id"]
            checked(
                client.post(
                    "/admin/api/bots/" + bot_id + "/feishu",
                    headers=admin,
                    json={
                        "enabled": True,
                        "app_id": "cli_f02" + secrets.token_hex(6),
                        "owner_open_id": "ou_f02" + suffix,
                        **{
                            f: secrets.token_urlsafe(24)
                            for f in ("app_secret", "verification_token", "encrypt_key")
                        },
                    },
                )
            )
            return bot_id

        a, b = new_bot("F02普通A-"), new_bot("F02紧急B-")
        app = checked(
            client.post(
                "/admin/api/clients",
                headers=admin,
                json={
                    "name": "F02验收-" + suffix,
                    "key_format": "nb",
                    "bot_ids": ["default", a, b],
                    "default_bot_id": a,
                },
            )
        )
        app_id, key = app["client"]["id"], app["api_key"]
        auth = {"Authorization": "Bearer " + key}
        first = {
            "client_id": app_id,
            "name": "管理员先创建",
            "text": "首条消息可靠保存，等待正确绑定。",
            "request_id": secrets.token_hex(16),
            "receiver_mode": "protected",
        }
        pending = checked(client.post("/admin/api/conversations", headers=admin, json=first))
        cid = pending["conversation"]["id"]
        assert (
            checked(client.post("/admin/api/conversations", headers=admin, json=first))[
                "conversation"
            ]["id"]
            == cid
        )
        assert (
            client.get("/api/inbox", headers=auth, params={"conversation_id": cid}).status_code
            == 403
        )
        pairing = checked(
            client.post(
                "/admin/api/conversations/" + cid + "/receiver/pair",
                headers=admin,
                json={"role": "primary", "host_type": "http", "label": "F02受控测试接收器"},
            )
        )
        setup = checked(
            client.post(
                "/api/receivers/exchange",
                headers=auth,
                json={"pairing_code": pairing["pairing_code"]},
            )
        )
        scoped = {**auth, "X-Notify-Receiver": setup["receiver_token"]}
        checked(
            client.post(
                "/api/receivers/verify", headers=scoped, json={"challenge": setup["challenge"]}
            )
        )
        peer = checked(
            client.post(
                "/api/conversations",
                headers=auth,
                json={
                    "conversation_key": "f02-peer-" + suffix,
                    "name": "另一接收上下文",
                    "receiver_mode": "protected",
                    "host_type": "http",
                },
            )
        )
        rp = {**auth, "X-Notify-Receiver": peer["receiver_setup"]["receiver_token"]}
        checked(
            client.post(
                "/api/receivers/verify",
                headers=rp,
                json={"challenge": peer["receiver_setup"]["challenge"]},
            )
        )
        assert (
            client.get("/api/inbox", headers=rp, params={"conversation_id": cid}).status_code == 403
        )
        policy = {
            "default_bot": a,
            "urgent_bot": b,
            "urgent_enabled": True,
            "interval_seconds": 60,
            "fallback_bot": None,
        }
        checked(
            client.post(
                "/admin/api/clients/" + app_id + "/notification-policy", headers=admin, json=policy
            )
        )

        def send(name, text, **extra):
            return client.post(
                "/api/messages",
                headers=scoped,
                json={
                    "conversation_id": cid,
                    "dedup_key": "f02-" + suffix + "-" + name,
                    "text": text,
                    **extra,
                },
            )

        assert checked(send("ordinary", "普通提醒走飞书 A。"))["bot_id"] == a
        assert checked(send("urgent", "获授权紧急提醒走 B。", level="urgent"))["bot_id"] == b
        assert checked(send("urgent", "获授权紧急提醒走 B。", level="urgent"))["duplicate"]
        assert send("limited", "另一个紧急事件", level="urgent").status_code == 429
        checked(
            client.post(
                "/admin/api/conversations/" + cid + "/mute", headers=admin, json={"muted": True}
            )
        )
        assert checked(send("quiet", "静音仍保存正文。"))["status"] == "muted"
        checked(
            client.post(
                "/admin/api/conversations/" + cid + "/mute", headers=admin, json={"muted": False}
            )
        )
        assert checked(send("quiet", "静音仍保存正文。"))["duplicate"]
        failure = checked(send("timeout", "[test:timeout] 结果未知保持原目标。"))
        assert failure["status"] == "unconfirmed_do_not_retry"
        receipt = checked(
            client.get(
                "/api/deliveries",
                headers=scoped,
                params={"conversation_id": cid, "dedup_key": "f02-" + suffix + "-timeout"},
            )
        )
        assert receipt["status"] == failure["status"]
        code = checked(client.post("/admin/api/chat/login-code", headers=admin, json={}))["code"]
        phone = {"Origin": BASE, "X-Chat-Request": "1"}
        checked(client.post("/chat/api/login", headers=phone, json={"code": code}))
        checked(
            client.post(
                "/chat/api/conversations/" + cid + "/messages",
                headers=phone,
                json={"text": "手机端 HTTP 答复，同一账本。", "request_id": secrets.token_hex(16)},
            )
        )
        messages = checked(
            client.get("/api/inbox", headers=scoped, params={"conversation_id": cid})
        )["messages"]
        assert len(messages) == 2
        for item in messages:
            claim = checked(
                client.post(
                    "/api/inbox/" + str(item["id"]) + "/claim",
                    headers=scoped,
                    json={"request_id": secrets.token_hex(16)},
                )
            )
            checked(
                client.post(
                    "/api/inbox/" + str(item["id"]) + "/report",
                    headers=scoped,
                    json={
                        "request_id": secrets.token_hex(16),
                        "claim_id": claim["processing"]["claim_id"],
                        "generation": claim["processing"]["generation"],
                        "status": "completed",
                        "result": "受控接收器核对并报告完成。",
                    },
                )
            )
        checked(send("answer", "原应用收到手机答复，并在原会话回复。"))
        ah = checked(client.get("/admin/api/conversations/" + cid + "/messages"))
        ph = checked(client.get("/chat/api/conversations/" + cid + "/messages"))
        assert [m["id"] for m in ah["messages"]] == [m["id"] for m in ph["messages"]]

        def save_private(name, data):
            ReceiverSession(
                {"base_url": BASE, "api_key": key, "receiver_file": str(PRIVATE / name)}
            ).save(data)

        save_private(
            "client.json",
            {
                "base_url": BASE,
                "api_key": key,
                "receiver_file": str(PRIVATE / "receiver.json"),
                "use_notification_policy": True,
            },
        )
        save_private(
            "receiver.json",
            {"base_url": BASE, "conversation_id": cid, "receiver_token": setup["receiver_token"]},
        )
        context = {
            "client_id": app_id,
            "conversation_id": cid,
            "peer_id": peer["id"],
            "urgent_bot": b,
            "default_bot": a,
            "suffix": suffix,
            "http_closure": True,
            "real_platform": False,
            "real_host": False,
        }
        (PRIVATE / "result.json").write_text(json.dumps(context), encoding="utf-8")
        print(json.dumps(context, ensure_ascii=False))


if __name__ == "__main__":
    main()
