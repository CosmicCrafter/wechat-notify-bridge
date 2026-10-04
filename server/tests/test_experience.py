"""Owner UX: pending is not unread, stable renames, and small typed forms."""
import hashlib
import time

from test_portal import portal, login, ORIGIN, send
from test_task_cards import create, answer


def test_pending_inbox_is_read_only_paginated_and_filtered(portal):
    store, client, auth, other, chats, calls, _ = portal
    assert client.get('/chat/api/tasks').status_code == 401
    cards = [create(portal, dedup_key='pending-'+str(n), conversation_id=chats[n % 2]['id'])[1]['task'] for n in range(4)]
    login(client)
    first = client.get('/chat/api/tasks?limit=2').json()
    assert [v['task']['id'] for v in first['tasks']] == [cards[3]['id'], cards[2]['id']]
    second = client.get('/chat/api/tasks', params={'limit':2,'before':first['next_before']}).json()
    assert [v['task']['id'] for v in second['tasks']] == [cards[1]['id'], cards[0]['id']]
    assert second['next_before'] is None
    assert len(client.get('/chat/api/tasks?q=监控').json()['tasks']) == 2
    assert client.get('/chat/api/tasks?q=%').json()['tasks'] == []
    assert len(client.get('/chat/api/tasks?q=CODEX').json()['tasks']) == 4
    assert store.db.execute("SELECT count(*) FROM inbox WHERE identity LIKE 'task:%'").fetchone()[0] == 0
    cid = cards[0]['conversation_id']
    client.post(f'/chat/api/conversations/{cid}/read', headers=ORIGIN, json={'message_id':10000})
    assert sum(c['pending_tasks'] for c in client.get('/chat/api/conversations').json()['conversations']) == 4
    answer(portal, cards[0])
    store.db.execute('UPDATE task_cards SET expires_at=? WHERE id=?', (time.time()-1, cards[1]['id']))
    client.post(f"/api/conversations/{cid}/tasks/{cards[2]['id']}/state", headers=auth, json={'status':'cancelled'})
    assert [v['task']['id'] for v in client.get('/chat/api/tasks').json()['tasks']] == [cards[3]['id']]
    client.post(f"/chat/api/conversations/{cards[3]['conversation_id']}/archive", headers=ORIGIN, json={'archived':True})
    assert client.get('/chat/api/tasks').json()['tasks'] == []
    assert len(calls) == 4


def test_pin_rename_csrf_stable_identity_and_name_rules(portal):
    store, client, auth, _, chats, _, _ = portal
    cid = chats[0]['id'];prefix = f'/chat/api/conversations/{cid}'
    response = send(client,auth,cid).json();login(client)
    for suffix, body in [('pin',{'pinned':True}),('rename',{'name':'新名字'})]:
        assert client.post(prefix+'/'+suffix,json=body).status_code == 403
    assert client.post(prefix+'/pin',headers=ORIGIN,json={'pinned':True}).status_code == 200
    listed = client.get('/chat/api/conversations').json()
    assert listed['conversations'][0]['id'] == cid and listed['conversations'][0]['pinned']
    scope = listed['draft_scope']
    assert client.post(prefix+'/rename',headers=ORIGIN,json={'name':'监控'}).status_code == 409
    assert client.post(prefix+'/rename',headers=ORIGIN,json={'name':'bad name'}).status_code == 422
    renamed = client.post(prefix+'/rename',headers=ORIGIN,json={'name':'NEW名字'}).json()['conversation']
    assert renamed['id'] == cid and renamed['name'] == 'new名字'
    assert store.conversations.register(store.conversations.rows()[0]['client_id'],'one','ignored')['id'] == cid
    assert store.conversations.resolve('codex-new名字') == (cid,'direct')
    assert store.conversations.resolve('codex-开发') == (None,'unknown')
    history = client.get(prefix+'/messages',params={'around':response['message_id']}).json()
    assert history['conversation']['name'] == 'new名字' and len(history['messages']) == 1
    assert client.get('/chat/api/conversations').json()['draft_scope'] == scope
    client.post(prefix+'/archive',headers=ORIGIN,json={'archived':True})
    assert client.post(prefix+'/rename',headers=ORIGIN,json={'name':'监控'}).status_code == 200
    assert client.post(prefix+'/archive',headers=ORIGIN,json={'archived':False}).status_code == 409
    client.post(prefix+'/delete',headers=ORIGIN,json={})
    assert store.db.execute('SELECT count(*) FROM web_preferences WHERE conversation_id=?',(cid,)).fetchone()[0] == 0


