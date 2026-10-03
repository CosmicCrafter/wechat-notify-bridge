"""WeChat protocol validation and response semantics."""
from urllib.parse import urlsplit

INTERVAL = 12 * 60 * 60
BASE_INFO = {'channel_version': '2.4.9', 'bot_agent': 'WeChatNotifyService/1.0.0'}
ACCEPTED = {'api_accepted', 'no_error_reported', 'phone_confirmed'}


def send_recovery_hint(status, error_code):
    if status == 'api_rejected' and str(error_code) == '-2':
        return ('微信拒绝发送。请直接在微信 ClawBot 聊天框发送一条新消息，再检查发送连接；'
                '网页回复不会更新微信上下文。错误码 -2 本身不能确定具体原因。')
    if status == 'api_rejected' and str(error_code) == '-14':
        return '微信报告会话失效，请使用原账号重新扫码绑定。'
    if status == 'api_rejected':
        return '微信拒绝发送，请检查连接和错误码；未自动重发。'
    if status in ('attempting', 'unconfirmed_do_not_retry'):
        return '发送结果尚未确认，请先检查回执与实际收件，不要重复发送。'
    return None


class BridgeError(Exception):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason
        super().__init__(reason)


class WeChatError(Exception):
    def __init__(self, field, code):
        self.field = field
        self.code = code if isinstance(code, int) else 'unknown'
        super().__init__('WeChat rejected the request')


def validate_base(value):
    p = urlsplit(value)
    if (p.scheme != 'https' or not p.hostname or not p.hostname.endswith('.weixin.qq.com')
            or p.username or p.password or p.port not in (None, 443)
            or p.path not in ('', '/') or p.query or p.fragment):
        raise ValueError('Invalid WeChat host')
    return value.rstrip('/')


def response_status(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid WeChat response')
    for field in ('ret', 'errcode'):
        if value.get(field) not in (None, 0):
            raise WeChatError(field, value[field])
    return 'api_accepted' if value.get('ret') == 0 else 'no_error_reported'


