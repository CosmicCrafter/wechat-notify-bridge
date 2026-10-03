"""Real HTTP contract with mocked WeChat transport: auth, history and routing."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from wechat_bridge.app import create_app
from wechat_bridge.services.bridge import Bridge
from wechat_bridge.storage.database import Store
from wechat_bridge.services.commands import execute

ORIGIN = {'Origin':'https://testserver', 'X-Chat-Request':'1'}
ADMIN = {'Authorization':'Bearer fixture-admin'}


@pytest.fixture
def portal(tmp_path, monkeypatch):
    monkeypatch.setenv('WECHAT_PUBLIC_BASE_URL', 'https://testserver')
    key = Fernet.generate_key()
    store = Store(tmp_path/'db.sqlite3', key)
    store.bind(dict(bot_token='fixture',bot_id='fixture',user_id='owner',context_token='fixture',
                    base_url='https://ilinkai.weixin.qq.com',bound_at=time.time()))
    c,k=store.clients.create('codex'); g,gk=store.clients.create('gpt')
    chats=[store.conversations.register(c['id'],'one','开发'),store.conversations.register(c['id'],'two','监控')]
    calls=[]
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'ret':0})
    bridge=Bridge(store,httpx.MockTransport(handler))
    with TestClient(create_app(bridge,{},False,admin_hash=hashlib.sha256(b'fixture-admin').hexdigest()),base_url='https://testserver') as client:
        yield store,client,{'Authorization':'Bearer '+k},{'Authorization':'Bearer '+gk},chats,calls,key
    asyncio.run(bridge.close());store.close()


def login(client):
    code=client.post('/admin/api/chat/login-code',headers=ADMIN).json()['code']
    response=client.post('/chat/api/login',headers=ORIGIN,json={'code':code})
    assert response.status_code==200
    return response,code


def send(client,auth,cid,text='**更新**\n\n- 已完成',key='test-event',**kw):
    return client.post('/api/messages',headers=auth,json=dict(text=text,dedup_key=key,conversation_id=cid,**kw))


def test_private_auth_csrf_cookie_reuse_and_logout(portal):
    store,client,auth,_,chats,_,_=portal
    assert client.get('/chat/').status_code==200
    assert client.get('/chat/api/conversations').status_code==401
    assert client.get('/chat/api/conversations',headers=auth).status_code==401
    assert client.post('/admin/api/chat/login-code',headers=auth).status_code==401
    response,code=login(client)
    cookie=response.headers['set-cookie']
    for flag in ['HttpOnly','Secure','SameSite=strict','Path=/chat/']: assert flag in cookie
    assert client.post('/chat/api/login',headers=ORIGIN,json={'code':code}).status_code==401
    path='/chat/api/conversations/'+chats[0]['id']+'/messages'
    body={'text':'hello','request_id':'csrf-probe-123456'}
    for headers in ({},{'Origin':'https://evil.test','X-Chat-Request':'1'},{'Origin':'https://testserver'}):
        assert client.post(path,headers=headers,json=body).status_code==403
    assert client.get('/chat/api/conversations').status_code==200
    assert client.post('/chat/api/logout',headers=ORIGIN,json={}).status_code==200
    assert client.get('/chat/api/conversations').status_code==401
    assert code not in '\n'.join(store.db.iterdump())


def test_login_expiry_lockout_replacement_and_revocation(portal):
    store,client,_,_,_,_,_=portal
    code=store.portal.issue_code()
    wrong='00000000' if code!='00000000' else '11111111'
    for _ in range(6): assert client.post('/chat/api/login',headers=ORIGIN,json={'code':wrong}).status_code==401
    assert client.post('/chat/api/login',headers=ORIGIN,json={'code':code}).status_code==401
    code=store.portal.issue_code(); data=store.get('web_login');data['expires_at']=time.time()-1;store.set('web_login',data)
    assert client.post('/chat/api/login',headers=ORIGIN,json={'code':code}).status_code==401
    login(client)
    assert client.post('/admin/api/chat/revoke-sessions',headers=ADMIN).status_code==200
    assert client.get('/chat/api/conversations').status_code==401
    login(client);execute(store,'/logout')
    assert client.get('/chat/api/conversations').status_code==401


def test_web_reply_routes_once_without_touching_wechat_context_or_timer(portal):
    store,client,auth,gpt,chats,calls,_=portal;login(client)
    cid=chats[0]['id'];before=(store.account(),store.get('last_activity_at'),store.next_heartbeat())
    body={'text':'网页回复内容','request_id':'same-event-12345678'}
    path='/chat/api/conversations/'+cid+'/messages'
    a=client.post(path,headers=ORIGIN,json=body);assert a.status_code==200
    b=client.post(path,headers=ORIGIN,json=body)
    assert a.json()['message']['id']==b.json()['message']['id'] and b.json()['duplicate']
    assert client.post(path,headers=ORIGIN,json=dict(body,text='different')).status_code==409
    assert (store.account(),store.get('last_activity_at'),store.next_heartbeat())==before and not calls
    assert client.get('/api/inbox',headers=auth,params={'conversation_id':chats[1]['id']}).json()['messages']==[]
    assert client.get('/api/inbox',headers=gpt,params={'conversation_id':cid}).status_code==404
    assert client.get('/api/inbox',headers=auth).json()['messages']==[]
    inbox=client.get('/api/inbox',headers=auth,params={'conversation_id':cid}).json()
    assert len(inbox['messages'])==1 and inbox['messages'][0]['source']=='web'
    assert client.get(path).json()['messages'][0]['status']=='client_read'
    assert body['text'] not in '\n'.join(store.db.iterdump())


def test_outgoing_encrypted_full_history_link_receipt_and_duplicate(portal):
    store,client,auth,_,chats,calls,key=portal;login(client);cid=chats[0]['id']
    content='## 完整报告\n\n'+('非常长的内容。'*700)
    assert send(client,auth,cid,content,dry_run=True).json()['status']=='dry_run_ready'
    assert not calls and not store.db.execute('SELECT 1 FROM chat_messages').fetchone()
    response=send(client,auth,cid,content).json()
    assert response['status']=='api_accepted' and response['phone_delivery']=='unconfirmed'
    assert response['conversation_url'].startswith('https://testserver/chat/?c='+cid+'&m=')
    wire=calls[0]['msg']['item_list'][0]['text_item']['text']
    assert len(wire)<=2000 and response['conversation_url'] in wire and wire.startswith('[codex-开发]\n\n')
    assert send(client,auth,cid,content).json()['duplicate'] and len(calls)==1
    history=client.get('/chat/api/conversations/'+cid+'/messages').json()['messages']
    assert len(history)==1 and history[0]['text']==content and history[0]['status']=='api_accepted'
    assert content not in '\n'.join(store.db.iterdump())
    assert client.get('/chat/api/conversations').json()['conversations'][0]['unread']==1
    client.post('/chat/api/conversations/'+cid+'/read',headers=ORIGIN,json={'message_id':history[0]['id']})
    assert client.get('/chat/api/conversations').json()['conversations'][0]['unread']==0
    # A restart neither duplicates records nor loses encrypted bodies.
    reopened=Store(store.db.execute('PRAGMA database_list').fetchone()[2],key)
    try: assert reopened.portal.history(cid)['messages'][0]['text']==content
    finally: reopened.close()


def test_failed_wechat_delivery_still_has_body_and_does_not_retry(portal):
    store,client,auth,_,chats,_,_=portal;login(client)
    bridge=client.app.state.bridge
    asyncio.run(bridge.http.aclose())
    calls=[]
    bridge.http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:calls.append(r) or httpx.Response(200,json={'ret':-2})))
    cid=chats[0]['id'];receipt=send(client,auth,cid).json()
    assert receipt['status']=='api_rejected'
    assert send(client,auth,cid).json()['duplicate'] and len(calls)==1
    assert client.get('/chat/api/conversations/'+cid+'/messages').json()['messages'][0]['status']=='api_rejected'


def test_timeline_paging_anchor_isolation_closed_and_deleted_chat(portal):
    store,client,auth,_,chats,_,_=portal;login(client);cid=chats[0]['id'];other=chats[1]['id']
    for i in range(60):store.portal.add(cid,'assistant','api',f'第{i}条','api_accepted')
    different=store.portal.add(other,'assistant','api','other','api_accepted')
    path='/chat/api/conversations/'+cid+'/messages'
    page=client.get(path).json();assert len(page['messages'])==50 and page['has_older']
    first=page['messages'][0]['id'];old=client.get(path,params={'before':first}).json()
    assert len(old['messages'])==10 and not old['has_older'] and old['has_newer']
    assert client.get(path,params={'around':30}).json()['messages'][0]['id']<30
    assert client.get(path,params={'around':different}).status_code==404
    assert client.post('/chat/api/conversations/'+cid+'/read',headers=ORIGIN,json={'message_id':different}).status_code==404
    owner=store.clients.authenticate(auth['Authorization'][7:]);store.clients.delete(owner.id)
    assert client.get(path).status_code==200
    assert not client.get(path).json()['conversation']['active']
    assert client.post(path,headers=ORIGIN,json={'text':'closed','request_id':'closed-test-123456'}).status_code==409


def test_command_format_privacy_and_migration(portal):
    store,client,auth,_,chats,calls,key=portal
    for text in ['/help','/status','/list','/chats','/getkey test','/rename test renamed','/revoke renamed','/resetkey renamed','/unknown','/web']:
        reply=execute(store,text).text
        assert reply.startswith('## ') and len(reply)<1750
    assert '北京时间' not in execute(store,'/status').text
    cid=chats[0]['id'];now=time.time()
    # Simulate direct inbound preserved by the previous version.
    store.db.execute("INSERT INTO inbox(identity,received_at,message_at,encrypted,kind,conversation_id,route_status) VALUES ('old',?,?,?,'message',?,'direct')",
        (now,now,store.cipher.encrypt(json.dumps({'text':'old inbound'}).encode()),cid))
    reopened=Store(store.db.execute('PRAGMA database_list').fetchone()[2],key)
    try:
        assert [m['text'] for m in reopened.portal.history(cid)['messages']]==['old inbound']
        assert reopened.portal.history(cid)['messages'][0]['status']=='legacy'
        reopened.inbox(0, 20, cid)
        assert reopened.portal.history(cid)['messages'][0]['status']=='client_read'
        assert reopened.portal.history(chats[1]['id'])['messages']==[]
    finally:reopened.close()


def test_assets_and_csp_and_admin_excluded_from_client_schema(portal):
    _,client,auth,_,_,_,_=portal
    for asset in ('app.js','style.css','marked.js','purify.js'):
        assert client.get('/chat/assets/'+asset).status_code==200
    assert client.get('/chat/assets/vendor-lock.json').status_code==404
    response=client.get('/chat/')
    assert response.headers['cache-control']=='no-store'
    assert "script-src 'self'" in response.headers['content-security-policy']
    schema=client.get('/openapi.json',headers=auth).json()
    assert all(not p.startswith(('/chat/','/admin/')) for p in schema['paths'])


def test_archive_names_readonly_restore_and_delete(portal):
    from wechat_bridge.services.portal import Portal
    from wechat_bridge.storage.client_registry import ClientError
    store,client,auth,_,chats,calls,_=portal
    cid=chats[0]['id'];client_id=store.conversations.get(store.clients.authenticate(auth['Authorization'][7:]).id,cid)['client_id']
    path='/chat/api/conversations/'+cid
    assert client.post(path+'/delete',headers=ORIGIN,json={}).status_code==401
    login(client)
    assert client.post(path+'/delete',json={}).status_code==403
    assert client.post(path+'/archive',json={'archived':True}).status_code==403
    send(client,auth,cid,text='retained archive',key='archive-send')
    r=client.post(path+'/messages',headers=ORIGIN,json={'text':'private body','request_id':'delete-request-123456'})
    assert r.status_code==200
    assert client.post(path+'/archive',headers=ORIGIN,json={'archived':True}).status_code==200
    assert client.get(path+'/messages').json()['conversation']['archived']
    assert client.post(path+'/messages',headers=ORIGIN,json={'text':'blocked','request_id':'archive-block-12345'}).status_code==409
    assert send(client,auth,cid,key='closed-send').status_code==409
    other=store.conversations.register(client_id,'replacement','开发')
    assert other['name']=='开发'
    assert client.post(path+'/archive',headers=ORIGIN,json={'archived':False}).json()['detail']=='conversation_name_conflict'
    store.conversations.set_active(client_id,other['id'],False)
    assert client.post(path+'/archive',headers=ORIGIN,json={'archived':False}).status_code==200
    assert len(client.get(path+'/messages').json()['messages'])==2
    assert client.post(path+'/delete',headers=ORIGIN,json={}).json()['messages_removed']==2
    assert client.post(path+'/delete',headers=ORIGIN,json={}).status_code==200
    assert client.get(path+'/messages').status_code==404
    assert send(client,auth,cid,key='deleted-send').status_code==404
    assert cid not in [x['id'] for x in client.get('/chat/api/conversations').json()['conversations']]
    row=store.db.execute('SELECT kind,encrypted FROM inbox WHERE conversation_id=?',(cid,)).fetchone()
    assert row['kind']=='deleted' and json.loads(store.cipher.decrypt(row['encrypted']))=={}
    Portal(store)
    assert store.db.execute('SELECT count(*) FROM chat_messages WHERE conversation_id=?',(cid,)).fetchone()[0]==0
    with pytest.raises(ClientError):store.conversations.register(client_id,'one','开发')
    assert store.conversations.register(client_id,'replacement2','开发')['name']=='开发'


def test_legacy_conversation_name_migration():
    import sqlite3
    from wechat_bridge.storage.conversations import Conversations
    db=sqlite3.connect(':memory:',isolation_level=None);db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE conversations(id TEXT PRIMARY KEY,client_id TEXT NOT NULL,conversation_key TEXT NOT NULL,name TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created_at REAL NOT NULL,UNIQUE(client_id,conversation_key),UNIQUE(client_id,name))')
    db.execute("INSERT INTO conversations VALUES ('a','c','one','same',0,1)")
    Conversations(db)
    db.execute("INSERT INTO conversations(id,client_id,conversation_key,name,active,created_at) VALUES ('b','c','two','same',1,2)")
    with pytest.raises(sqlite3.IntegrityError):db.execute("INSERT INTO conversations(id,client_id,conversation_key,name,active,created_at) VALUES ('d','c','three','same',1,3)")
    Conversations(db)
    assert db.execute('SELECT count(*) FROM conversations').fetchone()[0]==2
    db.close()