def form_fields():
    return [dict(id='name',label='名字'),dict(id='region',label='环境',type='select',options=[dict(id='test',label='测试'),dict(id='live',label='生产')]),
            dict(id='amount',label='数量',type='number'),dict(id='date',label='日期',type='date',required=False)]


def test_form_validation_canonical_retry_and_inbox(portal):
    store,client,auth,other,chats,calls,_ = portal
    _,sent = create(portal,mode='form',options=[],fields=form_fields());card=sent['task'];login(client)
    values={'name':'通知桥 <script>','region':'test','amount':'01.20','date':'2026-10-04'}
    for invalid in ({}, {**values,'region':'unknown'}, {**values,'amount':'NaN'}, {**values,'amount':'1e4'}, {**values,'date':'2026-02-30'}, {**values,'extra':'bad'}):
        r=answer(portal,card,choice_id=None,field_values=invalid)
        assert r.status_code == 422
    assert answer(portal,card,field_values=values).status_code == 422
    result=answer(portal,card,choice_id=None,field_values=values).json()
    assert result['task']['answer']['field_values'] == {**values,'amount':'1.2'}
    assert result['task']['answer']['fields'][1]['value'] == '测试'
    assert answer(portal,card,choice_id=None,field_values={**values,'amount':'1.200'}).json()['duplicate']
    assert answer(portal,card,choice_id=None,field_values={**values,'name':'changed'}).status_code == 409
    inbox=client.get('/api/inbox',headers=auth,params={'conversation_id':card['conversation_id']}).json()['messages']
    assert len(inbox)==1 and inbox[0]['task_response']['field_values']['amount']=='1.2'
    assert '环境：测试' in inbox[0]['text']
    assert client.get(f"/api/conversations/{card['conversation_id']}/tasks/{card['id']}",headers=other).status_code == 404
    assert len(calls)==1


def test_form_definition_rejects_incompatible_fields(portal):
    _,client,auth,_,chats,_,_=portal
    base=dict(conversation_id=chats[0]['id'],dedup_key='bad-form',title='表单',prompt='填写',mode='form',fields=form_fields())
    for changed in ({'fields':[]},{'fields':form_fields()*2},{'allow_custom':True},{'options':[dict(id='a',label='A'),dict(id='b',label='B')]},
                    {'fields':[dict(id='x',label=' ',type='text')]},{'fields':[dict(id='x',label='选项',type='select')]},{'mode':'input'}):
        assert client.post('/api/task-cards',headers=auth,json={**base,**changed}).status_code == 422


def test_wire_presentation_does_not_change_canonical_notification_hash(portal):
    store,client,auth,_,chats,calls,_=portal
    body=dict(conversation_id=chats[0]['id'],task='测试提醒',reason='遇到问题',need_user='检查配置',dedup_key='styled')
    r=client.post('/api/notifications',headers=auth,json=body).json()
    canonical='## 需要处理 · 测试提醒\n\n**当前情况**\n\n遇到问题\n\n**需要你处理**\n\n检查配置'
    assert store.client_receipt('styled',store.clients.authenticate(auth['Authorization'][7:]),chats[0]['id'])['message_hash']==hashlib.sha256(canonical.encode()).hexdigest()
    wire=calls[-1]['msg']['item_list'][0]['text_item']['text']
    assert '⚠️ 测试提醒' in wire and '**需要你的帮助**' in wire
    assert wire.endswith('[查看对话并回复 →](' + r['conversation_url'] + ')')
    footer = wire.rsplit('\n\n---\n\n', 1)[1].lstrip('\u3000')
    assert footer.startswith('(未知/10) [查看对话并回复 →](') and '\n' not in footer
    assert client.post('/api/notifications',headers=auth,json=body).json()['duplicate']
