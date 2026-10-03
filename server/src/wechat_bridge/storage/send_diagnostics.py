"""Encrypted upstream evidence and non-sensitive delivery diagnostics."""
import json
import re
import time

from wechat_bridge.wechat.protocol import ACCEPTED


SUMMARIES = {
    'wechat_rate_limited': '微信明确返回发送限流；具体额度和恢复时间未由接口提供。',
    'wechat_context_rejected': '微信明确报告回复上下文无效或过期。',
    'wechat_session_expired': '微信报告账号会话失效，需要重新绑定。',
    'wechat_prepare_failed': '微信返回 prepare failed；不能据此区分额度、上下文或其他准备失败。',
    'wechat_rejected': '微信拒绝发送，错误码本身不能确定原因。',
    'http_error': '上游 HTTP 请求失败，未自动重发。',
    'network_timeout': '请求超时，实际是否投递尚未确认。',
    'network_error': '网络请求失败，实际是否投递尚未确认。',
    'invalid_response': '上游响应无法解析，实际是否投递尚未确认。',
    'internal_error': '发送处理中出现错误，实际是否投递尚未确认。',
}


def wechat_category(code, message):
    text = message.lower() if isinstance(message, str) else ''
    if str(code) == '-14':
        return 'wechat_session_expired'
    if any(term in text for term in ('rate limited', 'rate limit', 'too many requests', '限流')):
        return 'wechat_rate_limited'
    if ('context' in text and any(term in text for term in ('expired', 'invalid', 'missing'))):
        return 'wechat_context_rejected'
    if 'prepare failed' in text:
        return 'wechat_prepare_failed'
    return 'wechat_rejected'


def redact_error_message(message, account):
    if not isinstance(message, str):
        return None
    for field in ('bot_token', 'context_token'):
        secret = account.get(field)
        if isinstance(secret, str) and secret:
            message = message.replace(secret, '[redacted]')
    # Command replies can issue numeric API keys; never retain one echoed by an
    # upstream error after the temporary key reply itself has been purged.
    return re.sub(r'(?<!\d)\d{40}(?!\d)', '[redacted]', message)[:2000]


class SendDiagnostics:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.execute('CREATE TABLE IF NOT EXISTS send_diagnostics '
                        '(outgoing_key TEXT PRIMARY KEY, encrypted BLOB NOT NULL)')
        self.db.execute('CREATE INDEX IF NOT EXISTS outgoing_attempted_at ON outgoing(attempted_at)')

    def context(self, now=None):
        now = time.time() if now is None else now
        account = self.store.account() or {}
        received = account.get('context_received_at')
        received = received if isinstance(received, (int, float)) and received > 0 else None
        count = self.db.execute('SELECT count(*) FROM outgoing WHERE attempted_at>=? AND status IN (?,?,?)',
                                (received, *sorted(ACCEPTED))).fetchone()[0] if received else None
        return {'context_received_at': received,
                'context_age_seconds': round(max(0, now - received), 1) if received else None,
                'accepted_sends_since_context': count,
                'quota_warning': ('自最近微信上下文以来，本地已记录 ' + str(count) +
                                  ' 条接口接受的推送，可能接近或达到主动推送限额。请在微信 ClawBot 发一条消息；'
                                  '网页回复与心跳不会刷新微信上下文。此计数不是微信剩余额度。')
                                  if count is not None and count >= 8 else None}

    def save(self, key, value):
        encrypted = self.store.cipher.encrypt(json.dumps(value, ensure_ascii=False).encode())
        self.db.execute('INSERT OR REPLACE INTO send_diagnostics VALUES (?,?)', (key, encrypted))

    def public(self, key):
        row = self.db.execute('SELECT encrypted FROM send_diagnostics WHERE outgoing_key=?', (key,)).fetchone()
        if not row:
            return None
        value = json.loads(self.store.cipher.decrypt(row[0]))
        # Raw errmsg may contain upstream data. Keep it encrypted and never expose
        # arbitrary upstream text, credentials, message bodies or context tokens.
        names = ('context_received_at', 'context_age_seconds', 'accepted_sends_since_context',
                 'request_characters', 'request_utf8_bytes', 'http_status', 'upstream_ret',
                 'upstream_errcode', 'upstream_error_field', 'duration_ms', 'error_category')
        result = {name: value.get(name) for name in names}
        result['error_summary'] = SUMMARIES.get(value.get('error_category'))
        return result
