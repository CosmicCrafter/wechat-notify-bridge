"""Bounded, administrator-initiated QR pairing. QR/token contents never enter logs.

Protocol: https://github.com/Tencent/openclaw-weixin/blob/main/docs/protocol_zh_CN.md
"""
import asyncio
import base64
import io
import secrets
import time

import httpx
import qrcode
from qrcode.image.pure import PyPNGImage

from wechat_bridge.wechat.protocol import BridgeError
from wechat_bridge.wechat.protocol import response_status
from wechat_bridge.wechat.protocol import validate_base

API = 'https://ilinkai.weixin.qq.com'
MESSAGES = {
    'idle': '点击“生成二维码”，开始绑定微信。',
    'starting': '正在向微信获取二维码…',
    'waiting_scan': '请用手机微信扫一扫，并在手机上确认连接。',
    'scanned': '已扫描，请在手机微信上完成确认。',
    'need_verifycode': '请输入手机微信显示的连接数字。',
    'verifying': '正在验证连接数字…',
    'binding': '正在保存绑定并启动接收服务…',
    'bound': '绑定已保存。请在手机的 ClawBot 对话发送一句“测试”。',
    'expired': '二维码已过期，请重新生成。',
    'timeout': '本次连接已超时，请重新生成二维码。',
    'blocked': '微信暂时限制了连接验证，请稍后再试。',
    'already_bound': '微信提示已有绑定，请检查原来的连接，或稍后重新扫码。',
    'owner_mismatch': '扫码账号与原绑定不一致，请使用原来的微信账号。',
    'cancelled': '已取消本次扫码。',
    'error': '暂时无法完成连接，请检查服务器网络后重试。',
}


class Pairing:
    def __init__(self, bridge, *, run_workers=True, transport=None, lifetime=600, poll_delay=1):
        self.bridge = bridge
        self.run_workers = run_workers
        self.http = httpx.AsyncClient(timeout=35, follow_redirects=False, transport=transport)
        self.lifetime, self.poll_delay = lifetime, poll_delay
        self.lock = asyncio.Lock()
        self.task = None
        self.phase = 'idle'
        self.session_id = None
        self.expires_at = None
        self.png = b''
        self.qr_version = 0
        self.code = None
        self.last_start = None

    def snapshot(self):
        return dict(phase=self.phase, message=MESSAGES[self.phase], session_id=self.session_id,
                    expires_at=self.expires_at, qr_available=bool(self.png), qr_version=self.qr_version,
                    active=bool(self.task and not self.task.done()))

    def phase_is(self, phase):
        self.phase = phase
        if phase not in ('waiting_scan', 'scanned'):
            self.png = b''

    async def start(self, replace=False):
        async with self.lock:
            if self.task and not self.task.done():
                return self.snapshot()
            if self.bridge.store.account() and not replace:
                raise BridgeError(409, 'confirm_rebind_required')
            if self.last_start is not None and time.monotonic() - self.last_start < 2:
                raise BridgeError(429, 'pairing_retry_later')
            self.last_start = time.monotonic()
            self.session_id = secrets.token_urlsafe(18)
            self.expires_at = time.time() + self.lifetime
            self.phase_is('starting')
            self.task = asyncio.create_task(self.run())
            return self.snapshot()

    async def verify(self, session_id, code):
        async with self.lock:
            if (session_id != self.session_id or self.phase != 'need_verifycode'
                    or not self.code or self.code.done()):
                raise BridgeError(409, 'no_verification_pending')
            self.phase_is('verifying')
            self.code.set_result(code)
            return self.snapshot()

    async def cancel(self, session_id):
        async with self.lock:
            if session_id != self.session_id or self.phase == 'binding':
                raise BridgeError(409, 'pairing_session_changed')
            if self.task and not self.task.done():
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
                self.phase_is('cancelled')
            return self.snapshot()

    async def request(self, endpoint, *, base=API, payload=None, params=None):
        headers = {'iLink-App-Id': 'bot', 'iLink-App-ClientVersion': str((2 << 16) | (4 << 8) | 9)}
        url = validate_base(base) + '/' + endpoint
        if payload is None:
            response = await self.http.get(url, params=params, headers=headers)
        else:
            headers.update(AuthorizationType='ilink_bot_token',
                           **{'X-WECHAT-UIN': base64.b64encode(str(secrets.randbits(32)).encode()).decode()})
            response = await self.http.post(url, params=params, json=payload, headers=headers)
        response.raise_for_status()
        value = response.json()
        response_status(value)
        return value

    async def new_qr(self):
        self.phase_is('starting')
        value = await self.request('ilink/bot/get_bot_qrcode', params={'bot_type': '3'},
                                   payload={'local_token_list': []})
        for field in ('qrcode', 'qrcode_img_content'):
            if not isinstance(value.get(field), str) or not 0 < len(value[field]) <= 2048:
                raise ValueError('Invalid QR response')
        stream = io.BytesIO()
        qrcode.make(value['qrcode_img_content'], image_factory=PyPNGImage, box_size=7, border=4).save(stream)
        self.png = stream.getvalue()
        self.qr_version += 1
        self.phase_is('waiting_scan')
        return value['qrcode']

    async def run(self):
        try:
            async with asyncio.timeout(self.lifetime):
                account = await self.poll()
            if account:
                # The QR deadline must not interrupt a confirmed credential handover.
                self.phase_is('binding')
                await self.bridge.bind_account(account, self.run_workers)
                self.phase_is('bound')
        except TimeoutError:
            self.phase_is('timeout')
        except asyncio.CancelledError:
            self.phase_is('cancelled')
            raise
        except BridgeError as exc:
            self.phase_is('owner_mismatch' if exc.reason == 'owner_mismatch' else 'error')
        except Exception:
            # No upstream error text/URL/response bodies: they can contain credentials.
            self.phase_is('error')
        finally:
            self.code = None

    async def poll(self):
        qr, base, verify_code = await self.new_qr(), API, ''
        refreshes = 0
        while True:
            params = {'qrcode': qr}
            if verify_code:
                params['verify_code'] = verify_code
            try:
                value = await self.request('ilink/bot/get_qrcode_status', base=base, params=params)
            except httpx.RequestError:
                await asyncio.sleep(max(1, self.poll_delay))
                continue
            phase = value.get('status')
            if phase == 'confirmed':
                fields = ('bot_token', 'ilink_bot_id', 'ilink_user_id', 'baseurl')
                if any(not isinstance(value.get(k), str) or not value[k] for k in fields):
                    raise ValueError('Incomplete binding response')
                account = dict(bot_token=value['bot_token'], bot_id=value['ilink_bot_id'],
                               user_id=value['ilink_user_id'], base_url=validate_base(value['baseurl']),
                               bound_at=time.time(), protocol_reference_version='2.4.9')
                return account
            if phase == 'scaned_but_redirect':
                base = validate_base('https://' + value['redirect_host'])
            elif phase == 'need_verifycode':
                self.code = asyncio.get_running_loop().create_future()
                self.phase_is('need_verifycode')
                verify_code = await self.code
            elif phase == 'scaned':
                verify_code = ''
                self.phase_is('scanned')
            elif phase == 'expired':
                refreshes += 1
                if refreshes > 3:
                    self.phase_is('expired')
                    return
                qr, base, verify_code = await self.new_qr(), API, ''
            elif phase in ('verify_code_blocked', 'binded_redirect'):
                self.phase_is('blocked' if phase == 'verify_code_blocked' else 'already_bound')
                return
            elif phase != 'wait':
                raise ValueError('Unexpected pairing state')
            await asyncio.sleep(self.poll_delay)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.http.aclose()
