"""Feishu HTTP contracts with a mock upstream and genuine signed/encrypted callbacks."""
import base64
import hashlib
import json
import os
import time

import httpx
import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from test_portal import portal, ADMIN

CONFIG = dict(enabled=True, app_id='cli_fixture', owner_open_id='ou_owner', app_secret='fixture-secret',
              verification_token='fixture-verification', encrypt_key='fixture-encrypt')


@pytest.fixture
def feishu(portal):
    store, client, auth, other, chats, wechat_calls, key = portal
    adapter = client.app.state.channels.feishu
    adapter.configure(dict(CONFIG))
    for identity in (auth,other):
        id=store.clients.authenticate(identity['Authorization'][7:]).id
        store.bots.set_grants(id,['default','feishu-default'],'default')
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        calls.append((request, payload))
        if request.url.path.endswith('/internal'):
            return httpx.Response(200, json=dict(code=0, tenant_access_token='fixture-token', expire=7200))
        if request.method == 'PATCH':
            return httpx.Response(200, json={'code':0})
        assert request.url.params['receive_id_type'] == 'open_id'
        assert payload['receive_id'] == 'ou_owner' and len(payload['uuid']) == 32
        return httpx.Response(200, json=dict(code=0, data=dict(message_id='om_' + payload['uuid'])))
    adapter.transport = httpx.MockTransport(handler)
    return portal, calls


def send(feishu, **overrides):
    portal, _ = feishu
    body = dict(text='**完成了**', dedup_key='feishu-event', conversation_id=portal[4][0]['id'], channel='feishu')
    body.update(overrides)
    return portal[1].post('/api/messages', headers=portal[2], json=body)


def callback(client, value, *, signed=True, timestamp=None):
    padder = padding.PKCS7(128).padder()
    raw = json.dumps(value, ensure_ascii=False).encode()
    padded = padder.update(raw) + padder.finalize()
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(hashlib.sha256(CONFIG['encrypt_key'].encode()).digest()), modes.CBC(iv)).encryptor()
    raw = json.dumps(dict(encrypt=base64.b64encode(iv + cipher.update(padded) + cipher.finalize()).decode())).encode()
    stamp, nonce = str(int(time.time()) if timestamp is None else timestamp), 'fixture-nonce'
    headers = {'Content-Type': 'application/json', 'X-Lark-Request-Timestamp': stamp, 'X-Lark-Request-Nonce': nonce}
    if signed:
        headers['X-Lark-Signature'] = hashlib.sha256((stamp + nonce + CONFIG['encrypt_key']).encode() + raw).hexdigest()
    return client.post('/channels/feishu/callback', content=raw, headers=headers)


def event(kind, data, **header):
    return dict(schema='2.0', header=dict(event_type=kind, event_id='fixture-event', app_id=CONFIG['app_id'],
                                         token=CONFIG['verification_token'], **header), event=data)


def message(text, **overrides):
    msg = dict(chat_type='p2p', message_type='text', message_id='om_incoming', create_time=str(int(time.time()*1000)),
               content=json.dumps(dict(text=text)), **overrides)
    return event('im.message.receive_v1', dict(sender=dict(sender_type='user', sender_id={'open_id':'ou_owner'}), message=msg))


def test_feishu_only_sending_dedup_receipt_and_wechat_isolation(feishu):
    portal, calls = feishu
    store, client, auth, _, chats, wechat_calls, _ = portal
    store.db.execute('DELETE FROM account')
    before = store.get('last_activity_at')
    first = send(feishu).json()
    assert first['channel'] == 'feishu' and first['status'] == 'api_accepted' and first['phone_delivery'] == 'unconfirmed'
    assert send(feishu).json()['duplicate'] and len(calls) == 2 and not wechat_calls
    assert send(feishu, text='changed').status_code == 409
    receipt = client.get('/api/deliveries', headers=auth, params=dict(channel='feishu', dedup_key='feishu-event', conversation_id=chats[0]['id'])).json()
    assert receipt['message_id'] == first['message_id']
    assert store.get('last_activity_at') == before and store.db.execute('SELECT count(*) FROM outgoing').fetchone()[0] == 0
    wire = json.loads(calls[-1][1]['content'])
    assert wire['schema'] == '2.0' and wire['body']['elements'][-1]['behaviors'][0]['default_url'] == first['conversation_url']
    assert '(9/10)' not in json.dumps(wire)


def test_default_wechat_contract_and_cross_channel_keys_are_independent(feishu):
    portal, calls = feishu
    store, client, auth, _, chats, wechat_calls, _ = portal
    assert send(feishu, channel='wechat').json()['status'] == 'api_accepted'
    assert send(feishu).json()['status'] == 'api_accepted'
    assert len(wechat_calls) == 1 and len(calls) == 2
    assert store.status()['last_send_status'] == 'api_accepted'
    assert client.get('/api/status', headers=auth).json()['channels']['feishu']['enabled']


