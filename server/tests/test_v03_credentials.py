"""Bounded key overlap, leak revocation and legacy/OAuth compatibility."""

import json
import time
import sqlite3
from test_portal import portal,ADMIN
from test_oauth import service,grant
from wechat_bridge.storage.database import Store


def test_new_key_id_overlap_immediate_leak_revocation_and_old_api(portal):
    store,client,*_=portal
    created=client.post('/admin/api/clients',headers=ADMIN,json={'name':'modern-app','key_format':'nb','bot_ids':['default'],'default_bot_id':'default'}).json()
    id=created['client']['id'];key=created['api_key'];key_id=created['credential']['id']
    assert key.startswith('nb_') and len(key)>=43 and key_id.startswith('nbk_') and key!=key_id
    headers={'Authorization':'Bearer '+key}
    assert client.get('/api/status',headers=headers).status_code==200
    snapshot=store.clients.authenticate(key)
    nextkey=client.post('/admin/api/clients/'+id+'/credentials/rotate',headers=ADMIN,json={'overlap_seconds':3600}).json()
    assert store.clients.authenticate(key).id==store.clients.authenticate(nextkey['api_key']).id==id
    assert client.post('/admin/api/clients/'+id+'/credentials/rotate',headers=ADMIN,json={}).status_code==409
    assert client.post('/admin/api/clients/'+id+'/credentials/'+key_id+'/revoke',headers=ADMIN,json={}).status_code==200
    assert client.get('/api/status',headers=headers).status_code==401
    import pytest
    with pytest.raises(Exception):store.clients.revalidate(snapshot)
    assert client.get('/api/status',headers={'Authorization':'Bearer '+nextkey['api_key']}).status_code==200
    listed=client.get('/admin/api/clients',headers=ADMIN).text
    assert key not in listed and nextkey['api_key'] not in listed
    old=client.post('/admin/api/clients/'+id+'/rotate',headers=ADMIN,json={}).json()
    assert len(old['api_key'])==40 and old['api_key'].isdigit()
    assert client.get('/api/status',headers={'Authorization':'Bearer '+nextkey['api_key']}).status_code==401
    assert client.get('/api/status',headers={'Authorization':'Bearer '+old['api_key']}).status_code==200


def test_overlap_expiry_zero_rotation_and_backup_restores_credentials(portal,tmp_path):
    store,client,auth,*_=portal
    identity=store.clients.authenticate(auth['Authorization'][7:]);id=identity.id
    rotated=client.post('/admin/api/clients/'+id+'/credentials/rotate',headers=ADMIN,json={}).json()
    assert client.post('/admin/api/clients/'+id+'/credentials/rotate',headers=ADMIN,json={'overlap_seconds':86401}).status_code==422
    store.db.execute("UPDATE api_credentials SET expires_at=? WHERE client_id=? AND status='retiring'",(time.time()-1,id))
    assert client.get('/api/status',headers=auth).status_code==401
    replacement=client.post('/admin/api/clients/'+id+'/credentials/rotate',headers=ADMIN,json={'overlap_seconds':0}).json()
    assert client.get('/api/status',headers={'Authorization':'Bearer '+rotated['api_key']}).status_code==401
    path=tmp_path/'restored.sqlite3';db=sqlite3.connect(path);store.db.backup(db);db.close()
    recovered=Store(path,portal[-1])
    try:
        assert recovered.clients.authenticate(replacement['api_key']).id==id
        assert recovered.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert replacement['api_key'] not in '\n'.join(recovered.db.iterdump())
    finally:recovered.close()


def test_key_rotation_does_not_silently_revoke_separate_oauth_grant(service):
    app,store,client,identity,*_=service
    oauth,body,_=grant(service)
    tokens=client.post('/token',data=body).json()
    authorization={'Authorization':'Bearer '+tokens['access_token']}
    assert client.get('/api/status',headers=authorization).status_code==200
    store.clients.credentials.rotate(identity['id'],0)
    assert client.get('/api/status',headers=authorization).status_code==200
    store.clients.rotate(identity['id'])
    assert client.get('/api/status',headers=authorization).status_code==401
