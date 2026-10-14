"""Safe, actionable API errors shared by remote and local MCP transports."""

import json

import httpx

SEND_PATHS = {"/api/messages", "/api/notifications", "/api/task-cards"}
DETAILS = {
    "urgent_not_authorized": "Urgent delivery requires explicit owner authorization. Do not switch bots to bypass it.",
    "urgent_rate_limited": "Urgent delivery is rate limited. Wait and keep the event dedup key; do not fan out.",
    "receiver_required": "This protected conversation needs an independently paired private receiver file. A shared app Key is insufficient.",
    "receiver_expired": "Ask the owner to renew the receiver binding; never borrow another conversation capability.",
    "inbox_claim_expired": "The lease expired. Reclaim before work and use the new generation; do not report with a stale claim.",
    "inbox_already_claimed": "This item already has another explicit claim. Read its processing state; do not pretend it was claimed here.",
    "inbox_claim_required": "Explicitly claim the assigned inbox item before reporting processing.",
    "inbox_processing_final": "The item has a final report; it cannot be downgraded or overwritten.",
    "delivery_retry_unsafe": "Do not resend an unknown or accepted delivery. Only recorded Feishu preparation failures support explicit same-request retry.",
    "client_receive_unavailable": "The application has no valid receiving credential; restore its Key or independent OAuth grant.",
    "bot_access_denied": "This key is not granted the selected bot. Ask the owner to change its grants in Admin; never bypass the scope.",
    "bot_required": "Read getCallerIdentity.bots and specify one authorized bot_id. No message was sent; do not broadcast.",
    "bot_disabled": "The selected bot is disabled. Ask the owner to enable it; never switch bots to retry without authorization.",
    "bot_platform_conflict": "The supplied bot_id and channel refer to different platforms. Use the original authorized bot and correct the filter.",
    "bot_not_found": "Check the bot_id returned by getCallerIdentity; do not guess IDs.",
    "task_not_found": "Check the original task_id and conversation_id; never guess a task by title.",
    "task_state_conflict": "Read getTaskCard first. Update only the current task state; terminal states cannot reopen.",
    "task_expired": "The pending card expired. Create a new, clearly scoped decision only if the task still needs it.",
    "task_already_answered": "The owner already submitted a decision; read the saved answer instead of changing it.",
    "conversation_closed": "The conversation is archived. Restore the same ID only when the user resumes it.",
    "conversation_name_conflict": "An active conversation already has this name. Ask which conversation should stay active before resolving the conflict; do not switch IDs.",
    "conversation_not_found": "Check the registered conversation ID and current client identity. Do not guess another ID.",
    "conversation_required": "Register this chat and pass its conversation_id.",
    "wechat_not_bound": "The owner must pair WeChat in the administrator page.",
    "feishu_not_enabled": "The owner must configure and enable Feishu in Admin. Do not switch channels to resend without authorization.",
    "image_not_found": "The attachment is unavailable. Do not claim to have seen it.",
    "invalid_client_key": "Reconnect OAuth or update the private local configuration; never paste credentials into chat.",
    "dedup_key already belongs to different content": "Keep the original conversation, dedup_key and payload. Do not change the key to resend.",
}


def api_error(response, path):
    """Expose only allowlisted error codes, never raw bodies or echoed inputs."""
    status = response.status_code
    try:
        body = response.json()
        detail = body.get("detail") if isinstance(body, dict) else None
    except ValueError:
        detail = None
    code = detail if isinstance(detail, str) and detail in DETAILS else f"http_{status}"
    advice = DETAILS.get(code)
    if advice is None:
        advice = {
            401: "Reconnect OAuth or update the private local configuration; never paste credentials into chat.",
            403: "This identity lacks access. Do not switch to another client to bypass it.",
            404: "Check the resource ID and endpoint for this client.",
            409: "The operation conflicts with current state. Check identity and conversation state.",
            422: "Check the tool input schema and correct invalid fields.",
            429: "The service is rate limited. Wait before another request.",
        }.get(status, "The API operation failed. Check service availability.")
    return failure(code, advice, path, status)


def failure(code, advice, path, status=None):
    # A failed read is not an uncertain send. A send may have crossed the network
    # before a proxy/network error; never encourage a blind retry.
    data = {
        "code": code,
        "message": advice,
        "operation": "send" if path in SEND_PATHS else "api",
        "automatic_retry": False,
    }
    if status is not None:
        data["http_status"] = status
    if path in SEND_PATHS:
        data["delivery"] = "unconfirmed"
        data["next_action"] = (
            "Query getDeliveryStatus with the original bot_id, conversation_id and dedup_key before deciding whether to retry."
        )
    return ValueError(json.dumps(data, ensure_ascii=False))


async def request_json(client, url, path, *, headers, payload=None, params=None):
    try:
        response = await client.request(
            "POST" if payload is not None else "GET",
            url,
            headers=headers,
            json=payload,
            params=params,
        )
    except httpx.HTTPError:
        raise failure(
            "network_error", "The API request could not be completed. Check the connection.", path
        ) from None
    if not 200 <= response.status_code < 300:
        raise api_error(response, path) from None
    try:
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("Expected an object")
        return value
    except ValueError:
        raise failure(
            "invalid_response", "The service returned an invalid API response.", path
        ) from None
