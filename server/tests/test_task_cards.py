"""Decision-card HTTP contracts: ownership, atomic answers, retries and lifecycle."""
from concurrent.futures import ThreadPoolExecutor
import time
import uuid

import pytest

from test_portal import portal, login, ORIGIN
from wechat_bridge.storage.database import Store


def create(portal, **overrides):
    store, client, auth, _, chats, _, _ = portal
    body = dict(conversation_id=chats[0]['id'], dedup_key='decision-card', title='选择部署方式',
                prompt='**两种方案都可行**，请选择。',
                options=[dict(id='docker', label='Docker', description='配置统一', recommended=True),
                         dict(id='python', label='Python', description='直接运行')])
    body.update(overrides)
    response = client.post('/api/task-cards', headers=auth, json=body)
    assert response.status_code == 200, response.text
    return body, response.json()


def answer(portal, card, **overrides):
    client = portal[1]
    body = dict(request_id=uuid.uuid4().hex, choice_id='docker', text='')
    body.update(overrides)
    return client.post(f"/chat/api/conversations/{card['conversation_id']}/tasks/{card['id']}/answer", headers=ORIGIN, json=body)


def test_create_retry_dry_run_and_content_conflict(portal):
    store, client, auth, _, chats, calls, _ = portal
    body, dry = create(portal, dry_run=True)
    assert dry['status'] == 'dry_run_ready' and not calls
    assert store.db.execute('SELECT count(*) FROM task_cards').fetchone()[0] == 0
    body['dry_run'] = False
    first = client.post('/api/task-cards', headers=auth, json=body).json()
    duplicate = client.post('/api/task-cards', headers=auth, json=body).json()
    assert len(calls) == 1 and duplicate['duplicate']
    assert duplicate['task']['id'] == first['task']['id']
    assert duplicate['task']['expires_at'] == first['task']['expires_at']
    assert first['task']['status'] == 'pending' and first['phone_delivery'] == 'unconfirmed'
    assert calls[0]['msg']['item_list'][0]['text_item']['text'].endswith(
        '[处理任务卡片 →](' + first['conversation_url'] + ')')
    for changed in ({'allow_custom': False}, {'expires_in': 3600}, {'prompt': '另一个问题'}):
        assert client.post('/api/task-cards', headers=auth, json={**body, **changed}).status_code == 409
    history = client.get(f"/chat/api/conversations/{chats[0]['id']}/messages")
    assert history.status_code == 401
    login(client)
    assert client.get(f"/chat/api/conversations/{chats[0]['id']}/messages").json()['messages'][0]['task']['id'] == first['task']['id']


def test_answer_routes_structured_event_without_touching_wechat(portal):
    store, client, auth, other, chats, calls, _ = portal
    _, sent = create(portal)
    card = sent['task'];cid = card['conversation_id'];login(client)
    store.set('last_activity_at', 12345)
    before = client.get('/api/wake/events', headers=auth, params={'conversation_id': cid}).json()['next_after_id']
    submitted = answer(portal, card)
    assert submitted.status_code == 200 and submitted.json()['task']['status'] == 'answered'
    assert len(calls) == 1 and store.get('last_activity_at') == 12345
    response = client.get('/api/wake/events', headers=auth, params={'conversation_id': cid, 'after_id': before}).json()
    assert len(response['events']) == 1
    inbox = client.get('/api/inbox', headers=auth, params={'conversation_id': cid, 'after_id': before}).json()['messages']
    assert len(inbox) == 1
    assert inbox[0]['task_response'] == dict(task_id=card['id'], title='选择部署方式', choice_id='docker', choice_label='Docker', text='')
    assert 'Docker' in inbox[0]['text']
    assert client.get('/api/inbox', headers=auth, params={'conversation_id': chats[1]['id']}).json()['messages'] == []
    assert client.get(f"/api/conversations/{cid}/tasks/{card['id']}", headers=other).status_code == 404
    assert store.portal.tasks.get(cid, card['id'])['status'] == 'answered'


def test_competing_answers_are_atomic_and_same_answer_is_idempotent(portal):
    store, client, _, _, _, _, _ = portal
    _, sent = create(portal);card = sent['task'];login(client)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda choice: answer(portal, card, choice_id=choice), ['docker', 'python']))
    assert sorted(result.status_code for result in results) == [200, 409]
    recorded = store.portal.tasks.get(card['conversation_id'], card['id'])['answer']
    repeat = answer(portal, card, choice_id=recorded['choice_id'])
    assert repeat.json()['duplicate']
    assert store.db.execute("SELECT count(*) FROM inbox WHERE identity LIKE 'task:%'").fetchone()[0] == 1
    assert store.db.execute("SELECT count(*) FROM chat_messages WHERE direction='user'").fetchone()[0] == 1


def test_custom_reply_validation_and_content_preserved(portal):
    _, client, _, _, _, _, _ = portal
    _, sent = create(portal);card = sent['task'];login(client)
    assert answer(portal, card, choice_id='unknown').status_code == 422
    assert answer(portal, card, choice_id=None, text='  ').status_code == 422
    custom = '晚点处理，先保留当前运行方式。'
    assert answer(portal, card, choice_id=None, text=custom).json()['task']['answer']['text'] == custom
    assert answer(portal, card, choice_id=None, text='不同意见').status_code == 409
    _, restricted = create(portal, dedup_key='restricted', allow_custom=False)
    assert answer(portal, restricted['task'], choice_id=None, text=custom).status_code == 422


