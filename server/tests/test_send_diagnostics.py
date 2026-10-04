"""Rejection evidence, uncertainty, privacy, and observed push-budget warnings."""
import asyncio
import json
import sqlite3
import time

from cryptography.fernet import Fernet
import httpx
import pytest

from test_service import store, incoming
from test_portal import portal, login, ORIGIN, send
from wechat_bridge.services.bridge import Bridge
from wechat_bridge.storage.database import Store


@pytest.mark.parametrize('response,category', [
    ({'ret': -2, 'errmsg': 'rate limited'}, 'wechat_rate_limited'),
    ({'ret': -2, 'errmsg': 'prepare failed'}, 'wechat_prepare_failed'),
    ({'errcode': -2, 'errmsg': 'context_token expired'}, 'wechat_context_rejected'),
    ({'ret': -14, 'errmsg': ''}, 'wechat_session_expired'),
    ({'ret': -2}, 'wechat_rejected'),
    ({'ret': -2, 'errmsg': 'unexpected secret-context-token'}, 'wechat_rejected'),
])
def test_rejections_preserve_evidence_without_leaking_upstream_text(store, caplog, response, category):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=response)
    async def run():
        bridge = Bridge(store, httpx.MockTransport(handler))
        result = await bridge.send('private text', 'rejection', 'codex')
        diagnostic = result['diagnostics']
        assert result['status'] == 'api_rejected'
        assert diagnostic['error_category'] == category
        assert diagnostic['http_status'] == 200 and diagnostic['duration_ms'] >= 0
        assert diagnostic['upstream_error_field'] == ('ret' if 'ret' in response else 'errcode')
        assert diagnostic['accepted_sends_since_context'] == 0
        public = json.dumps([result, store.status()], ensure_ascii=False) + caplog.text
        for secret in ('private text', 'secret-context-token', store.account()['context_token']):
            assert secret not in public
        assert 'upstream_error_message' not in diagnostic
        if category == 'wechat_rate_limited':
            assert '发送限流' in result['recovery_hint']
        if category == 'wechat_prepare_failed':
            assert '不能据此区分' in diagnostic['error_summary']
        raw = store.db.execute('SELECT encrypted FROM send_diagnostics').fetchone()[0]
        assert b'upstream_error_message' not in raw
        assert json.loads(store.cipher.decrypt(raw))['upstream_error_message'] == response.get('errmsg')
        assert (await bridge.send('private text', 'rejection', 'codex'))['duplicate']
        assert len(calls) == 1
        assert store.status()['last_send_diagnostics'] == diagnostic
        await bridge.close()
    asyncio.run(run())


@pytest.mark.parametrize('failure,category,http_status', [
    ('timeout', 'network_timeout', None),
    ('network', 'network_error', None),
    ('http', 'http_error', 429),
    ('invalid', 'invalid_response', 200),
])
def test_uncertain_errors_never_become_rejected_or_trigger_resends(store, caplog, failure, category, http_status):
    calls = []
    def handler(request):
        calls.append(1)
        if failure == 'timeout':
            raise httpx.ReadTimeout('secret-transport-url-token')
        if failure == 'network':
            raise httpx.ConnectError('secret-transport-url-token')
        if failure == 'http':
            return httpx.Response(429, text='secret-transport-url-token')
        return httpx.Response(200, text='secret-transport-url-token')
    async def run():
        bridge = Bridge(store, httpx.MockTransport(handler))
        result = await bridge.send('test', 'uncertain', 'codex')
        assert result['status'] == 'unconfirmed_do_not_retry'
        assert result['diagnostics']['error_category'] == category
        assert result['diagnostics']['http_status'] == http_status
        assert 'secret-transport-url-token' not in json.dumps(result) + caplog.text
        assert (await bridge.send('test', 'uncertain', 'codex'))['duplicate']
        assert len(calls) == 1
        await bridge.close()
    asyncio.run(run())


def test_budget_is_observed_warning_not_hard_quota_and_new_wechat_message_resets_it(store):
    calls = []
    async def run():
        def handler(request):
            calls.append(json.loads(request.content)['msg']['item_list'][0]['text_item']['text'])
            return httpx.Response(200, json={'ret': 0})
        bridge = Bridge(store, httpx.MockTransport(handler))
        received = store.account()['context_received_at']
        for n in range(8):
            result = await bridge.send('test', 'budget-' + str(n), 'codex' if n % 2 else 'gpt')
            assert result['diagnostics']['accepted_sends_since_context'] == n
            assert f'通知额度 ({9 - n}/10)' in calls[-1]
            assert '归零前请给 Bot 发句话' in calls[-1]
        status = store.status()
        assert status['accepted_sends_since_context'] == 8 and status['quota_warning']
        assert '不是微信剩余额度' in status['quota_warning']
        assert store.account()['context_received_at'] == received
        await bridge.send('test', 'budget-7', 'codex')
        assert store.status()['accepted_sends_since_context'] == 8 and len(calls) == 8
        # Unknown server policy must not become a fabricated local 10-send limit.
        for n in range(8, 12):
            assert (await bridge.send('test', 'budget-' + str(n), 'codex'))['status'] == 'api_accepted'
            assert f'通知额度 ({max(0, 9 - n)}/10)' in calls[-1]
        assert store.status()['accepted_sends_since_context'] == 12
        now = time.time()
        store.ingest({'msgs': [incoming(seq=99, at=now)]}, now)
        assert store.status()['accepted_sends_since_context'] == 0 and store.status()['quota_warning'] is None
        assert store.account()['context_token'] == 'new-context'
        assert store.inbox(0, 20)[-1]['conversation_id'] is None
        await bridge.send('after ordinary Bot message', 'fresh-budget', 'codex')
        assert '通知额度 (9/10)' in calls[-1]
        await bridge.close()
    asyncio.run(run())


