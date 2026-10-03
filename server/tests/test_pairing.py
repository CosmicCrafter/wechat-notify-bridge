"""Exercise the real web routes, QR state machine and storage with fake WeChat HTTP."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import httpx
import pytest

from wechat_bridge.app import create_app
from wechat_bridge.services.bridge import Bridge
from wechat_bridge.wechat.protocol import BridgeError
from wechat_bridge.wechat.protocol import INTERVAL
from wechat_bridge.storage.database import Store
from wechat_bridge.wechat.pairing import Pairing

ADMIN = {'Authorization': 'Bearer fixture-admin'}
CLIENT = {'Authorization': 'Bearer fixture-client'}


def account(owner='fixture-owner', token='fixture-bot-token'):
    return dict(user_id=owner, bot_id='fixture-bot', bot_token=token,
                base_url='https://ilinkai.weixin.qq.com', bound_at=time.time())


def confirmed(owner='fixture-owner'):
    return dict(status='confirmed', bot_token='fixture-bot-token', ilink_bot_id='fixture-bot',
                ilink_user_id=owner, baseurl='https://ilinkai.weixin.qq.com')


@pytest.fixture
def store(tmp_path):
    key = Fernet.generate_key()
    value = Store(tmp_path / 'state.sqlite3', key)
    value.test_key = key
    yield value
    value.close()


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(.002)


def test_unbound_server_web_auth_is_separate_from_mcp_and_qr_is_private(store):
    async def hold(request):
        await asyncio.sleep(30)
    bridge = Bridge(store, httpx.MockTransport(lambda r: pytest.fail('Unbound bridge must stay offline')))
    pairing = Pairing(bridge, run_workers=False, transport=httpx.MockTransport(hold))
    app = create_app(bridge, {'codex': hashlib.sha256(b'fixture-client').hexdigest()}, False,
                     admin_hash=hashlib.sha256(b'fixture-admin').hexdigest(), pairing=pairing)
    with TestClient(app) as client:
        page = client.get('/admin/')
        assert page.status_code == 200 and '扫码连接' in page.text
        assert page.headers['cache-control'] == 'no-store'
        assert "script-src 'self'" in page.headers['content-security-policy']
        assert client.get('/admin', follow_redirects=False).headers['location'] == 'admin/'
        assert client.get('/admin/app.js').status_code == 200
        assert client.get('/admin/style.css').status_code == 200
        for headers in ({}, CLIENT):
            assert client.get('/admin/api/status', headers=headers).status_code == 401
            assert client.get('/admin/api/pairing/qr?session_id=x', headers=headers).status_code == 401
            assert client.post('/admin/api/pairing/start', headers=headers, json={}).status_code == 401
        assert client.get('/api/status', headers=ADMIN).status_code == 401
        assert client.options('/admin/api/pairing/start', headers={
            'Origin':'https://evil.example', 'Access-Control-Request-Method':'POST',
            'Access-Control-Request-Headers':'Authorization'}).headers.get('access-control-allow-origin') is None
        value = client.get('/admin/api/status', headers=ADMIN).json()
        assert value['service']['connection_status'] == 'unbound'
        assert value['service']['next_heartbeat_at'] is None
        assert client.post('/api/messages', headers=CLIENT, json={'text':'hi','dedup_key':'x'}).status_code == 409
        assert client.get('/api/deliveries?dedup_key=x', headers=CLIENT).json()['status'] == 'not_found'
        first = client.post('/admin/api/pairing/start', headers=ADMIN, json={}).json()
        again = client.post('/admin/api/pairing/start', headers=ADMIN, json={}).json()
        assert first['session_id'] == again['session_id']
        assert client.post('/admin/api/pairing/verify', headers=ADMIN, json={
            'session_id':first['session_id'],'code':'bad'}).status_code == 422
        assert client.post('/admin/api/pairing/cancel', headers=ADMIN,
                           json={'session_id': 'stale'}).status_code == 409
        assert client.post('/admin/api/pairing/cancel', headers=ADMIN,
                           json={'session_id': first['session_id']}).json()['phase'] == 'cancelled'
    asyncio.run(bridge.close())


def test_qr_verification_binding_first_message_and_restart(store, tmp_path):
    qr_calls = []
    phases = iter(['scaned_but_redirect', 'need_verifycode', 'confirmed'])
    def qr_handler(request):
        qr_calls.append(request)
        if request.url.path.endswith('get_bot_qrcode'):
            assert request.method == 'POST'
            assert json.loads(request.content) == {'local_token_list': []}
            assert 'authorization' not in request.headers
            return httpx.Response(200, json={'qrcode':'fixture-qr-token','qrcode_img_content':'fixture-qr-only'})
        assert request.method == 'GET' and 'authorizationtype' not in request.headers
        phase = next(phases)
        if phase == 'scaned_but_redirect':
            return httpx.Response(200, json={'status':phase,'redirect_host':'alternate.weixin.qq.com'})
        assert request.url.host == 'alternate.weixin.qq.com'
        if phase == 'confirmed':
            assert request.url.params['verify_code'] == '123456'
            return httpx.Response(200, json=confirmed())
        return httpx.Response(200, json={'status':phase})
    sent = []
    def bridge_handler(request):
        if request.url.path.endswith('sendmessage'):
            sent.append(request)
        return httpx.Response(200, json={'ret':0})
    async def run():
        bridge = Bridge(store, httpx.MockTransport(bridge_handler))
        pairing = Pairing(bridge, run_workers=False, transport=httpx.MockTransport(qr_handler), poll_delay=.005)
        await pairing.start()
        await until(lambda: pairing.phase == 'waiting_scan')
        assert pairing.png.startswith(b'\x89PNG')
        await until(lambda: pairing.phase == 'need_verifycode')
        assert not pairing.png
        assert all(secret not in json.dumps(pairing.snapshot()) for secret in ('fixture-qr-token','123456','fixture-bot-token'))
        await pairing.verify(pairing.session_id, '123456')
        await pairing.task
        assert pairing.phase == 'bound'
        assert store.status()['connection_status'] == 'waiting_message'
        assert (await bridge.heartbeat_once())['status'] == 'waiting_for_binding_or_message'
        with pytest.raises(BridgeError, match='waiting_for_first_wechat_message'):
            await bridge.send('hi','first','codex')
        now = time.time()
        store.ingest({'msgs':[{'message_id':1,'seq':1,'from_user_id':'fixture-owner',
            'message_type':1,'message_state':2,'context_token':'fixture-context',
            'create_time_ms':int(now*1000),'item_list':[{'type':1,'text_item':{'text':'测试'}}]}]}, now)
        assert store.status()['connection_status'] == 'connected'
        assert store.next_heartbeat() == pytest.approx(now + INTERVAL, abs=.01)
        assert (await bridge.send('ready','dryrun','codex',dry_run=True))['status'] == 'dry_run_ready'
        other = Store(tmp_path/'state.sqlite3', store.test_key)
        try:
            assert other.account()['context_token'] == 'fixture-context'
            assert other.status()['bound'] is True
            assert other.inbox(0,10)[0]['text'] == '测试'
        finally:
            other.close()
        assert sent == []
        raw = store.db.execute('SELECT encrypted FROM account').fetchone()[0]
        assert b'fixture-bot-token' not in raw and b'fixture-context' not in raw
        await pairing.close()
        await bridge.close()
    asyncio.run(run())


@pytest.mark.parametrize('phase,expected', [('verify_code_blocked','blocked'),('binded_redirect','already_bound'),
    ('expired','expired'),('unknown','error'),('unsafe_redirect','error'),('unsafe_base','error'),('foreign_owner','owner_mismatch')])
def test_pairing_failure_preserves_existing_account(store, phase, expected):
    store.bind(account())
    before = store.account()
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path.endswith('get_bot_qrcode'):
            return httpx.Response(200,json={'qrcode':'qr','qrcode_img_content':'test-qr'})
        value = {'status':phase}
        if phase == 'unsafe_redirect':
            value = {'status':'scaned_but_redirect','redirect_host':'evil.example'}
        elif phase == 'unsafe_base':
            value = dict(confirmed(), baseurl='http://localhost:1234')
        elif phase == 'foreign_owner':
            value = confirmed('different-owner')
        return httpx.Response(200,json=value)
    async def run():
        bridge = Bridge(store,httpx.MockTransport(lambda r:pytest.fail('No authenticated requests expected')))
        pairing = Pairing(bridge,run_workers=False,transport=httpx.MockTransport(handler),poll_delay=0)
        with pytest.raises(BridgeError,match='confirm_rebind_required'):
            await pairing.start()
        await pairing.start(replace=True)
        await pairing.task
        assert pairing.phase == expected
        assert store.account() == before and not pairing.png
        assert all(r.url.host.endswith('.weixin.qq.com') for r in calls)
        if phase == 'expired':
            assert sum(r.url.path.endswith('get_bot_qrcode') for r in calls) == 4
        await pairing.close()
        await bridge.close()
    asyncio.run(run())


def test_pairing_timeout_leaves_server_unbound(store):
    async def hold(request):
        await asyncio.sleep(30)
    async def run():
        bridge = Bridge(store)
        pairing = Pairing(bridge,run_workers=False,transport=httpx.MockTransport(hold),lifetime=.03)
        await pairing.start()
        await pairing.task
        assert pairing.phase == 'timeout' and store.account() is None
        assert not pairing.png
        await pairing.close()
        await bridge.close()
    asyncio.run(run())


def test_rebind_cancels_old_receiver_before_new_credentials_and_keeps_history(store):
    store.bind(account(token='old-token'))
    store.set('last_activity_at',time.time()-500)
    store.db.execute('INSERT INTO outgoing VALUES (?,?,?,?,?,?,?,?)', ('old','hash','api_accepted','message','codex',1,2,None))
    tokens = []
    cancelled = []
    async def handler(request):
        if request.url.path.endswith('getupdates'):
            token = request.headers['authorization']
            tokens.append(token)
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.append(token)
                raise
        return httpx.Response(200,json={'ret':0})
    async def run():
        bridge = Bridge(store,httpx.MockTransport(handler))
        await bridge.start()
        await until(lambda: bool(tokens))
        await bridge.bind_account(account(token='new-token'))
        await until(lambda: len(tokens)==2)
        assert tokens == ['Bearer old-token','Bearer new-token']
        assert cancelled == ['Bearer old-token']
        assert len(bridge.tasks)==3
        assert store.receipt('old')['status']=='api_accepted'
        assert store.status()['next_heartbeat_at'] is None
        await bridge.close()
    asyncio.run(run())


def test_legacy_install_without_admin_keeps_api_available(store):
    bridge = Bridge(store)
    with TestClient(create_app(bridge, {'codex':hashlib.sha256(b'fixture-client').hexdigest()}, False)) as client:
        assert client.get('/admin/api/status',headers=ADMIN).status_code==503
        assert client.get('/api/status',headers=CLIENT).status_code==200
    asyncio.run(bridge.close())


def test_confirmed_binding_is_not_interrupted_by_qr_deadline(store):
    def handler(request):
        value = ({'qrcode':'qr','qrcode_img_content':'test'} if request.url.path.endswith('get_bot_qrcode')
                 else confirmed())
        return httpx.Response(200,json=value)
    async def run():
        bridge = Bridge(store)
        original = bridge.bind_account
        async def slow_handover(credentials, run_workers):
            await asyncio.sleep(.15)
            await original(credentials, run_workers)
        bridge.bind_account = slow_handover
        pairing = Pairing(bridge,run_workers=False,transport=httpx.MockTransport(handler),lifetime=.1)
        await pairing.start()
        await pairing.task
        assert pairing.phase=='bound' and store.account()['user_id']=='fixture-owner'
        await pairing.close()
        await bridge.close()
    asyncio.run(run())
