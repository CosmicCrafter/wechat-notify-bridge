"""Shared URL, cookie and packaged asset configuration."""
import os
from pathlib import Path
from urllib.parse import urlencode, urlsplit

SESSION_SECONDS = 30 * 86400
COOKIE = 'wechat_chat_session'
WEB = Path(__file__).parent / 'web'


def public_base():
    base = os.environ.get('WECHAT_PUBLIC_BASE_URL', '').rstrip('/')
    p = urlsplit(base)
    if not base:
        return ''
    if (p.scheme != 'https' and not (p.scheme == 'http' and p.hostname in ('localhost', '127.0.0.1'))
            or not p.hostname or p.username or p.password or p.query or p.fragment
            or any(c in base for c in '\n\r()<>')):
        raise ValueError('Invalid WECHAT_PUBLIC_BASE_URL')
    return base


def chat_url(conversation_id=None, message_id=None):
    base = public_base()
    if not base:
        return None
    params = {}
    if conversation_id: params['c'] = conversation_id
    if message_id: params['m'] = message_id
    return base + '/chat/' + ('?' + urlencode(params) if params else '')


