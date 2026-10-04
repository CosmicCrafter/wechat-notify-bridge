"""One WeChat owner, multiple identities, explicit key lifecycle and private commands."""
import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import httpx
import pytest

from wechat_bridge.app import create_app
from wechat_bridge.storage.client_registry import ClientError
from wechat_bridge.services.bridge import Bridge
from wechat_bridge.storage.database import Store
from wechat_bridge.services.commands import format_time, execute

ADMIN={'Authorization':'Bearer fixture-admin'}


@pytest.mark.parametrize('utc_hour,expected', [(15, '2026-10-02 23:48'), (18, '2026-10-03 02:48')])
def test_wechat_command_times_use_beijing_time_including_next_day(store,utc_hour,expected):
    from datetime import datetime, timezone
    stamp=datetime(2026,10,2,utc_hour,48,tzinfo=timezone.utc).timestamp()
    assert format_time(stamp)==expected
    assert format_time(None)=='未调用'
    store.set('last_activity_at',stamp)
    client,_=store.clients.create('codex')
    store.db.execute('UPDATE api_clients SET last_seen_at=? WHERE id=?',(stamp,client['id']))
    assert expected in execute(store,'/status').text
    assert expected in execute(store,'/list').text


@pytest.fixture
def store(tmp_path):
    key=Fernet.generate_key()
    value=Store(tmp_path/'clients.sqlite3',key)
    value.test_key=key
    value.bind({'bot_token':'fixture-bot','bot_id':'fixture-id','user_id':'fixture-owner',
                'base_url':'https://ilinkai.weixin.qq.com','bound_at':time.time(),
                'context_token':'fixture-context'})
    yield value
    value.close()


def incoming(text, id=1, **extra):
    return dict({'message_id':id,'seq':id,'from_user_id':'fixture-owner','message_type':1,
                 'message_state':2,'context_token':'fixture-new-context','create_time_ms':int(time.time()*1000),
                 'item_list':[{'type':1,'text_item':{'text':text}}]},**extra)


def ingest(store, text, id=1, **extra):
    return store.ingest({'msgs':[incoming(text,id,**extra)],'get_updates_buf':'fixture-cursor'},time.time())


def pending(store):
    row=store.db.execute('SELECT * FROM command_replies ORDER BY id DESC LIMIT 1').fetchone()
    return row, store.cipher.decrypt(row['encrypted_reply']).decode() if row['encrypted_reply'] else ''


def issued_key(store):
    return re.search(r'\b[0-9]{40}\b',pending(store)[1]).group()


def test_getkey_reply_authentication_duplicate_event_and_no_plaintext_key(store):
    assert ingest(store,'/getkey Codex')==1
    key=issued_key(store)
    identity=store.clients.authenticate(key)
    assert identity.name=='codex' and len(key)==40
    assert ingest(store,'/getkey Codex',seq=55)==0
    assert store.account()['get_updates_buf']=='fixture-cursor'
    assert len(store.clients.list())==1
    assert store.inbox(0,20)==[]
    assert key not in '\n'.join(store.db.iterdump())
    ingest(store,'/getkey codex',2)
    assert '已存在' in pending(store)[1] and key not in pending(store)[1]
    assert store.clients.authenticate(key).id==identity.id


@pytest.mark.parametrize('extra', [
    {'from_user_id':'stranger'}, {'message_type':2}, {'message_state':0}, {'delete_time_ms':1},
    {'item_list':[{'type':3,'voice_item':{'text':'/getkey codex'}}]},
    {'item_list':[{'type':1,'text_item':{'text':'/getkey codex'},'ref_msg':{'title':'quoted'}}]},
    {'message_id':None,'seq':None},
])
def test_only_owner_completed_unquoted_text_creates_keys(store, extra):
    ingest(store,'/getkey codex',**extra)
    assert store.clients.list()==[]


def test_old_commands_and_unknown_commands_never_create_keys(store):
    ingest(store,'/getkey codex',create_time_ms=int((time.time()-3600)*1000))
    assert pending(store)[0]['status']=='ignored_old'
    assert store.clients.list()==[]
    for i,text in enumerate(['/getkey','/getkey bad name','/getkey admin','/getkey <script>', '/unknown'],2):
        ingest(store,text,i)
        assert pending(store)[0]['status']=='pending'
        assert len(pending(store)[1])<300
    assert store.clients.list()==[]