def test_footer_does_not_charge_rejected_or_duplicate_sends(store):
    calls = []
    def handler(request):
        calls.append(json.loads(request.content)['msg']['item_list'][0]['text_item']['text'])
        return httpx.Response(200, json={'ret': -2, 'errmsg': 'prepare failed'} if len(calls) == 2 else {'ret': 0})
    async def run():
        bridge = Bridge(store, httpx.MockTransport(handler))
        await bridge.send('first', 'footer-first', 'codex')
        assert (await bridge.send('rejected', 'footer-rejected', 'codex'))['status'] == 'api_rejected'
        assert (await bridge.send('first', 'footer-first', 'codex'))['duplicate']
        await bridge.send('second accepted', 'footer-second', 'gpt')
        assert len(calls) == 3
        assert '通知额度 (8/10)' in calls[-1]
        assert store.status()['accepted_sends_since_context'] == 2
        await bridge.close()
    asyncio.run(run())


def test_footer_never_fabricates_remaining_budget_for_legacy_context(store):
    account = store.account()
    account.pop('context_received_at')
    store.save_account(account)
    calls = []
    def handler(request):
        calls.append(json.loads(request.content)['msg']['item_list'][0]['text_item']['text'])
        return httpx.Response(200, json={'ret': 0})
    async def run():
        bridge = Bridge(store, httpx.MockTransport(handler))
        result = await bridge.send('legacy', 'legacy-budget', 'codex')
        assert result['diagnostics']['accepted_sends_since_context'] is None
        assert '通知额度 (未知/10)' in calls[-1] and '(9/10)' not in calls[-1]
        await bridge.close()
    asyncio.run(run())


def test_diagnostic_migration_and_restart_preserve_old_receipts(tmp_path):
    path, key = tmp_path / 'legacy.sqlite3', Fernet.generate_key()
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE outgoing (key TEXT PRIMARY KEY,message_hash TEXT NOT NULL,status TEXT NOT NULL,'
               'kind TEXT NOT NULL,caller TEXT NOT NULL,attempted_at REAL NOT NULL,finished_at REAL,error_code TEXT)')
    db.execute('INSERT INTO outgoing VALUES (?,?,?,?,?,?,?,?)', ('old', 'hash', 'api_rejected', 'message', 'codex', 1, 2, '-2'))
    db.commit(); db.close()
    store = Store(path, key)
    original = store.receipt('old')
    assert store.send_diagnostics.public('old') is None
    store.send_diagnostics.save('old', {'error_category': 'wechat_prepare_failed', 'upstream_error_message': 'prepare failed'})
    diagnostic = store.send_diagnostics.public('old')
    store.close()
    reopened = Store(path, key)
    assert reopened.receipt('old') == original
    assert reopened.send_diagnostics.public('old') == diagnostic
    assert reopened.status()['last_send_error_code'] == '-2'
    reopened.close()


def test_web_reply_does_not_refresh_context_or_observed_budget_and_delete_purges_evidence(portal):
    store, client, auth, _, chats, _, _ = portal
    cid = chats[0]['id']
    now = time.time()
    store.ingest({'msgs': [incoming(seq=100, at=now, owner='owner')]}, now)
    result = send(client, auth, cid, key='diagnostic-web').json()
    before = store.send_diagnostics.context()
    assert before['accepted_sends_since_context'] == 1
    login(client)
    response = client.post('/chat/api/conversations/' + cid + '/messages', headers=ORIGIN,
                           json={'text': 'web reply', 'request_id': 'diagnostic-web-reply-1'})
    assert response.status_code == 200
    after = store.send_diagnostics.context()
    assert after['context_received_at'] == before['context_received_at']
    assert after['accepted_sends_since_context'] == 1
    key = store.db.execute('SELECT outgoing_key FROM chat_messages WHERE id=?', (result['message_id'],)).fetchone()[0]
    assert store.send_diagnostics.public(key) is not None
    assert client.post('/chat/api/conversations/' + cid + '/delete', headers=ORIGIN, json={}).status_code == 200
    assert store.send_diagnostics.public(key) is None
    # Keep the original deduplication tombstone, so deleting history never resends.
    assert store.receipt(key)['status'] == 'api_accepted'


def test_error_evidence_redacts_credentials_even_inside_encrypted_record(store):
    account = store.account()
    key = '1234567890' * 4
    message = 'rate limited ' + account['context_token'] + ' ' + account['bot_token'] + ' ' + key
    async def run():
        bridge = Bridge(store, httpx.MockTransport(lambda r: httpx.Response(200, json={'ret': -2, 'errmsg': message})))
        result = await bridge.send('test', 'redaction', 'codex')
        assert result['diagnostics']['error_category'] == 'wechat_rate_limited'
        raw = store.db.execute('SELECT encrypted FROM send_diagnostics').fetchone()[0]
        saved = store.cipher.decrypt(raw).decode()
        assert all(secret not in saved for secret in (account['context_token'], account['bot_token'], key))
        assert '[redacted]' in saved
        await bridge.close()
    asyncio.run(run())