def test_lifecycle_expiry_and_terminal_states(portal):
    store, client, auth, _, _, _, _ = portal
    _, sent = create(portal);card = sent['task'];cid = card['conversation_id'];id = card['id']
    path = f'/api/conversations/{cid}/tasks/{id}/state'
    assert client.post(path, headers=auth, json={'status': 'completed'}).status_code == 409
    login(client);assert answer(portal, card).status_code == 200
    for status in ['processing', 'completed']:
        body = {'status': status, 'result': '已按你的选择处理。'}
        assert client.post(path, headers=auth, json=body).json()['task']['status'] == status
        assert client.post(path, headers=auth, json=body).json()['duplicate']
    assert client.post(path, headers=auth, json={'status': 'processing'}).status_code == 409
    assert client.post(path, headers=auth, json={'status': 'completed', 'result': '改写结果'}).status_code == 409
    _, expired = create(portal, dedup_key='expired')
    store.db.execute('UPDATE task_cards SET expires_at=? WHERE id=?', (time.time() - 1, expired['task']['id']))
    assert answer(portal, expired['task']).json()['detail'] == 'task_expired'
    assert store.portal.tasks.get(cid, expired['task']['id'])['status'] == 'expired'
    assert client.post(f"/api/conversations/{cid}/tasks/{expired['task']['id']}/state", headers=auth, json={'status':'cancelled'}).status_code == 409
    _, cancelled = create(portal, dedup_key='cancelled')
    client.post(f"/api/conversations/{cid}/tasks/{cancelled['task']['id']}/state", headers=auth, json={'status': 'cancelled'})
    assert answer(portal, cancelled['task']).json()['detail'] == 'task_not_pending'


def test_owner_auth_csrf_archive_and_deletion(portal):
    store, client, auth, _, chats, _, _ = portal
    _, sent = create(portal);card = sent['task'];cid = card['conversation_id'];id = card['id']
    path = f'/chat/api/conversations/{cid}/tasks/{id}/answer'
    body = dict(request_id=uuid.uuid4().hex, choice_id='docker')
    assert client.post(path, headers=ORIGIN, json=body).status_code == 401
    assert client.post(path, headers={**ORIGIN, **auth}, json=body).status_code == 401
    login(client)
    for headers in ({}, {'Origin':'https://evil.test','X-Chat-Request':'1'}):
        assert client.post(path, headers=headers, json=body).status_code == 403
    assert client.post(f'/chat/api/conversations/{chats[1]["id"]}/tasks/{id}/answer', headers=ORIGIN, json=body).status_code == 404
    client.post(f'/chat/api/conversations/{cid}/archive', headers=ORIGIN, json={'archived': True})
    assert answer(portal, card).json()['detail'] == 'conversation_closed'
    batch = client.get(f'/chat/api/conversations/{cid}/tasks', params={'ids': id}).json()['tasks']
    assert not batch[0]['can_answer']
    assert client.get(f'/chat/api/conversations/{cid}/tasks', params={'ids': '../bad'}).status_code == 422
    client.post(f'/chat/api/conversations/{cid}/delete', headers=ORIGIN, json={})
    assert store.db.execute('SELECT count(*) FROM task_cards').fetchone()[0] == 0
    assert client.get(f'/api/conversations/{cid}/tasks/{id}', headers=auth).status_code == 404


def test_encrypted_persistence_and_reopen(portal):
    store, client, _, _, _, _, key = portal
    _, sent = create(portal);card = sent['task'];login(client)
    assert answer(portal, card, choice_id=None, text='private-decision-content').status_code == 200
    dump = '\n'.join(store.db.iterdump())
    assert 'private-decision-content' not in dump and '选择部署方式' not in dump
    path = store.db.execute('PRAGMA database_list').fetchone()[2]
    reopened = Store(path, key)
    try:
        assert reopened.portal.tasks.get(card['conversation_id'], card['id'])['answer']['text'] == 'private-decision-content'
    finally:
        reopened.close()


@pytest.mark.parametrize('change', [
    {'options': []}, {'options': [{'id':'same','label':'A'}, {'id':'same','label':'B'}]},
    {'options': [{'id':'a','label':'A','recommended': True}, {'id':'b','label':'B','recommended': True}]},
    {'title':'  '}, {'expires_in': 0}, {'allow_unknown': True},
])
def test_invalid_card_rejected_without_side_effects(portal, change):
    store, client, auth, _, chats, calls, _ = portal
    body = dict(conversation_id=chats[0]['id'], dedup_key='invalid', title='Question', prompt='Choose',
                options=[{'id':'a','label':'A'}, {'id':'b','label':'B'}])
    body.update(change)
    assert client.post('/api/task-cards', headers=auth, json=body).status_code == 422
    assert not calls and store.db.execute('SELECT count(*) FROM task_cards').fetchone()[0] == 0