def test_channel_configuration_is_admin_only_encrypted_and_rotatable(feishu):
    portal, _ = feishu
    store, client, auth, _, _, _, _ = portal
    path = '/admin/api/channels/feishu'
    assert client.get(path).status_code == 401 and client.post(path, headers=auth, json=CONFIG).status_code == 401
    public = client.get(path, headers=ADMIN).json()
    assert public['callback_url'] == 'https://testserver/channels/feishu/feishu-default/callback'
    assert not {'app_secret','verification_token','encrypt_key'} & public.keys()
    assert 'fixture-secret' not in '\n'.join(store.db.iterdump())
    changed = dict(CONFIG, app_secret='rotated-secret', verification_token='', encrypt_key='')
    assert client.post(path, headers=ADMIN, json=changed).status_code == 200
    assert client.app.state.channels.feishu.config()['verification_token'] == CONFIG['verification_token']
    assert client.post(path, headers=ADMIN, json=dict(CONFIG, owner_open_id='ou_other')).status_code == 409
    assert client.post(path, headers=ADMIN, json=dict(CONFIG, enabled=False)).status_code == 200
    assert send(feishu).status_code == 409


@pytest.mark.parametrize('bad', ['signature','old','future','token','app','plaintext','oversize'])
def test_callbacks_authenticate_before_persistence(feishu, bad):
    portal, _ = feishu
    store, client, _, _, chats, _, _ = portal
    payload = message('[codex-one] test')
    kwargs = {}
    if bad == 'signature': kwargs['signed'] = False
    if bad == 'old': kwargs['timestamp'] = int(time.time()) - 600
    if bad == 'future': kwargs['timestamp'] = int(time.time()) + 600
    if bad == 'token': payload['header']['token'] = 'wrong'
    if bad == 'app': payload['header']['app_id'] = 'cli_wrong'
    if bad == 'plaintext': response = client.post('/channels/feishu/callback', json=payload)
    elif bad == 'oversize': response = client.post('/channels/feishu/callback', content=b'x'*65537)
    else: response = callback(client, payload, **kwargs)
    assert response.status_code in (401, 413)
    assert not store.inbox(0, 100, chats[0]['id'])


def test_challenge_owner_filter_routing_reply_and_wake(feishu):
    portal, _ = feishu
    store, client, auth, other, chats, _, _ = portal
    challenge = callback(client, dict(type='url_verification', token=CONFIG['verification_token'], challenge='challenge'), signed=False)
    assert challenge.json() == {'challenge':'challenge'}
    outgoing = send(feishu).json()
    provider = outgoing['diagnostics']['provider_message_id']
    payload = message('收到', parent_id=provider)
    assert callback(client, payload).json()['accepted']
    assert callback(client, payload).json()['duplicate']
    inbox = client.get('/api/inbox', headers=auth, params={'conversation_id':chats[0]['id']}).json()['messages']
    assert len(inbox) == 1 and inbox[0]['source'] == 'feishu' and inbox[0]['text'] == '收到'
    assert len(client.get('/api/wake/events', headers=auth, params={'conversation_id':chats[0]['id'],'after_id':0}).json()['events']) == 1
    assert client.get('/api/inbox', headers=other, params={'conversation_id':chats[0]['id']}).status_code == 404
    foreign = message('foreign'); foreign['event']['sender']['sender_id']['open_id'] = 'ou_foreign'
    assert callback(client, foreign).json()['ignored']
    group = message('group'); group['event']['message']['chat_type'] = 'group'
    assert callback(client, group).json()['ignored']
    tagged = message('[codex-开发] 新问题'); tagged['event']['message']['message_id'] = 'om_tagged'
    assert callback(client, tagged).json()['accepted']
    assert len(store.inbox(0, 20, chats[0]['id'])) == 2


