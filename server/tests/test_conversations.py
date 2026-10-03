"""Chat naming, per-chat receipts and exact-tag inbox routing; no live WeChat."""
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
from wechat_bridge.storage.client_registry import ClientError
from wechat_bridge.services.commands import execute
from wechat_bridge.services.bridge import Bridge
from wechat_bridge.storage.database import Store


@pytest.fixture
def setup(tmp_path):
    key=Fernet.generate_key()
    store=Store(tmp_path/'test.sqlite3',key)
    store.bind(dict(bot_token='fixture-bot',bot_id='fixture',user_id='owner',context_token='fixture-context',
                    base_url='https://ilinkai.weixin.qq.com',bound_at=time.time()))
    first,first_key=store.clients.create('codex')
    second,second_key=store.clients.create('gpt')
    calls=[]
    bridge=Bridge(store,httpx.MockTransport(lambda r:calls.append(json.loads(r.content)) or httpx.Response(200,json={'ret':0})))
    app=create_app(bridge,{},False,admin_hash=hashlib.sha256(b'fixture-admin').hexdigest())
    with TestClient(app) as client:
        yield store,client,{'Authorization':'Bearer '+first_key},{'Authorization':'Bearer '+second_key},calls,key
    asyncio.run(bridge.close())
    store.close()


def register(client,auth,stable,name=None):
    response=client.post('/api/conversations',headers=auth,json={'conversation_key':stable,'name':name})
    assert response.status_code==200
    return response.json()


def ingest(store,text,id):
    return store.ingest({'msgs':[dict(message_id=id,seq=id,from_user_id='owner',message_type=1,message_state=2,
        create_time_ms=int(time.time()*1000),item_list=[{'type':1,'text_item':{'text':text}}])]},time.time())


def test_wake_events_are_scoped_and_never_mark_read(setup):
    store,client,auth,gpt,_,_=setup
    chat=register(client,auth,'wake-thread','唤醒')
    other=register(client,auth,'other-thread','其他')
    url='/api/wake/events'
    assert client.get(url,params={'conversation_id':chat['id']}).status_code==401
    assert client.get(url,headers=gpt,params={'conversation_id':chat['id']}).status_code==404
    assert client.get(url,headers=auth).status_code==422
    ingest(store,'[codex-唤醒] old',201)
    cursor=client.get(url,headers=auth,params={'conversation_id':chat['id']}).json()
    assert cursor['events']==[] and cursor['next_after_id']>0
    ingest(store,'[codex-唤醒] new',202)
    ingest(store,'[codex-其他] not this chat',203)
    ingest(store,'unaddressed',204)
    before=[tuple(r) for r in store.db.execute('SELECT id,status FROM chat_messages')]
    result=client.get(url,headers=auth,params={'conversation_id':chat['id'],'after_id':cursor['next_after_id']}).json()
    assert len(result['events'])==1 and set(result['events'][0])=={'id'}
    assert [tuple(r) for r in store.db.execute('SELECT id,status FROM chat_messages')]==before
    client.post('/api/conversations/'+chat['id']+'/state',headers=auth,json={'active':False})
    assert client.get(url,headers=auth,params={'conversation_id':chat['id']}).status_code!=200


def test_registration_names_count_scope_lifecycle_and_restart(setup,tmp_path):
    store,client,auth,gpt,_,key=setup
    first=register(client,auth,'thread-1','tibo')
    assert first['name']=='tibo' and first['display_tag']=='[codex]' and first['reply_tag']=='[codex-tibo]'
    assert register(client,auth,'thread-1','other')['id']==first['id']
    second=register(client,auth,'thread-2','tibo')
    assert second['name']=='tibo-2'
    third=register(client,auth,'thread-3')
    assert third['name']=='1'
    status=client.get('/api/status',headers=auth).json()
    assert status['conversation_count']==3
    assert [c['display_tag'] for c in status['conversations']]==['[codex-tibo]','[codex-tibo-2]','[codex-1]']
    assert client.get('/api/conversations',headers=gpt).json()['conversations']==[]
    for chat in (second,third):
        assert client.post('/api/conversations/'+chat['id']+'/state',headers=auth,json={'active':False}).status_code==200
    assert client.get('/api/status',headers=auth).json()['conversations'][0]['display_tag']=='[codex]'
    assert len(client.get('/api/conversations?include_closed=true',headers=auth).json()['conversations'])==3
    other=Store(tmp_path/'test.sqlite3',key)
    try:
        owner=store.clients.authenticate(auth['Authorization'][7:])
        assert other.conversations.register(owner.id,'thread-1')['id']==first['id']
        assert len(other.conversations.list(owner.id))==1
    finally: other.close()
    assert client.post('/api/conversations/'+second['id']+'/state',headers=auth,json={'active':True}).status_code==200
    assert client.get('/api/status',headers=auth).json()['conversation_count']==2


