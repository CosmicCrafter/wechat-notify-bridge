"""Safe, actionable API errors shared by remote and local MCP transports."""
import json

import httpx

SEND_PATHS = {'/api/messages', '/api/notifications', '/api/task-cards'}
DETAILS = {
    'task_not_found': 'Check the original task_id and conversation_id; never guess a task by title.',
    'task_state_conflict': 'Read getTaskCard first. Update only the current task state; terminal states cannot reopen.',
    'task_expired': 'The pending card expired. Create a new, clearly scoped decision only if the task still needs it.',
    'task_already_answered': 'The owner already submitted a decision; read the saved answer instead of changing it.',
    'conversation_closed': 'The conversation is archived. Restore the same ID only when the user resumes it.',
    'conversation_name_conflict': 'An active conversation already has this name. Ask which conversation should stay active before resolving the conflict; do not switch IDs.',
    'conversation_not_found': 'Check the registered conversation ID and current client identity. Do not guess another ID.',
    'conversation_required': 'Register this chat and pass its conversation_id.',
    'wechat_not_bound': 'The owner must pair WeChat in the administrator page.',
    'image_not_found': 'The attachment is unavailable. Do not claim to have seen it.',
    'invalid_client_key': 'Reconnect OAuth or update the private local configuration; never paste credentials into chat.',
    'dedup_key already belongs to different content': 'Keep the original conversation, dedup_key and payload. Do not change the key to resend.',
}


def api_error(response, path):
    """Expose only allowlisted error codes, never raw bodies or echoed inputs."""
    status = response.status_code
    try:
        body = response.json()
        detail = body.get('detail') if isinstance(body, dict) else None
    except ValueError:
        detail = None
    code = detail if isinstance(detail, str) and detail in DETAILS else f'http_{status}'
    advice = DETAILS.get(code)
    if advice is None:
        advice = {
            401: 'Reconnect OAuth or update the private local configuration; never paste credentials into chat.',
            403: 'This identity lacks access. Do not switch to another client to bypass it.',
            404: 'Check the resource ID and endpoint for this client.',
            409: 'The operation conflicts with current state. Check identity and conversation state.',
            422: 'Check the tool input schema and correct invalid fields.',
            429: 'The service is rate limited. Wait before another request.',
        }.get(status, 'The API operation failed. Check service availability.')
    return failure(code, advice, path, status)


def failure(code, advice, path, status=None):
    # A failed read is not an uncertain send. A send may have crossed the network
    # before a proxy/network error; never encourage a blind retry.
    data = {'code': code, 'message': advice, 'operation': 'send' if path in SEND_PATHS else 'api',
            'automatic_retry': False}
    if status is not None:
        data['http_status'] = status
    if path in SEND_PATHS:
        data['delivery'] = 'unconfirmed'
        data['next_action'] = 'Query getDeliveryStatus with the original conversation_id and dedup_key before deciding whether to retry.'
    return ValueError(json.dumps(data, ensure_ascii=False))


async def request_json(client, url, path, *, headers, payload=None, params=None):
    try:
        response = await client.request('POST' if payload is not None else 'GET', url,
                                        headers=headers, json=payload, params=params)
    except httpx.HTTPError:
        raise failure('network_error', 'The API request could not be completed. Check the connection.', path) from None
    if not 200 <= response.status_code < 300:
        raise api_error(response, path) from None
    try:
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError('Expected an object')
        return value
    except ValueError:
        raise failure('invalid_response', 'The service returned an invalid API response.', path) from None
