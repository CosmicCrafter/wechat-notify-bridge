"""Optional interaction modes, legacy retries, and one-answer routing contracts."""
import hashlib
import json
import uuid

import pytest

from test_portal import portal, login, ORIGIN
from test_task_cards import create, answer


def test_multiple_limits_notes_and_order_independent_retry(portal):
    store, client, auth, _, _, calls, _ = portal
    options = [{'id':id,'label':label} for id,label in [('fix','修复'),('test','测试'),('docs','文档')]]
    _, sent = create(portal, mode='multiple', options=options, min_choices=2, max_choices=2)
    card = sent['task'];login(client)
    for choice_ids, detail in [(['fix'],'task_choice_limit'), (['fix','test','docs'],'task_choice_limit'),
                                (['fix','fix'],'invalid_task_choice'), (['missing'],'invalid_task_choice')]:
        response = answer(portal, card, choice_id=None, choice_ids=choice_ids)
        assert response.status_code == 422 and response.json()['detail'] == detail
    assert store.db.execute("SELECT count(*) FROM inbox WHERE identity LIKE 'task:%'").fetchone()[0] == 0
    note = '先修复和测试，文档稍后更新。'
    response = answer(portal, card, choice_id=None, choice_ids=['test','fix'], text=note)
    assert response.status_code == 200
    expected = dict(choice_id=None, choice_label=None, choice_ids=['fix','test'], choice_labels=['修复','测试'], text=note)
    assert response.json()['task']['answer'] == expected
    repeated = answer(portal, card, choice_id=None, choice_ids=['fix','test'], text=note)
    assert repeated.json()['duplicate']
    assert answer(portal, card, choice_id=None, choice_ids=['fix','docs'], text=note).status_code == 409
    inbox = client.get('/api/inbox', headers=auth, params={'conversation_id':card['conversation_id']}).json()['messages']
    assert len(inbox) == 1 and inbox[0]['task_response'] == dict(task_id=card['id'], title=card['title'], **expected)
    assert len(calls) == 1


def test_multiple_custom_alternative_and_custom_disabled(portal):
    _, client, _, _, _, _, _ = portal
    _, sent = create(portal, mode='multiple', min_choices=2);login(client)
    card = sent['task']
    assert answer(portal, card, choice_id=None, choice_ids=[]).status_code == 422
    assert answer(portal, card, choice_id=None, choice_ids=['docker'], text='备注不能绕过最少选择数').status_code == 422
    assert answer(portal, card, choice_id=None, choice_ids=[], text='都不选，先检查环境。').json()['task']['answer']['choice_ids'] == []
    _, restricted = create(portal, mode='multiple', dedup_key='restricted-multiple', allow_custom=False)
    card = restricted['task']
    assert answer(portal, card, choice_id=None, choice_ids=[], text='自行回复').status_code == 422
    assert answer(portal, card, choice_id=None, choice_ids=['docker'], text='不允许附注').status_code == 422
    assert answer(portal, card, choice_id=None, choice_ids=['docker']).status_code == 200


@pytest.mark.parametrize('mode', ['confirm','input'])
def test_confirm_and_input_answer_routing_and_lifecycle(portal, mode):
    store, client, auth, _, _, calls, _ = portal
    overrides = {'options':[], 'input_hint':'例如：通知桥'} if mode == 'input' else {}
    _, sent = create(portal, mode=mode, **overrides);card = sent['task'];login(client)
    assert card['mode'] == mode and len(calls) == 1
    if mode == 'input':
        assert card['options'] == [] and card['allow_custom']
        assert answer(portal, card).status_code == 422
        assert answer(portal, card, choice_id=None, text='  ').status_code == 422
        body = dict(choice_id=None, text='通知桥 <script>不执行</script>\n原样回传')
    else:
        assert not card['allow_custom']
        assert answer(portal, card, choice_id=None, text='没有开启自定义回复').status_code == 422
        body = dict(choice_id='docker')
    assert answer(portal, card, choice_ids=['docker'], **body).status_code == 422
    result = answer(portal, card, **body)
    assert result.status_code == 200 and result.json()['task']['status'] == 'answered'
    assert answer(portal, card, **body).json()['duplicate']
    path = f"/api/conversations/{card['conversation_id']}/tasks/{card['id']}/state"
    assert client.post(path, headers=auth, json={'status':'completed','result':'已处理'}).json()['task']['status'] == 'completed'
    assert store.db.execute("SELECT count(*) FROM inbox WHERE identity LIKE 'task:%'").fetchone()[0] == 1


def test_single_default_keeps_pre_upgrade_fingerprint_and_reply_shape(portal):
    store, client, auth, _, _, _, _ = portal
    body, sent = create(portal)
    legacy = dict(title=body['title'], prompt=body['prompt'], options=[
        dict(id='docker',label='Docker',description='配置统一',recommended=True),
        dict(id='python',label='Python',description='直接运行',recommended=False)], allow_custom=True, expires_in=86400)
    legacy_text = '## 需要你决定 · 选择部署方式\n\n**两种方案都可行**，请选择。\n\n- **Docker** · 推荐：配置统一\n- **Python**：直接运行\n\n也可以输入自己的安排。\n\n点击下方链接，选择后提交决定。'
    expected = hashlib.sha256(json.dumps({'text':legacy_text,'task':legacy},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    row = store.db.execute('SELECT * FROM outgoing').fetchone()
    assert row['message_hash'] == expected
    assert store.portal.tasks.decrypt(store.db.execute('SELECT encrypted FROM task_cards').fetchone()[0]) == legacy
    repeated = client.post('/api/task-cards',headers=auth,json={**body,'mode':'single','allow_custom':True}).json()
    assert repeated['duplicate'] and repeated['task']['id'] == sent['task']['id']
    login(client)
    assert answer(portal,sent['task']).json()['task']['answer'] == dict(choice_id='docker',choice_label='Docker',text='')


@pytest.mark.parametrize('change', [
    {'mode':'unknown'}, {'mode':'input'}, {'mode':'input','options':[],'allow_custom':False},
    {'mode':'single','max_choices':2}, {'mode':'single','input_hint':'wrong mode'},
    {'mode':'multiple','min_choices':3}, {'mode':'multiple','min_choices':2,'max_choices':1},
    {'mode':'multiple','max_choices':3}, {'mode':'multiple','min_choices':0},
    {'mode':'confirm','options':[{'id':str(i),'label':str(i)} for i in range(5)]},
])
def test_mode_configuration_rejected_before_side_effects(portal, change):
    store, client, auth, _, chats, calls, _ = portal
    body = dict(conversation_id=chats[0]['id'],dedup_key='invalid-mode',title='问题',prompt='请选择',
                options=[{'id':'a','label':'A'}, {'id':'b','label':'B'}])
    body.update(change)
    assert client.post('/api/task-cards',headers=auth,json=body).status_code == 422
    assert not calls and store.db.execute('SELECT count(*) FROM task_cards').fetchone()[0] == 0


def test_mode_change_with_same_send_key_is_rejected(portal):
    _, client, auth, _, _, calls, _ = portal
    body, _ = create(portal)
    for mode in ['multiple','confirm','input']:
        response = client.post('/api/task-cards',headers=auth,json={**body,'mode':mode,**({'options':[]} if mode=='input' else {})})
        assert response.status_code == 409
    assert len(calls) == 1
