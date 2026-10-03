"""Local ClawBot pairing probe. Receives one owner message; sends no chat messages.

Protocol reference: https://github.com/Tencent/openclaw-weixin
Run: uv run --with qrcode==8.2 --with pypng==0.20220715.0 server/scripts/pair_wechat.py
Credentials are encrypted with Windows DPAPI for the current Windows user.
"""

import argparse
import base64
import ctypes
from ctypes import wintypes
import io
import json
import os
from pathlib import Path
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / '.private'
API = 'https://ilinkai.weixin.qq.com'
VERSION = '2.4.9'
BASE_INFO = {'channel_version': VERSION, 'bot_agent': 'CodexWechatProbe/0.1.0'}
PAGE_KEY = secrets.token_urlsafe(24)
LOCK = threading.Lock()
VERIFY_EVENT = threading.Event()
VERIFY_CODE = ''
QR_PNG = b''
STATE = {'phase': 'starting', 'message': '正在获取微信绑定二维码…', 'qr': False}


class Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('This pairing helper requires Windows DPAPI')
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    func = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    func.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                     ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    func.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    if not func(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel.LocalFree(result.pbData)


def save_credentials(value):
    target = PRIVATE / 'wechat-credentials.dpapi'
    encrypted = dpapi(json.dumps(value, ensure_ascii=False).encode('utf-8'))
    temporary = target.with_suffix('.tmp')
    temporary.write_bytes(encrypted)
    temporary.replace(target)


def status(phase, message, qr=False):
    with LOCK:
        STATE.update(phase=phase, message=message, qr=qr)
        (PRIVATE / 'status.json').write_text(json.dumps(STATE, ensure_ascii=False), encoding='utf-8')
    print('STATE=' + phase, flush=True)


def validate_base(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or
            not parsed.hostname.endswith('.weixin.qq.com') or
            parsed.username or parsed.password or parsed.port not in (None, 443) or
            parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Unexpected Weixin API host')
    return value.rstrip('/')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WeixinAPIError(RuntimeError):
    def __init__(self, field, code):
        self.field = field
        self.code = code
        super().__init__('Weixin API rejected request: ' + field + '=' + str(code))


def api(endpoint, data=None, *, base=API, token=None, timeout=35):
    headers = {'iLink-App-Id': 'bot', 'iLink-App-ClientVersion': str((2 << 16) | (4 << 8) | 9)}
    body = None
    if data is not None:
        body = json.dumps(data).encode('utf-8')
        headers.update({'Content-Type': 'application/json', 'AuthorizationType': 'ilink_bot_token',
                        'X-WECHAT-UIN': base64.b64encode(str(secrets.randbits(32)).encode()).decode()})
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(validate_base(base) + '/' + endpoint, data=body, headers=headers)
    with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
        result = json.loads(response.read())
    for key in ('ret', 'errcode'):
        if result.get(key) not in (None, 0):
            raise WeixinAPIError(key, result[key])
    return result


def new_qr():
    global QR_PNG
    import qrcode
    from qrcode.image.pure import PyPNGImage
    result = api('ilink/bot/get_bot_qrcode?bot_type=3', {'local_token_list': []})
    if not result.get('qrcode') or not result.get('qrcode_img_content'):
        raise RuntimeError('Weixin did not return a QR code')
    stream = io.BytesIO()
    qrcode.make(result['qrcode_img_content'], image_factory=PyPNGImage, box_size=7, border=4).save(stream)
    with LOCK:
        QR_PNG = stream.getvalue()
        (PRIVATE / 'pairing.png').write_bytes(QR_PNG)
    status('waiting_scan', '请用 手机微信扫描二维码，并在手机上确认连接。', True)
    return result['qrcode']


def receive_owner_context(credentials):
    status('bound', '微信已绑定。请进入手机的微信 ClawBot 对话，发送一句“测试”。')
    token = credentials['bot_token']
    base = credentials['base_url']
    try:
        api('ilink/bot/msg/notifystart', {'base_info': BASE_INFO}, base=base, token=token)
    except (URLError, TimeoutError, RuntimeError):
        pass
    cursor = ''
    deadline = time.monotonic() + 600
    try:
        while time.monotonic() < deadline:
            try:
                update = api('ilink/bot/getupdates', {'get_updates_buf': cursor, 'base_info': BASE_INFO},
                             base=base, token=token, timeout=40)
            except (URLError, TimeoutError):
                time.sleep(2)
                continue
            if update.get('get_updates_buf'):
                cursor = update['get_updates_buf']
            for message in update.get('msgs', []):
                if (message.get('from_user_id') == credentials['user_id'] and
                        message.get('message_type') == 1 and message.get('context_token')):
                    credentials.update(context_token=message['context_token'],
                                       context_received_at=int(time.time()), get_updates_buf=cursor)
                    save_credentials(credentials)
                    status('ready', '已收到你的微信消息，接收通道验证通过。请回到终端 继续；此程序尚未发送任何微信消息。')
                    return
        status('bound_no_message', '绑定已保存，等待消息超时。请回到终端 继续。')
    finally:
        try:
            api('ilink/bot/msg/notifystop', {'base_info': BASE_INFO}, base=base, token=token, timeout=10)
        except Exception:
            pass


def pair():
    global VERIFY_CODE
    try:
        if (PRIVATE / 'wechat-credentials.dpapi').exists():
            status('existing_credentials', '本机已有绑定凭证，已停止新建绑定。请回到终端 检查现有连接。')
            return
        qr = new_qr()
        base = API
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            query = {'qrcode': qr}
            if VERIFY_CODE:
                query['verify_code'] = VERIFY_CODE
            try:
                result = api('ilink/bot/get_qrcode_status?' + urlencode(query), base=base)
            except (URLError, TimeoutError):
                time.sleep(2)
                continue
            phase = result.get('status')
            if phase == 'confirmed':
                if not all(result.get(k) for k in ('bot_token', 'ilink_bot_id', 'ilink_user_id', 'baseurl')):
                    raise RuntimeError('Incomplete binding response')
                credentials = {'bot_token': result['bot_token'], 'bot_id': result['ilink_bot_id'],
                               'user_id': result['ilink_user_id'], 'base_url': validate_base(result['baseurl']),
                               'bound_at': int(time.time()), 'protocol_reference_version': VERSION}
                save_credentials(credentials)
                receive_owner_context(credentials)
                return
            if phase == 'scaned_but_redirect':
                base = validate_base('https://' + result['redirect_host'])
            elif phase == 'need_verifycode':
                VERIFY_CODE = ''
                VERIFY_EVENT.clear()
                status('need_verifycode', '请将手机微信显示的连接数字输入下方，然后点击“继续连接”。')
                if not VERIFY_EVENT.wait(timeout=max(0, deadline-time.monotonic())):
                    break
            elif phase == 'scaned':
                VERIFY_CODE = ''
                if STATE['phase'] != 'scanned':
                    status('scanned', '已扫描，请在手机微信上完成确认。')
            elif phase == 'expired':
                VERIFY_CODE = ''
                base = API
                qr = new_qr()
            elif phase == 'verify_code_blocked':
                status('blocked', '微信暂时限制了连接验证，请稍后再试。')
                return
            elif phase == 'binded_redirect':
                status('already_bound', '微信提示已有绑定，但本程序没有相应凭证。请回到终端 检查。')
                return
            elif phase not in ('wait', 'scaned_but_redirect'):
                raise RuntimeError('Unknown pairing status')
            time.sleep(1)
        status('timeout', '本次扫码已超时，请回到终端 重新生成连接页。')
    except Exception as exc:
        # Never log response bodies, tokens, user IDs, or verification codes.
        status('error', '连接暂未完成，请回到终端 排查。错误类型：' + type(exc).__name__)


HTML = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>连接微信 ClawBot</title><style>
body{margin:0;background:#f4f7f5;color:#163a2b;font-family:system-ui,"Microsoft YaHei",sans-serif}main{max-width:560px;margin:48px auto;padding:32px;background:white;border:1px solid #dfe9e3;border-radius:20px;box-shadow:0 12px 45px #193a2910}h1{font-size:28px;margin:10px 0 16px}.tag{font-size:13px;color:#35784f}p{line-height:1.8}#qr{display:none;width:min(100%,340px);height:auto;margin:16px auto}#status{padding:14px;background:#edf7f0;border-radius:10px}form{display:none}input,button{font-size:16px;padding:12px;border:1px solid #bcd5c6;border-radius:8px}button{background:#087f4f;color:white;cursor:pointer}small{display:block;color:#658071;line-height:1.8;margin-top:22px}
</style><main><div class="tag">WECHAT NOTIFY BRIDGE · 微信连接验证</div><h1>用手机微信扫码连接</h1><p>打开 手机微信，使用“扫一扫”扫描下方二维码，并确认连接。</p><p id="status">正在准备…</p><img id="qr" alt="微信 ClawBot 绑定二维码"><form id="verify"><p>手机显示的连接数字</p><input id="code" autocomplete="off" inputmode="numeric" maxlength="16" required><button>继续连接</button></form><small>绑定后，在手机的微信 ClawBot 对话里发送一句“测试”。<br>此页面仅在本机运行。绑定凭证加密保存在本机；本次只验证接收通道。</small></main><script>
let busy=false;async function update(){if(busy)return;busy=true;try{const r=await fetch('status',{cache:'no-store'});const s=await r.json();document.querySelector('#status').textContent=s.message;const q=document.querySelector('#qr');q.style.display=s.qr?'block':'none';if(s.qr)q.src='qr.png?t='+Date.now();document.querySelector('#verify').style.display=s.phase==='need_verifycode'?'block':'none'}finally{busy=false}}
document.querySelector('#verify').onsubmit=async e=>{e.preventDefault();const input=document.querySelector('#code');const code=input.value;input.value='';await fetch('verify',{method:'POST',body:new URLSearchParams({code})});await update()};update();setInterval(update,2500);
</script></html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, body, kind='text/html; charset=utf-8', code=200):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'")
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        if self.headers.get('Host') != '127.0.0.1:' + str(self.server.server_port):
            return None
        path = urlsplit(self.path).path
        prefix = '/' + PAGE_KEY + '/'
        return path[len(prefix):] if path.startswith(prefix) else None

    def do_GET(self):
        route = self.route()
        if route == '':
            self.respond(HTML)
        elif route == 'status':
            with LOCK:
                payload = json.dumps(STATE, ensure_ascii=False)
            self.respond(payload, 'application/json; charset=utf-8')
        elif route == 'qr.png':
            with LOCK:
                data = QR_PNG
            self.respond(data, 'image/png')
        else:
            self.respond('Not found', code=404)

    def do_POST(self):
        global VERIFY_CODE
        expected_origin = 'http://127.0.0.1:' + str(self.server.server_port)
        if self.route() != 'verify' or self.headers.get('Origin') != expected_origin:
            return self.respond('Forbidden', code=403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 128:
                raise ValueError()
            values = parse_qs(self.rfile.read(length).decode())
            value = values.get('code', [''])[0]
            if not value.isascii() or not value.isdigit() or not 1 <= len(value) <= 16:
                raise ValueError()
        except (ValueError, UnicodeError):
            return self.respond('Invalid input', code=400)
        if STATE['phase'] != 'need_verifycode':
            return self.respond('No verification pending', code=409)
        VERIFY_CODE = value
        VERIFY_EVENT.set()
        self.respond('{}', 'application/json')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        assert dpapi(dpapi(b'pairing storage check'), decrypt=True) == b'pairing storage check'
        assert validate_base(API) == API
        for bad in ('http://ilinkai.weixin.qq.com', 'https://weixin.qq.com.evil.test', 'https://example.com'):
            try:
                validate_base(bad)
                raise AssertionError('Invalid host accepted')
            except ValueError:
                pass
        print('PASS: DPAPI roundtrip and endpoint validation')
        return
    PRIVATE.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    url = 'http://127.0.0.1:' + str(server.server_port) + '/' + PAGE_KEY + '/'
    (PRIVATE / 'pairing-page.json').write_text(json.dumps({'url': url, 'pid': os.getpid()}), encoding='utf-8')
    print('PAIRING_PAGE=' + url, flush=True)
    threading.Thread(target=pair, daemon=True).start()
    # Bounded helper lifetime; this is not an installed background service.
    timer = threading.Timer(1800, server.shutdown)
    timer.daemon = True
    timer.start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
        timer.cancel()


if __name__ == '__main__':
    main()
