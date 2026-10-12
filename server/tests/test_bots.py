"""Multiple bot isolation and key grants through public HTTP contracts."""
import json
import time

import httpx
import pytest

from test_portal import portal,ADMIN
from test_feishu import CONFIG,callback,event
from wechat_bridge.storage.database import Store
from wechat_bridge.services.bridge import BridgeError
from wechat_bridge.services.portal import Portal


def bot(portal,platform,name):
    response=portal[1].post('/admin/api/bots',headers=ADMIN,json=dict(name=name,platform=platform))
    assert response.status_code==200,response.text
    return response.json()['id']


def grants(portal,ids,default=None):
    store,client,auth,*_=portal
    identity=store.clients.authenticate(auth['Authorization'][7:])
    return client.post(f'/admin/api/clients/{identity.id}/bots',headers=ADMIN,json=dict(bot_ids=ids,default_bot_id=default))


def wechat(portal,name='微信B'):
    id=bot(portal,'wechat',name)
    bridge=portal[1].app.state.channels.adapter(id)
    bridge.store.bind(dict(bot_token='fixture-'+id,bot_id='upstream-'+id,user_id='owner-'+id,context_token='context-'+id,
                          context_received_at=time.time(),base_url='https://ilinkai.weixin.qq.com',bound_at=time.time()))
    calls=[]
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'ret':0})
    # The adapter has not made a request yet; replace its test-only transport.
    bridge.http._transport=httpx.MockTransport(handler)
    bridge.http._mounts={}
    return id,bridge,calls


def send(portal,id=None,key='multi-event',**extra):
    body=dict(text='通知',conversation_id=portal[4][0]['id'],dedup_key=key,**extra)
    if id:body['bot_id']=id
    return portal[1].post('/api/messages',headers=portal[2],json=body)


def test_key_grants_default_selection_and_denial_precede_network(portal):
    id,bridge,calls=wechat(portal)
    assert send(portal,id).status_code==403 and not calls
    assert grants(portal,[id],id).status_code==200
    result=send(portal).json()
    assert result['status']=='api_accepted' and result['bot_id']==id
    assert calls[0]['msg']['to_user_id']==bridge.store.account()['user_id']
    assert send(portal,'default').status_code==403
    identity=portal[1].get('/api/status',headers=portal[2]).json()
    assert [item['id'] for item in identity['bots']]==[id] and identity['default_bot_id']==id
    assert 'accepted_sends_since_context' not in identity
    assert grants(portal,[],None).status_code==200
    assert send(portal,id).status_code==403
    assert portal[1].get('/api/deliveries',headers=portal[2],params=dict(bot_id=id,dedup_key='multi-event',conversation_id=portal[4][0]['id'])).status_code==403


def test_bot_outgoing_context_dedup_and_heartbeat_are_separate(portal):
    store=portal[0]
    id,bridge,calls=wechat(portal)
    assert grants(portal,['default',id],'default').status_code==200
    old_account=store.account();old_activity=store.get('last_activity_at')
    first=send(portal,id).json();duplicate=send(portal,id).json()
    assert duplicate['duplicate'] and first['message_id']==duplicate['message_id'] and len(calls)==1
    assert store.account()==old_account and store.get('last_activity_at')==old_activity
    assert bridge.store.send_diagnostics.context()['accepted_sends_since_context']==1
    assert send(portal,'default').json()['status']=='api_accepted'
    assert len(portal[5])==1 and len(calls)==1
    assert bridge.store.send_diagnostics.context()['accepted_sends_since_context']==1
    root_receipt=portal[1].get('/api/deliveries',headers=portal[2],params=dict(bot_id='default',dedup_key='multi-event',conversation_id=portal[4][0]['id'])).json()
    assert root_receipt['message_id']!=first['message_id']


def test_wechat_incoming_same_message_ids_are_bot_scoped_and_acl_filters_reads(portal):
    store,client,auth,_,chats,*_=portal
    id,bridge,_=wechat(portal)
    assert grants(portal,['default',id],'default').status_code==200
    def update(owner,context):
        return {'msgs':[dict(from_user_id=owner,message_type=1,message_state=2,message_id='same-id',
            context_token=context,create_time_ms=int(time.time()*1000),item_list=[dict(type=1,text_item={'text':'[codex-开发] 回复'})])]}
    store.ingest(update(store.account()['user_id'],'default-new-context'),time.time())
    bridge.store.ingest(update(bridge.store.account()['user_id'],'new-bot-context'),time.time())
    messages=client.get('/api/inbox',headers=auth,params={'conversation_id':chats[0]['id']}).json()['messages']
    assert len(messages)==2 and {m['bot_id'] for m in messages}=={'default',id}
    assert store.account()['context_token']=='default-new-context'
    assert bridge.store.account()['context_token']=='new-bot-context'
    assert grants(portal,[id],id).status_code==200
    messages=client.get('/api/inbox',headers=auth,params={'conversation_id':chats[0]['id']}).json()['messages']
    assert len(messages)==1 and messages[0]['bot_id']==id
    events=client.get('/api/wake/events',headers=auth,params={'conversation_id':chats[0]['id'],'after_id':0}).json()['events']
    assert [e['id'] for e in events]==[messages[0]['id']]
    store.ingest(update(store.account()['user_id'],'default-new-context'),time.time())
    assert store.inbox(0,20,chats[0]['id'])[0]['bot_id']=='default'


