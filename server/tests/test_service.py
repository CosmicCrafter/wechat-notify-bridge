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


@pytest.fixture
def store(tmp_path):
    key = Fernet.generate_key()
    value = Store(tmp_path / 'test.sqlite3', key)
    value.bootstrap(Fernet(key).encrypt(json.dumps({'credentials': {
        'user_id': 'test-owner', 'bot_token': 'test-token', 'context_token': 'test-context',
        'base_url': 'https://ilinkai.weixin.qq.com', 'bound_at': time.time(),
        'context_received_at': time.time(), 'get_updates_buf': ''}}).encode()))
    yield value
    value.close()


def incoming(seq=1, at=None, owner='test-owner'):
    return {'message_id': seq, 'seq': seq, 'from_user_id': owner, 'message_type': 1,
            'message_state': 2, 'create_time_ms': int((at or time.time()) * 1000),
            'context_token': 'new-context', 'item_list': [{'type': 1, 'text_item': {'text': 'reply'}}]}


def test_receive_updates_context_and_deadline_and_is_idempotent(store):
    stamp = time.time() + 100
    assert store.ingest({'msgs': [incoming(at=stamp)], 'get_updates_buf': 'cursor'}, stamp) == 1
    deadline = store.next_heartbeat()
    assert deadline == pytest.approx(stamp + INTERVAL, abs=.002)
    assert store.ingest({'msgs': [incoming(at=stamp)]}, stamp + 50) == 0
    assert store.next_heartbeat() == deadline
    assert store.account()['get_updates_buf'] == 'cursor'
    assert store.account()['context_token'] == 'new-context'
    assert store.inbox(0, 20)[0]['text'] == 'reply'
    raw = store.db.execute('SELECT encrypted FROM inbox').fetchone()[0]
    assert b'reply' not in raw


def test_other_senders_and_bot_echoes_do_not_postpone(store):
    baseline = store.next_heartbeat()
    bot = incoming(seq=2)
    bot['message_type'] = 2
    assert store.ingest({'msgs': [incoming(owner='another-user'), bot]}, time.time()) == 0
    assert store.next_heartbeat() == baseline


def test_new_message_state_is_valid_inbound_activity(store):
    value=incoming()
    value['message_state']=0
    assert store.ingest({'msgs':[value]},time.time())==1


def test_concurrent_identical_requests_submit_once(store):
    calls=[]
    async def handler(request):
        calls.append(1)
        await asyncio.sleep(.01)
        return httpx.Response(200,json={'ret':0})
    async def run():
        bridge=Bridge(store,httpx.MockTransport(handler))
        results=await asyncio.gather(*(bridge.send('same message','concurrent','codex') for _ in range(10)))
        assert len(calls)==1
        assert sum(not r['duplicate'] for r in results)==1
        await bridge.close()
    asyncio.run(run())


def test_restart_preserves_activity_and_inbox(store, tmp_path):
    stamp = time.time() + 50
    store.ingest({'msgs': [incoming(at=stamp)]}, stamp)
    other = Store(tmp_path / 'test.sqlite3', Fernet.generate_key())
    assert other.next_heartbeat() == store.next_heartbeat()
    other.close()


def test_success_updates_timer_and_duplicate_never_sends_again(store):
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'ret': 0})
    async def run():
        bridge = Bridge(store, httpx.MockTransport(handler))
        first = await bridge.send('plain message', 'same-key', 'codex')
        deadline = store.next_heartbeat()
        second = await bridge.send('plain message', 'same-key', 'codex')
        with pytest.raises(BridgeError):
            await bridge.send('changed', 'same-key', 'codex')
        assert first['status'] == 'api_accepted'
        assert second['duplicate'] is True
        assert first['phone_delivery'] == 'unconfirmed'
        assert store.next_heartbeat() == deadline
        assert len(calls) == 1
        assert calls[0]['msg']['to_user_id'] == 'test-owner'
        assert calls[0]['msg']['item_list'][0]['text_item']['text'] == 'plain message'
        await bridge.close()
    asyncio.run(run())