@pytest.mark.parametrize('key,name',[('',None),('bad key',None),('ok','<bad>'),('ok','two words')])
def test_registration_rejects_invalid_names_and_keys(setup,key,name):
    _,client,auth,_,_,_=setup
    assert client.post('/api/conversations',headers=auth,json={'conversation_key':key,'name':name}).status_code==422


def test_direct_inbox_never_crosses_chat_or_api_key_and_ambiguous_tags_stay_unassigned(setup):
    store,client,auth,gpt,_,_=setup
    a=register(client,auth,'one','tibo')
    b=register(client,auth,'two','开发')
    c=register(client,gpt,'one','写作')
    for id,text in enumerate(['[codex-tibo] 给 tibo','[codex-开发] 给开发','[gpt] 给 GPT',
                              '[codex] 不明确','[不存在] 不明确','公共消息','/help'],1):
        ingest(store,text,id)
    def inbox(headers,**params):
        response=client.get('/api/inbox',headers=headers,params=params)
        assert response.status_code==200
        return response.json()
    messages=inbox(auth,conversation_id=a['id'])
    assert [m['text'] for m in messages['messages']]==['给 tibo']
    assert messages['messages'][0]['route_status']=='direct'
    assert inbox(auth,conversation_id=a['id'],after_id=messages['next_after_id'])['messages']==[]
    assert [m['text'] for m in inbox(auth,conversation_id=b['id'])['messages']]==['给开发']
    assert [m['text'] for m in inbox(gpt,conversation_id=c['id'])['messages']]==['给 GPT']
    assert [m['route_status'] for m in inbox(auth)['messages']]==['ambiguous','unknown','shared']
    assert len(inbox(auth,conversation_id=a['id'],include_unaddressed=True)['messages'])==4
    for path in ['/api/inbox?conversation_id='+a['id'], '/api/deliveries?dedup_key=x&conversation_id='+a['id']]:
        assert client.get(path,headers=gpt).status_code==404
    assert client.post('/api/conversations/'+a['id']+'/state',headers=gpt,json={'active':False}).status_code==404
    assert '[codex-tibo]' in execute(store,'/chats').text and '[gpt-写作]' in execute(store,'/chats').text


def test_labels_and_receipts_follow_chat_identity_and_never_resend_when_label_changes(setup):
    _,client,auth,gpt,calls,_=setup
    a=register(client,auth,'one','tibo')
    def send(chat,headers=auth):
        return client.post('/api/messages',headers=headers,json={'text':'one event','dedup_key':'same','conversation_id':chat})
    assert send(a['id']).json()['status']=='api_accepted'
    assert calls[-1]['msg']['item_list'][0]['text_item']['text']=='[codex]\n\none event'
    b=register(client,auth,'two','开发')
    assert send(a['id']).json()['duplicate'] is True
    assert len(calls)==1
    assert client.get('/api/deliveries',headers=auth,params={'dedup_key':'same','conversation_id':b['id']}).json()['status']=='not_found'
    assert send(b['id']).json()['status']=='api_accepted'
    assert calls[-1]['msg']['item_list'][0]['text_item']['text']=='[codex-开发]\n\none event'
    assert send(None).json()['detail']=='conversation_required'
    assert send(a['id'],gpt).status_code==404
    assert len(calls)==2
    assert client.post('/api/conversations/'+b['id']+'/state',headers=auth,json={'active':False}).status_code==200
    assert send(b['id']).json()['detail']=='conversation_closed'
    assert client.get('/api/deliveries',headers=auth,params={'dedup_key':'same','conversation_id':b['id']}).json()['status']=='api_accepted'


def test_client_rename_revoke_delete_and_tag_collision_are_safe(setup):
    store,client,auth,gpt,calls,_=setup
    a=register(client,auth,'one','tibo')
    owner=store.clients.authenticate(auth['Authorization'][7:])
    store.clients.rename(owner.id,'dev')
    assert client.get('/api/status',headers=auth).json()['conversations'][0]['reply_tag']=='[dev-tibo]'
    ingest(store,'[codex-tibo] old tag',1)
    assert store.inbox(0,20)[0]['route_status']=='unknown'
    store.clients.revoke(owner.id)
    assert store.conversations.resolve('dev-tibo')==(None,'unknown')
    store.clients.delete(owner.id)
    assert client.get('/api/status',headers=auth).status_code==401
    assert store.db.execute('SELECT active FROM conversations WHERE id=?',(a['id'],)).fetchone()[0]==0
    x,_=store.clients.create('x')
    xy,_=store.clients.create('x-y')
    first=store.conversations.register(x['id'],'one','y')
    store.conversations.register(xy['id'],'one','z')
    # [x-y] can be a full chat tag or another client's base: do not guess.
    assert store.conversations.resolve('x-y')==(None,'ambiguous')
    assert store.conversations.label(x['id'],first['id'])=='[x]'