def test_key_lifecycle_and_help_list_never_return_old_key(store):
    ingest(store,'/getkey codex')
    key=issued_key(store)
    id=store.clients.authenticate(key).id
    ingest(store,'/rename codex 开发助手',2)
    assert store.clients.authenticate(key).name=='开发助手'
    ingest(store,'/list',3)
    assert '[开发助手]' in pending(store)[1] and key not in pending(store)[1]
    ingest(store,'/revoke 开发助手',4)
    with pytest.raises(ClientError): store.clients.authenticate(key)
    ingest(store,'/resetkey 开发助手',5)
    next_key=issued_key(store)
    assert next_key!=key and store.clients.authenticate(next_key).id==id
    with pytest.raises(ClientError): store.clients.authenticate(key)
    for i,command in enumerate(['/help','/list','/status'],6):
        ingest(store,command,i)
        assert key not in pending(store)[1] and next_key not in pending(store)[1]
    assert store.inbox(0,100)==[]


def test_list_paginates_without_hiding_clients_or_exceeding_message_limit(store):
    for i in range(12): store.clients.create(f'client-{i:02}')
    ingest(store,'/list')
    first=pending(store)[1]
    assert '1/2' in first and '[client-09]' in first and '[client-10]' not in first
    ingest(store,'/list 2',2)
    second=pending(store)[1]
    assert '[client-10]' in second and '[client-11]' in second
    assert len(first)<2000 and len(second)<2000


def test_seeded_key_cannot_resurrect_after_rename_rotate_revoke_restart(store,tmp_path):
    registry={'codex':hashlib.sha256(b'fixture-old').hexdigest()}
    store.clients.seed(registry)
    id=store.clients.authenticate('fixture-old').id
    store.clients.rename(id,'new-codex')
    _,key=store.clients.rotate(id)
    store.clients.revoke(id)
    other=Store(tmp_path/'clients.sqlite3',store.test_key)
    try:
        other.clients.seed(registry)
        assert len(other.clients.list())==1 and other.clients.list()[0]['name']=='new-codex'
        with pytest.raises(ClientError): other.clients.authenticate('fixture-old')
        with pytest.raises(ClientError): other.clients.authenticate(key)
    finally: other.close()


def test_cursor_and_client_creation_roll_back_together(store, monkeypatch):
    original=store.clients.create
    def broken(name):
        original(name)
        raise RuntimeError('fixture failure before reply persistence')
    monkeypatch.setattr(store.clients,'create',broken)
    with pytest.raises(RuntimeError): ingest(store,'/getkey codex')
    assert store.clients.list()==[]
    assert store.get('last_poll_success_at') is None
    assert store.account().get('get_updates_buf') is None
    monkeypatch.setattr(store.clients,'create',original)
    assert ingest(store,'/getkey codex')==1
    assert store.clients.authenticate(issued_key(store)).name=='codex'


@pytest.mark.parametrize('timeout',[False,True])
def test_command_reply_sent_once_and_temporary_key_purged(store,timeout):
    ingest(store,'/getkey codex')
    key=issued_key(store)
    calls=[]
    def handler(request):
        calls.append(json.loads(request.content)['msg']['item_list'][0]['text_item']['text'])
        if timeout: raise httpx.ReadTimeout('fixture')
        return httpx.Response(200,json={'ret':0})
    async def run():
        bridge=Bridge(store,httpx.MockTransport(handler))
        result=await bridge.command_once()
        assert result['status']==('unconfirmed_do_not_retry' if timeout else 'api_accepted')
        assert (await bridge.command_once())['status']=='idle'
        assert len(calls)==1 and key in calls[0]
        assert pending(store)[0]['encrypted_reply'] is None
        assert store.inbox(0,20)==[]
        await bridge.close()
    asyncio.run(run())


def test_superseded_key_reply_is_not_sent(store):
    ingest(store,'/getkey codex')
    old=issued_key(store)
    ingest(store,'/resetkey codex',2)
    new=issued_key(store)
    sent=[]
    def handler(request):
        sent.append(request.content.decode())
        return httpx.Response(200,json={'ret':0})
    async def run():
        bridge=Bridge(store,httpx.MockTransport(handler))
        assert (await bridge.command_once())['status']=='superseded'
        assert (await bridge.command_once())['status']=='api_accepted'
        assert len(sent)==1 and old not in sent[0] and new in sent[0]
        await bridge.close()
    asyncio.run(run())