@pytest.mark.parametrize('mode', ['single', 'multiple', 'confirm', 'input', 'form'])
def test_native_task_answers_share_state_and_event_once(feishu, mode):
    portal, calls = feishu
    store, client, auth, _, chats, wechat_calls, _ = portal
    cid = chats[0]['id']
    body = dict(channel='feishu', conversation_id=cid, dedup_key='task-'+mode, title='选择方案', prompt='需要你的决定', mode=mode)
    if mode in ('single', 'multiple', 'confirm'):
        body['options'] = [dict(id='a', label='A'),dict(id='b',label='B')]
    if mode == 'form':
        body['fields'] = [dict(id='name',label='名称',type='text')]
    response = client.post('/api/task-cards', headers=auth, json=body)
    assert response.status_code == 200, response.text
    sent = response.json(); task = sent['task']
    assert not wechat_calls
    value = dict(conversation_id=cid, task_id=task['id'])
    form = {'choice_id':'a'} if mode == 'single' else {'choice_ids':['a','b']} if mode == 'multiple' else {'reply_text':'我的安排'} if mode == 'input' else {'field_name':'通知桥'} if mode == 'form' else {}
    if mode == 'confirm': value['choice_id'] = 'a'
    payload = event('card.action.trigger', dict(operator={'open_id':'ou_owner'},
        context={'open_message_id':sent['diagnostics']['provider_message_id']}, action=dict(value=value, form_value=form)))
    first = callback(client, payload)
    assert first.status_code == 200 and first.json()['toast']['type'] == 'success', first.text
    assert callback(client, payload).json()['toast']['type'] == 'success'
    assert store.portal.tasks.get(cid, task['id'])['status'] == 'answered'
    inbox = store.inbox(0, 20, cid)
    assert len(inbox) == 1 and inbox[0]['source'] == 'feishu' and inbox[0]['task_response']['task_id'] == task['id']
    if mode == 'form': assert inbox[0]['task_response']['field_values'] == {'name':'通知桥'}
    assert len(client.get('/api/wake/events',headers=auth,params=dict(conversation_id=cid,after_id=0)).json()['events']) == 1
    changed = json.loads(json.dumps(payload)); changed['event']['context']['open_message_id'] = 'om_other'
    assert callback(client, changed).json()['toast']['type'] == 'error'
    assert store.db.execute('SELECT count(*) FROM outgoing').fetchone()[0] == 0
    completed = client.post(f'/api/conversations/{cid}/tasks/{task["id"]}/state', headers=auth,
                            json=dict(status='completed', result='已完成处理')).json()
    assert completed['task']['status'] == 'completed' and completed['card_delivery'] == 'api_updated'
    assert calls[-1][0].method == 'PATCH'


def test_unknown_sends_never_resend(feishu):
    portal, calls = feishu
    _, client, _, _, chats, _, _ = portal
    adapter = client.app.state.channels.feishu
    def timeout(request):
        if request.url.path.endswith('/internal'):
            return httpx.Response(200,json=dict(code=0,tenant_access_token='fixture-token',expire=7200))
        calls.append(request)
        raise httpx.ReadTimeout('fixture',request=request)
    adapter.transport = httpx.MockTransport(timeout)
    assert send(feishu).json()['status'] == 'unconfirmed_do_not_retry'
    assert send(feishu).json()['duplicate'] and len(calls) == 1


def test_archived_conversation_and_deleted_history_remain_protected(feishu):
    portal, _ = feishu
    store, client, auth, _, chats, _, _ = portal
    cid = chats[0]['id']
    assert send(feishu).json()['status'] == 'api_accepted'
    store.conversations.set_active(store.clients.authenticate(auth['Authorization'][7:]).id,cid,False)
    assert send(feishu,dedup_key='after-archive').status_code == 409
    store.portal.delete_chat(cid)
    row = store.db.execute('SELECT encrypted,provider_hash FROM channel_outgoing WHERE conversation_id=?',(cid,)).fetchone()
    assert row['encrypted'] is None and row['provider_hash'] is None


def test_commands_login_code_and_duplicate_do_not_enter_ai_inbox(feishu):
    portal, calls = feishu
    store, client, auth, _, chats, _, _ = portal
    payload = message('/web')
    assert callback(client, payload).status_code == 200
    saved = store.get('web_login')
    assert saved and len(calls) == 2
    assert callback(client, payload).json()['duplicate']
    assert store.get('web_login') == saved and len(calls) == 2
    assert store.inbox(0, 20, chats[0]['id']) == []
    assert store.db.execute('SELECT encrypted FROM channel_commands').fetchone()[0] is None


@pytest.mark.parametrize('closed', ['archive', 'expired'])
def test_native_card_refuses_archived_or_expired_tasks(feishu, closed):
    portal, _ = feishu
    store, client, auth, _, chats, _, _ = portal
    cid = chats[0]['id']
    body = dict(channel='feishu',conversation_id=cid,dedup_key='closed-task',title='确认',prompt='确认操作',mode='confirm',
                options=[dict(id='a',label='A'),dict(id='b',label='B')])
    sent = client.post('/api/task-cards',headers=auth,json=body).json()
    if closed == 'archive':
        store.conversations.set_active(store.clients.authenticate(auth['Authorization'][7:]).id,cid,False)
    else:
        store.db.execute('UPDATE task_cards SET expires_at=0 WHERE id=?',(sent['task']['id'],))
    payload = event('card.action.trigger',dict(operator={'open_id':'ou_owner'},
        context={'open_message_id':sent['diagnostics']['provider_message_id']},
        action={'value':dict(conversation_id=cid,task_id=sent['task']['id'],choice_id='a')}))
    assert callback(client,payload).json()['toast']['type'] == 'error'
    assert store.inbox(0,20,cid) == []


def test_initial_disabled_settings_can_be_enabled_later(portal):
    client = portal[1]
    path = '/admin/api/channels/feishu'
    assert client.post(path,headers=ADMIN,json={'enabled':False}).status_code == 200
    assert client.post(path,headers=ADMIN,json=CONFIG).status_code == 200
    assert client.app.state.channels.feishu.http is None