@pytest.mark.parametrize('failure,status', [('timeout','unconfirmed_do_not_retry'),('reject','api_rejected')])
def test_failed_send_does_not_refresh_activity_or_retry(store, failure, status):
    calls = []
    def handler(request):
        calls.append(1)
        if failure == 'timeout':
            raise httpx.ReadTimeout('test')
        return httpx.Response(200, json={'errcode': -14})
    async def run():
        bridge = Bridge(store, httpx.MockTransport(handler))
        last = store.get('last_activity_at')
        assert (await bridge.send('test', 'failed', 'codex'))['status'] == status
        assert (await bridge.send('test', 'failed', 'codex'))['duplicate']
        assert len(calls) == 1
        assert store.get('last_activity_at') == last
        await bridge.close()
    asyncio.run(run())


def test_heartbeat_due_only_after_12h_and_next_one_after_success(store):
    calls=[]
    def handler(request):
        calls.append(1)
        return httpx.Response(200,json={})
    async def run():
        bridge=Bridge(store,httpx.MockTransport(handler))
        assert (await bridge.heartbeat_once())['status']=='not_due'
        store.set('last_activity_at',time.time()-INTERVAL-1)
        assert (await bridge.heartbeat_once())['status']=='no_error_reported'
        assert (await bridge.heartbeat_once())['status']=='not_due'
        assert len(calls)==1
        assert store.next_heartbeat()>time.time()+INTERVAL-2
        await bridge.close()
    asyncio.run(run())


def test_heartbeat_rechecks_new_activity_after_waiting_for_send_lock(store):
    calls=[]
    async def run():
        bridge=Bridge(store,httpx.MockTransport(lambda request: calls.append(1) or httpx.Response(200,json={'ret':0})))
        store.set('last_activity_at',time.time()-INTERVAL-1)
        await bridge.lock.acquire()
        heartbeat=asyncio.create_task(bridge.heartbeat_once())
        await asyncio.sleep(0)
        store.touch(time.time())
        bridge.lock.release()
        assert (await heartbeat)['status']=='skipped_new_activity'
        assert calls==[]
        await bridge.close()
    asyncio.run(run())


def test_failed_heartbeat_backoff_survives_service_restart(store):
    async def run():
        bridge=Bridge(store,httpx.MockTransport(lambda r:httpx.Response(200,json={'ret':-1})))
        store.set('last_activity_at',time.time()-INTERVAL-1)
        assert (await bridge.heartbeat_once())['status']=='api_rejected'
        assert (await bridge.heartbeat_once())['status']=='not_due'
        assert store.get('last_heartbeat_status')=='api_rejected'
        assert store.next_heartbeat()>time.time()+INTERVAL-2
        await bridge.close()
    asyncio.run(run())


def test_session_expired_suppresses_heartbeat(store):
    async def run():
        bridge=Bridge(store,httpx.MockTransport(lambda r:pytest.fail('No send expected')))
        store.set('last_activity_at',time.time()-INTERVAL-1)
        store.set('poll_status','session_expired')
        assert (await bridge.heartbeat_once())['status']=='session_expired'
        await bridge.close()
    asyncio.run(run())


def test_api_auth_validation_and_dryrun_do_not_send(store):
    bridge=Bridge(store,httpx.MockTransport(lambda r:pytest.fail('No network expected')))
    app=create_app(bridge,{'codex':hashlib.sha256(b'test-key').hexdigest()},run_workers=False)
    headers={'Authorization':'Bearer test-key'}
    with TestClient(app) as client:
        assert client.get('/health').status_code==200
        for path in ('/api/status','/api/inbox','/api/deliveries?dedup_key=a','/openapi.json'):
            assert client.get(path).status_code==401
        assert client.post('/api/messages',json={'text':'test','dedup_key':'a'}).status_code==401
        assert client.post('/api/messages',headers=headers,json={'text':' ','dedup_key':'a'}).status_code==422
        assert client.post('/api/messages',headers=headers,json={'text':'test','dedup_key':'a','recipient':'other'}).status_code==422
        assert client.post('/api/messages',headers=headers,json={'text':'test','dedup_key':'a','dry_run':True}).json()['status']=='dry_run_ready'
        assert client.get('/api/status',headers=headers).json()['caller']=='codex'
        assert store.db.execute('SELECT count(*) FROM outgoing').fetchone()[0]==0
    asyncio.run(bridge.close())