def test_admin_and_wechat_share_clients_and_api_cannot_manage_keys(store):
    sent=[]
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200,json={'ret':0})
    bridge=Bridge(store,httpx.MockTransport(handler))
    app=create_app(bridge,{},False,admin_hash=hashlib.sha256(b'fixture-admin').hexdigest())
    with TestClient(app) as client:
        for headers in ({},{'Authorization':'Bearer wrong'}):
            assert client.get('/admin/api/clients',headers=headers).status_code==401
            assert client.post('/admin/api/clients',headers=headers,json={'name':'codex'}).status_code==401
        created=client.post('/admin/api/clients',headers=ADMIN,json={'name':'codex'}).json()
        id,key=created['client']['id'],created['api_key']
        auth={'Authorization':'Bearer '+key}
        listing=client.get('/admin/api/clients',headers=ADMIN).json()
        assert key not in json.dumps(listing) and 'key_hash' not in json.dumps(listing)
        assert client.get('/admin/api/clients',headers=auth).status_code==401
        assert client.get('/api/status',headers=auth).json()['caller']=='codex'
        assert client.post('/admin/api/clients',headers=ADMIN,json={'name':'codex'}).status_code==409
        assert client.post('/admin/api/clients',headers=ADMIN,json={'name':'<bad>'}).status_code==422
        ingest(store,'/getkey gpt',2)
        gptkey=issued_key(store)
        gp={'Authorization':'Bearer '+gptkey}
        assert len(client.get('/admin/api/clients',headers=ADMIN).json()['clients'])==2
        assert client.get('/api/inbox',headers=auth).json()['messages']==[]
        body={'text':'same event','dedup_key':'task-1'}
        assert client.post('/api/messages',headers=auth,json=body).json()['status']=='api_accepted'
        assert client.get('/api/deliveries?dedup_key=task-1',headers=gp).json()['status']=='not_found'
        assert client.post('/api/messages',headers=gp,json=body).json()['status']=='api_accepted'
        assert sent[0]['msg']['item_list'][0]['text_item']['text'].split('\n\n---\n\n',1)[0]=='[codex]\n\nsame event'
        assert sent[1]['msg']['item_list'][0]['text_item']['text'].split('\n\n---\n\n',1)[0]=='[gpt]\n\nsame event'
        notice={'task':'test','reason':'reason','need_user':'choice','source':'gpt','dedup_key':'notice'}
        assert client.post('/api/notifications',headers=auth,json=notice).status_code==200
        assert sent[-1]['msg']['item_list'][0]['text_item']['text'].startswith('[codex]\n')
        assert client.post(f'/admin/api/clients/{id}/rename',headers=ADMIN,json={'name':'开发助手'}).status_code==200
        assert client.get('/api/status',headers=auth).json()['caller']=='开发助手'
        assert client.post('/api/messages',headers=auth,json=body).json()['duplicate'] is True
        assert len(sent)==3
        assert client.post(f'/admin/api/clients/{id}/revoke',headers=ADMIN,json={}).status_code==200
        assert client.get('/api/status',headers=auth).status_code==401
        reset=client.post(f'/admin/api/clients/{id}/rotate',headers=ADMIN,json={}).json()
        assert client.get('/api/status',headers=auth).status_code==401
        assert client.get('/api/status',headers={'Authorization':'Bearer '+reset['api_key']}).status_code==200
        assert client.get('/api/status',headers=gp).status_code==200
    asyncio.run(bridge.close())


@pytest.mark.parametrize('operation', ['revoke', 'delete'])
def test_revocation_is_rechecked_after_waiting_for_send_lock(store, operation):
    client,key=store.clients.create('codex')
    identity=store.clients.authenticate(key)
    async def run():
        bridge=Bridge(store,httpx.MockTransport(lambda r:pytest.fail('revoked key must not send')))
        await bridge.lock.acquire()
        task=asyncio.create_task(bridge.send('hi','key','codex',identity=identity))
        await asyncio.sleep(0)
        getattr(store.clients, operation)(client['id'])
        bridge.lock.release()
        with pytest.raises(ClientError) as exc: await task
        assert exc.value.status == 401
        await bridge.close()
    asyncio.run(run())


def test_legacy_receipt_survives_client_namespace_migration(store):
    store.clients.seed({'codex':hashlib.sha256(b'old-key').hexdigest()})
    id=store.clients.authenticate('old-key')
    async def run():
        calls=[]
        bridge=Bridge(store,httpx.MockTransport(lambda r: calls.append(1) or httpx.Response(200,json={'ret':0})))
        await bridge.send('legacy','old-event','codex')
        assert (await bridge.send('legacy','old-event','codex',identity=id))['duplicate'] is True
        assert len(calls)==1
        await bridge.close()
    asyncio.run(run())


def test_pending_key_reply_and_identity_survive_restart_without_reexecuting(store,tmp_path):
    ingest(store,'/getkey codex')
    key=issued_key(store)
    other=Store(tmp_path/'clients.sqlite3',store.test_key)
    assert other.clients.authenticate(key).name=='codex'
    assert ingest(other,'/getkey codex')==0
    calls=[]
    async def run():
        bridge=Bridge(other,httpx.MockTransport(lambda r:calls.append(r.content) or httpx.Response(200,json={'ret':0})))
        assert (await bridge.command_once())['status']=='api_accepted'
        assert (await bridge.command_once())['status']=='idle'
        assert len(calls)==1 and key.encode() in calls[0]
        await bridge.close()
    try: asyncio.run(run())
    finally: other.close()


