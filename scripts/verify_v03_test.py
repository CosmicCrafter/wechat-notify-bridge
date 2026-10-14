"""Exercise the loopback test server through real HTTP, without printing secrets."""

import hashlib
import json
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".private/test-v03"
BASE = "http://127.0.0.1:19865"


def checked(response):
    response.raise_for_status()
    return response.json()


def main():
    access = json.loads((PRIVATE / "local-access.json").read_text(encoding="utf-8"))
    with httpx.Client(base_url=BASE, timeout=30) as client:
        # Historical local credentials are used only to prove that the removed path stays closed.
        legacy = {"Authorization": "Bearer " + access.get("legacy_admin_key", "removed-admin-key")}
        assert client.get("/admin/api/clients", headers=legacy).status_code == 401
        assert client.post("/admin/api/auth/setup", headers=legacy, json={}).status_code == 404
        origin = {"Origin": BASE, "X-Admin-Request": "1"}
        login = checked(
            client.post(
                "/admin/api/auth/login",
                headers=origin,
                json={"username": access["username"], "password": access["password"]},
            )
        )
        admin = {**origin, "X-Admin-CSRF": login["csrf"]}
        assert client.get("/admin/api/account").json()["legacy_enabled"] is False
        assert (
            client.post(
                "/admin/api/account/legacy-key", headers=admin, json={"enabled": True}
            ).status_code
            == 404
        )
        credentials = json.loads((PRIVATE / "browser-app.json").read_text(encoding="utf-8"))
        caller = {"Authorization": "Bearer " + credentials["api_key"]}
        status = checked(client.get("/api/status", headers=caller))
        chats = status["conversations"]
        assert chats, "First create an isolated application and admin conversation in the UI."
        cid = chats[-1]["id"]
        incoming = checked(
            client.get("/api/inbox", headers=caller, params={"conversation_id": cid})
        )["messages"]
        for item in incoming:
            claim = hashlib.sha256(("claim:" + str(item["id"])).encode()).hexdigest()
            checked(
                client.post(
                    "/api/inbox/" + str(item["id"]) + "/claim",
                    headers=caller,
                    json={"request_id": claim},
                )
            )
            checked(
                client.post(
                    "/api/inbox/" + str(item["id"]) + "/report",
                    headers=caller,
                    json={
                        "claim_id": claim,
                        "request_id": hashlib.sha256(
                            ("report:" + str(item["id"])).encode()
                        ).hexdigest(),
                        "status": "completed",
                        "result": "隔离 HTTP 测试应用已核对并报告完成。",
                    },
                )
            )
        sent = checked(
            client.post(
                "/api/messages",
                headers=caller,
                json={
                    "text": "## 应用回复\n\n核对完成。此回复由原应用通过 HTTP API 发出。",
                    "dedup_key": "v03-smoke-reply-" + cid,
                    "conversation_id": cid,
                    "bot_id": "default",
                },
            )
        )
        assert sent["status"] == "api_accepted" and sent["phone_delivery"] == "unconfirmed"
        for marker, expected in [
            ("reject", "api_rejected"),
            ("timeout", "unconfirmed_do_not_retry"),
        ]:
            failed = checked(
                client.post(
                    "/api/messages",
                    headers=caller,
                    json={
                        "text": "[test:" + marker + "] 隔离失败场景",
                        "dedup_key": "v03-" + marker + "-" + cid,
                        "conversation_id": cid,
                        "bot_id": "default",
                    },
                )
            )
            assert failed["status"] == expected
        task = checked(
            client.post(
                "/api/task-cards",
                headers=caller,
                json={
                    "title": "补充验收编号",
                    "prompt": "输入一个编号，支持保留前导零。",
                    "mode": "input",
                    "options": [],
                    "dedup_key": "v03-task-" + cid,
                    "conversation_id": cid,
                    "bot_id": "default",
                },
            )
        )
        phone = checked(client.post("/admin/api/chat/login-code", headers=admin, json={}))
        current = checked(
            client.get("/api/conversations/" + cid + "/tasks/" + task["task"]["id"], headers=caller)
        )
        if current["task"]["status"] in ("answered", "processing"):
            checked(
                client.post(
                    "/api/conversations/" + cid + "/tasks/" + task["task"]["id"] + "/state",
                    headers=caller,
                    json={"status": "completed", "result": "隔离应用已收到答复并完成任务。"},
                )
            )
        context = {
            "conversation_id": cid,
            "task_id": task["task"]["id"],
            "message_id": sent["message_id"],
            "phone_code": phone["code"],
        }
        (PRIVATE / "acceptance-context.json").write_text(
            json.dumps(context, indent=2), encoding="utf-8"
        )
        print(
            "PASS: original application read, explicit claim, report, response, task, rejected/unknown delivery. Platforms simulated; phone login code remains private."
        )


if __name__ == "__main__":
    main()
