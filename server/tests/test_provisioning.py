"""Check that generated private files can initialize the actual storage engine."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

SERVER=Path(__file__).resolve().parents[1]
from wechat_bridge.storage.database import Store
from wechat_bridge.app import create_app

spec=importlib.util.spec_from_file_location('prepare_secrets',SERVER/'scripts/prepare_secrets.py')
setup=importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_provisioned_secrets_initialize_store_and_do_not_overwrite(tmp_path):
    credentials={'bot_token':'fixture-token','user_id':'fixture-owner','context_token':'fixture-context',
                 'base_url':'https://ilinkai.weixin.qq.com'}
    output=setup.prepare(credentials,tmp_path/'provisioned','https://notify.example.com/wechat',['codex','gpt'])
    client=json.loads((output/'clients/codex.json').read_text())
    registry=json.loads((output/'secrets/clients.json').read_text())
    assert setup.hashlib.sha256(client['api_key'].encode()).hexdigest()==registry['codex']
    store=Store(tmp_path/'state.sqlite3',(output/'secrets/encryption.key').read_bytes())
    try:
        store.bootstrap((output/'secrets/bootstrap.enc').read_bytes())
        assert store.account()['context_token']=='fixture-context'
        assert b'fixture-token' not in (output/'secrets/bootstrap.enc').read_bytes()
        with pytest.raises(FileExistsError):
            setup.prepare(credentials,output,'https://notify.example.com/wechat',['codex'])
        assert json.loads((output/'clients/codex.json').read_text())==client
    finally:
        store.close()


def test_web_pairing_provisions_unbound_server_and_private_admin(tmp_path, monkeypatch):
    output=setup.prepare(None,tmp_path/'provisioned','https://notify.example.com/wechat',['codex'])
    assert not (output/'secrets/bootstrap.enc').exists()
    admin=json.loads((output/'admin/admin.json').read_text())
    registry=json.loads((output/'secrets/admin.json').read_text())
    assert setup.hashlib.sha256(admin['admin_key'].encode()).hexdigest()==registry['key_sha256']
    assert admin['admin_url']=='https://notify.example.com/wechat/admin/'
    monkeypatch.setenv('WECHAT_SECRETS',str(output/'secrets'))
    monkeypatch.setenv('WECHAT_DATA',str(tmp_path/'data'))
    with TestClient(create_app(run_workers=False)) as client:
        response=client.get('/admin/api/status',headers={'Authorization':'Bearer '+admin['admin_key']})
        assert response.status_code==200
        assert response.json()['service']['connection_status']=='unbound'
        client.app.state.bridge.store.bind({'user_id':'fixture-owner','bot_id':'fixture-bot',
            'bot_token':'fixture-token','base_url':'https://ilinkai.weixin.qq.com'})
    with TestClient(create_app(run_workers=False)) as client:
        assert client.get('/health').status_code==200
        value=client.get('/admin/api/status',headers={'Authorization':'Bearer '+admin['admin_key']}).json()
        assert value['service']['bound'] is True
        assert value['service']['connection_status']=='waiting_message'


def test_add_admin_to_existing_secrets_does_not_rotate_other_files(tmp_path):
    output=tmp_path/'legacy'
    (output/'secrets').mkdir(parents=True)
    (output/'secrets/encryption.key').write_bytes(b'old-key')
    (output/'secrets/clients.json').write_text('{"codex":"old-hash"}')
    setup.prepare_admin(output,'https://notify.example.com/wechat')
    assert (output/'secrets/encryption.key').read_bytes()==b'old-key'
    assert (output/'secrets/clients.json').read_text()=='{"codex":"old-hash"}'
    with pytest.raises(FileExistsError):
        setup.prepare_admin(output,'https://notify.example.com/wechat')