def test_invalid_grants_are_atomic_and_no_implicit_broadcast(portal):
    id,_,calls=wechat(portal)
    assert grants(portal,[id],'default').status_code==422
    assert grants(portal,[id,id],id).status_code==422
    assert grants(portal,['missing'],'missing').status_code==404
    assert grants(portal,['default',id],None).status_code==200
    assert send(portal).status_code==409 and not calls and not portal[5]
    assert send(portal,id,channel='feishu').status_code==422
    assert send(portal,id).json()['status']=='api_accepted' and len(calls)==1 and not portal[5]


def test_new_key_creation_and_scopes_commit_together(portal):
    id,_,_=wechat(portal)
    client=portal[1]
    bad=client.post('/admin/api/clients',headers=ADMIN,json=dict(name='invalid-new-key',bot_ids=[id],default_bot_id='default'))
    assert bad.status_code==422
    assert all(row['name']!='invalid-new-key' for row in portal[0].clients.list())
    created=client.post('/admin/api/clients',headers=ADMIN,json=dict(name='monitor',bot_ids=[id],default_bot_id=id)).json()
    identity=client.get('/api/status',headers={'Authorization':'Bearer '+created['api_key']}).json()
    assert identity['bot_ids']==[id] and identity['default_bot_id']==id


def test_multiple_feishu_bots_do_not_cross_send_or_callbacks(portal):
    store,client,auth,_,chats,*_=portal
    a,b=bot(portal,'feishu','飞书A'),bot(portal,'feishu','飞书B')
    for id,app in ((a,CONFIG['app_id']),(b,'cli_second')):
        adapter=client.app.state.channels.adapter(id)
        adapter.configure(dict(CONFIG,app_id=app))
        def handler(request,id=id):
            if request.url.path.endswith('/internal'):
                return httpx.Response(200,json=dict(code=0,tenant_access_token='token-'+id,expire=7200))
            return httpx.Response(200,json=dict(code=0,data={'message_id':'om_'+id}))
        adapter.transport=httpx.MockTransport(handler)
    assert grants(portal,[a,b],a).status_code==200
    first=send(portal,a).json();second=send(portal,b).json()
    assert first['bot_id']==a and second['bot_id']==b and first['message_id']!=second['message_id']
    assert send(portal,a).json()['duplicate'] and send(portal,b).json()['duplicate']
    with pytest.raises(BridgeError,match='feishu_owner_mismatch'):
        client.app.state.channels.adapter(b).configure(dict(CONFIG))
    unbound=bot(portal,'feishu','飞书C')
    with pytest.raises(BridgeError,match='bot_binding_conflict'):
        client.app.state.channels.adapter(unbound).configure(dict(CONFIG))


def test_bot_metadata_and_encrypted_binding_survive_restart(portal):
    store,client,auth,*_=portal
    id,bridge,_=wechat(portal)
    grants(portal,[id],id)
    clone=Store(store.db.execute('PRAGMA database_list').fetchone()['file'],portal[-1])
    try:
        identity=clone.clients.authenticate(auth['Authorization'][7:])
        assert clone.bots.grants(identity.id)['default_bot_id']==id
        assert 'context-'+id not in '\n'.join(clone.db.iterdump())
    finally:clone.close()


def test_bot_disable_keeps_records_and_prevents_new_calls(portal):
    id,_,calls=wechat(portal)
    grants(portal,[id],id)
    sent=send(portal,id).json()
    assert portal[1].post('/admin/api/bots/'+id,headers=ADMIN,json=dict(name='微信B',enabled=False)).status_code==200
    assert send(portal,id,key='next').status_code==409 and len(calls)==1
    status=portal[1].get('/api/status',headers=portal[2]).json()['bots'][0]['status']
    assert status['connection_status']=='disabled' and status['next_heartbeat_at'] is None
    receipt=portal[1].get('/api/deliveries',headers=portal[2],params=dict(bot_id=id,dedup_key='multi-event',conversation_id=portal[4][0]['id'])).json()
    assert receipt['message_id']==sent['message_id']


def test_recovered_history_preserves_bot_and_platform(portal):
    store=portal[0]
    id=bot(portal,'feishu','恢复测试')
    cid=portal[4][0]['id']
    payload=store.cipher.encrypt(json.dumps({'text':'历史恢复'}).encode())
    for identity,bot_id in (('restore-feishu',id),('restore-wechat','default'),('restore-web',None)):
        store.db.execute("INSERT INTO inbox(identity,received_at,message_at,encrypted,kind,conversation_id,route_status,bot_id) "
                         "VALUES (?,?,?,?,'message',?,'direct',?)",(identity,time.time(),time.time(),payload,cid,bot_id))
    Portal(store)
    rows=store.db.execute('SELECT source,bot_id FROM chat_messages WHERE inbox_id IN '
                          "(SELECT id FROM inbox WHERE identity LIKE 'restore-%') ORDER BY inbox_id").fetchall()
    assert [tuple(row) for row in rows]==[('feishu',id),('wechat','default'),('web',None)]