@pytest.mark.parametrize('disabled', [False, True])
def test_admin_delete_invalidates_key_preserves_history_and_allows_new_identity(store, disabled):
    bridge=Bridge(store,httpx.MockTransport(lambda r:httpx.Response(200,json={'ret':0})))
    app=create_app(bridge,{},False,admin_hash=hashlib.sha256(b'fixture-admin').hexdigest())
    with TestClient(app) as client:
        first=client.post('/admin/api/clients',headers=ADMIN,json={'name':'codex'}).json()
        id,key=first['client']['id'],first['api_key']
        auth={'Authorization':'Bearer '+key}
        other,other_key=store.clients.create('other')
        body={'text':'historic message','dedup_key':'original-event'}
        assert client.post('/api/messages',headers=auth,json=body).json()['status']=='api_accepted'
        ingest(store,'ordinary reply',100)
        before_account=store.account()
        before_inbox=store.inbox(0,20)
        before_outgoing=[tuple(row) for row in store.db.execute('SELECT * FROM outgoing')]
        endpoint=f'/admin/api/clients/{id}/delete'
        for headers in ({},{'Authorization':'Bearer incorrect'},auth):
            assert client.post(endpoint,headers=headers,json={}).status_code==401
        if disabled: store.clients.revoke(id)
        result=client.post(endpoint,headers=ADMIN,json={})
        assert result.status_code==200 and result.json()['client']['id']==id
        assert 'api_key' not in result.json() and 'key_hash' not in result.text
        assert client.get('/api/status',headers=auth).status_code==401
        assert client.post('/api/messages',headers=auth,json=body).status_code==401
        assert client.post(endpoint,headers=ADMIN,json={}).status_code==404
        assert [item['id'] for item in client.get('/admin/api/clients',headers=ADMIN).json()['clients']]==[other['id']]
        assert store.clients.authenticate(other_key).id==other['id']
        assert store.account()==before_account and store.inbox(0,20)==before_inbox
        assert [tuple(row) for row in store.db.execute('SELECT * FROM outgoing')]==before_outgoing
        new=client.post('/admin/api/clients',headers=ADMIN,json={'name':'codex'}).json()
        assert new['client']['id']!=id and new['api_key']!=key
        new_auth={'Authorization':'Bearer '+new['api_key']}
        assert client.get('/api/status',headers=new_auth).status_code==200
        assert client.get('/api/deliveries?dedup_key=original-event',headers=new_auth).json()['status']=='not_found'
        assert client.get('/api/status',headers=auth).status_code==401
    asyncio.run(bridge.close())


def test_delete_survives_restart_without_legacy_key_resurrection(store,tmp_path):
    registry={'codex':hashlib.sha256(b'fixture-old').hexdigest()}
    store.clients.seed(registry)
    identity=store.clients.authenticate('fixture-old')
    store.clients.delete(identity.id)
    other=Store(tmp_path/'clients.sqlite3',store.test_key)
    try:
        other.clients.seed(registry)
        assert other.clients.list()==[]
        with pytest.raises(ClientError): other.clients.authenticate('fixture-old')
        new,key=other.clients.create('codex')
        other.clients.seed(registry)
        assert new['id']!=identity.id and other.clients.authenticate(key).id==new['id']
        assert len(other.clients.list())==1
        with pytest.raises(ClientError): other.clients.authenticate('fixture-old')
    finally: other.close()


def test_delete_purges_queued_key_reply_without_blocking_other_commands(store):
    ingest(store,'/getkey codex')
    key=issued_key(store)
    id=store.clients.authenticate(key).id
    ingest(store,'/getkey gpt',2)
    kept_key=issued_key(store)
    store.clients.delete(id)
    deleted=store.db.execute('SELECT * FROM command_replies WHERE client_id=?',(id,)).fetchone()
    assert deleted['status']=='deleted' and deleted['encrypted_reply'] is None and deleted['issued_hash'] is None
    calls=[]
    async def run():
        bridge=Bridge(store,httpx.MockTransport(lambda r:calls.append(r.content) or httpx.Response(200,json={'ret':0})))
        assert (await bridge.command_once())['status']=='api_accepted'
        assert (await bridge.command_once())['status']=='idle'
        assert len(calls)==1 and key.encode() not in calls[0] and kept_key.encode() in calls[0]
        await bridge.close()
    asyncio.run(run())
