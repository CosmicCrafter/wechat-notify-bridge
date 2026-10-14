"""Refactor contracts: startup cleanup and local credential preservation."""
import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from wechat_bridge.__main__ import initialize
from wechat_bridge.app import create_app
from wechat_bridge.core.errors import BridgeError
from wechat_bridge.wechat.protocol import BridgeError as LegacyBridgeError


def test_local_initialize_preserves_existing_keys(tmp_path):
    initialize(tmp_path)
    files = [tmp_path/'admin-key.txt', *sorted((tmp_path/'secrets').iterdir())]
    before = {p.name:p.read_bytes() for p in files}
    initialize(tmp_path)
    assert before == {p.name:p.read_bytes() for p in files}
    admin = json.loads((tmp_path/'secrets/admin.json').read_text())
    assert admin['key_sha256'] == hashlib.sha256(before['admin-key.txt']).hexdigest()


def test_local_initialize_refuses_orphan_database(tmp_path):
    (tmp_path/'data').mkdir()
    (tmp_path/'data/wechat.sqlite3').write_bytes(b'existing')
    with pytest.raises(RuntimeError, match='original encryption key'):
        initialize(tmp_path)
    assert not (tmp_path/'secrets').exists()


def test_local_initialize_refuses_partial_secrets(tmp_path):
    (tmp_path/'secrets').mkdir()
    with pytest.raises(RuntimeError, match='Incomplete'):
        initialize(tmp_path)


def test_error_import_is_backward_compatible():
    assert BridgeError is LegacyBridgeError


def test_owned_lifespan_can_restart_without_reusing_closed_store(tmp_path, monkeypatch):
    initialize(tmp_path)
    monkeypatch.setenv('WECHAT_DATA',str(tmp_path/'data'))
    monkeypatch.setenv('WECHAT_SECRETS',str(tmp_path/'secrets'))
    app = create_app(run_workers=False)
    for _ in range(2):
        with TestClient(app) as client:
            assert client.get('/health').status_code == 200
            assert app.state.bridge.store.db.execute('SELECT 1').fetchone()[0] == 1


def test_failed_startup_releases_acquired_resources(monkeypatch):
    from wechat_bridge.runtime import lifecycle
    closed = []
    class Pairing:
        def __init__(self,*a,**k): pass
        async def close(self): closed.append('pairing')
    class Channels:
        def __init__(self,*a,**k): pass
        async def reconcile(self): raise RuntimeError('startup failed')
        async def close(self): closed.append('channels')
    class Proxy:
        def __init__(self,*a,**k): pass
        async def close(self): closed.append('proxy')
    monkeypatch.setattr(lifecycle,'Pairing',Pairing)
    monkeypatch.setattr(lifecycle,'Channels',Channels)
    monkeypatch.setattr(lifecycle,'ProxyManager',Proxy)
    for name in ('AdminAccounts','AdminConversations','AdminRecovery','ConnectionTests'):
        monkeypatch.setattr(lifecycle,name,lambda *a,**k:SimpleNamespace())
    bridge = SimpleNamespace(store=SimpleNamespace(db=None,clients=SimpleNamespace(seed=lambda _:None)))
    app = SimpleNamespace(state=SimpleNamespace())
    async def run():
        with pytest.raises(RuntimeError,match='startup failed'):
            async with lifecycle.create_lifespan(bridge,run_workers=False)(app):
                pytest.fail('startup should not finish')
    asyncio.run(run())
    assert closed == ['proxy','channels','pairing']
