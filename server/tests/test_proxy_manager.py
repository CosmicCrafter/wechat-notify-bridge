"""Proxy recovery, subscription trust boundaries and administrator isolation."""
import asyncio
import copy
import hashlib
import json
import socket
import time
from unittest.mock import AsyncMock

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import httpx
import pytest

from wechat_bridge.app import create_app
from wechat_bridge.api.proxy import ProxySettings
from wechat_bridge.services.bridge import Bridge
from wechat_bridge.services import proxy as module
from wechat_bridge.services.proxy import ProxyManager, GROUP, parse_subscription, subscription_url
from wechat_bridge.storage.database import Store
from wechat_bridge.wechat.protocol import BridgeError


def node(name):
    return {'name': name, 'type': 'vmess', 'server': 'proxy.example.com', 'port': 443,
            'uuid': 'test-node-secret', 'udp': True}


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path/'state.sqlite3', Fernet.generate_key())
    yield value
    value.close()


@pytest.fixture
def control():
    return {'controller_url': 'http://127.0.0.1:9090', 'controller_secret': 'fixture-controller-secret',
            'allowed_hosts': ['connectors.api.openai.com'], 'callback': {'host': '127.0.0.1', 'port': 7890,
                'username': 'fixture', 'password': 'fixture-proxy-password'},
            'base_config': {'port': 7890, 'proxies': [node('日本 Pro old')], 'rules': ['MATCH,REJECT']}}


@pytest.fixture(autouse=True)
def public_nodes(monkeypatch):
    monkeypatch.setattr(module, 'public_ips', lambda host: ['8.8.8.8'])


def manager(store, control, nodes, delays, *, failing_target=None):
    state = {'loads': [], 'selected': None, 'requests': []}
    def handler(request):
        state['requests'].append(request)
        if request.url.path == '/configs':
            state['loads'].append(json.loads(json.loads(request.content)['payload']))
            return httpx.Response(204)
        if request.url.path == '/proxies/' + GROUP:
            if request.method == 'PUT':
                state['selected'] = json.loads(request.content)['name']
                return httpx.Response(204)
            return httpx.Response(200, json={'now': state['selected']})
        if request.url.path.endswith('/delay'):
            name = request.url.path[len('/proxies/'):-len('/delay')]
            delay = delays.get(name)
            return httpx.Response(200, json={'delay': delay}) if delay else httpx.Response(504)
        return httpx.Response(404)
    value = ProxyManager(store, control, transport=httpx.MockTransport(handler),
                         downloader=lambda url: (json.dumps({'proxies': nodes}).encode(), {'total': 1000, 'download': 300}))
    value.settings['subscription_url'] = 'https://subscription.example.com/feed?token=fixture-subscription-secret'
    async def verify():
        return state['selected'] != failing_target
    value.verify_selected = verify
    return value, state


@pytest.mark.parametrize('url', ['http://example.com/a', 'https://127.0.0.1/a', 'https://[::1]/',
    'https://user:password@example.com/feed', 'https://example.com:999/feed', 'https://example.com/feed#fragment',
    'https://localhost/feed', 'https://224.0.0.1/feed'])
def test_subscription_urls_reject_untrusted_destinations(url):
    with pytest.raises(BridgeError):
        subscription_url(url)


def test_subscription_dns_rejects_mixed_public_private_answers(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [
        (2, 1, 6, '', ('8.8.8.8', 443)), (2, 1, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(BridgeError):
        module.public_ips('example.com')


@pytest.mark.parametrize('raw', [b'!!python/object/apply:os.system [echo invalid]',
    b'proxies: &a [*a]', b'proxies: []', b'proxies: [1]',
    b'a: &x {b: 1}\nproxies: [*x]', b'x: ' + b'['*14 + b'1' + b']'*14])
def test_yaml_does_not_accept_objects_aliases_or_unbounded_depth(raw):
    with pytest.raises(BridgeError):
        parse_subscription(raw)


def test_only_nodes_are_imported_and_privileged_options_are_removed():
    item = dict(node('日本 Pro 1'), **{'dialer-proxy': 'DIRECT', 'interface-name': 'eth0', 'routing-mark': 1})
    result = parse_subscription(json.dumps({'proxies': [item], 'rules': ['MATCH,DIRECT'],
                                            'external-controller': '0.0.0.0:1234'}).encode())
    assert result == [node('日本 Pro 1')]


def test_subscription_and_node_cache_are_encrypted_and_never_returned(store, control):
    async def run():
        value, state = manager(store, control, [node('日本 Pro 1')], {'日本 Pro 1': 120})
        value.save(ProxySettings(enabled=True, update_interval=21600, check_interval=300,
                                  priorities=['日本 Pro'], subscription_url=value.settings['subscription_url']))
        await value.update()
        public = json.dumps(value.snapshot(), ensure_ascii=False)
        for secret in ('fixture-subscription-secret', 'test-node-secret', 'fixture-controller-secret', 'fixture-proxy-password'):
            assert secret not in public
            assert secret not in json.dumps([dict(r) for r in store.db.execute("SELECT * FROM state WHERE key LIKE 'proxy_%'")])
        restarted = ProxyManager(store, control, transport=httpx.MockTransport(lambda r: httpx.Response(204)))
        assert restarted.source == 'admin'
        assert restarted.settings['subscription_url'] == value.settings['subscription_url']
        assert restarted.cache['current'] == '日本 Pro 1'
        assert value.snapshot()['usage']['download'] == 300
        await restarted.close()
        await value.close()
    asyncio.run(run())


@pytest.mark.parametrize('delays,expected', [
    ({'日本 Pro 1': 130, '美国 Pro 1': 50, '新加坡 Pro 1': 20}, '日本 Pro 1'),
    ({'日本 Pro 1': None, '美国 Pro 1': 50, '新加坡 Pro 1': 20}, '美国 Pro 1'),
    ({'日本 Pro 1': None, '美国 Pro 1': None, '新加坡 Pro 1': 20}, '新加坡 Pro 1'),
])
def test_country_priority_is_not_overridden_by_latency(store, control, delays, expected):
    async def run():
        value, state = manager(store, control, [node(n) for n in delays], delays)
        await value.update()
        assert value.snapshot()['current_node'] == expected
        assert state['selected'] == expected
        assert state['loads'][-1]['rules'][-1] == 'MATCH,REJECT'
        await value.close()
    asyncio.run(run())


def test_healthy_current_node_stays_within_tier_and_actual_target_is_checked(store, control):
    async def run():
        nodes = [node('日本 Pro slow'), node('日本 Pro fast')]
        value, state = manager(store, control, nodes, {'日本 Pro slow': 200, '日本 Pro fast': 20})
        value.cache['current'] = '日本 Pro slow'
        await value.update()
        assert value.cache['current'] == '日本 Pro slow'
        value.verify_selected = AsyncMock(side_effect=[False, True])
        await value.check()
        assert value.cache['current'] == '日本 Pro fast'
        await value.close()
    asyncio.run(run())


def test_empty_rules_choose_fastest_available_not_random(store, control):
    async def run():
        value, state = manager(store, control, [node('德国 A'), node('美国 B')], {'德国 A': 90, '美国 B': 20})
        value.settings['priorities'] = []
        await value.update()
        assert value.cache['current'] == '美国 B'
        await value.close()
    asyncio.run(run())


def test_failed_update_restores_runtime_and_preserves_last_good_metadata(store, control):
    async def run():
        value, state = manager(store, control, [node('日本 Pro 1')], {'日本 Pro 1': 30})
        await value.update()
        before = copy.deepcopy(value.cache)
        value.downloader = lambda url: (json.dumps({'proxies': [node('德国 1')]}).encode(), {'total': 999})
        await value.job(value.update)
        assert value.cache['nodes'] == before['nodes']
        assert value.cache['usage'] == before['usage']
        assert value.cache['last_update_at'] == before['last_update_at']
        assert value.cache['last_error'] == 'proxy_no_available_node'
        assert value.cache['retry_after'] > time.time() + 290
        assert state['loads'][-1] == before['runtime']
        assert state['selected'] == before['current']
        await value.close()
    asyncio.run(run())


def test_manual_selection_failure_preserves_previous_mode_and_selected_node(store, control):
    async def run():
        value, state = manager(store, control, [node('日本 Pro 1'), node('美国 Pro 1')], {'日本 Pro 1': 10})
        await value.update()
        value.action('select', '美国 Pro 1')
        with pytest.raises(BridgeError) as error:
            value.action('update')
        assert error.value.reason == 'proxy_operation_running'
        await value.task
        assert value.settings['mode'] == 'auto'
        assert value.cache['current'] == state['selected'] == '日本 Pro 1'
        assert value.cache['last_error'] == 'proxy_no_available_node'
        await value.close()
    asyncio.run(run())


def test_download_error_is_redacted_and_old_config_survives(store, control):
    async def run():
        value, state = manager(store, control, [node('日本 Pro 1')], {'日本 Pro 1': 10})
        await value.update()
        count = len(state['loads'])
        def bad(url):
            raise RuntimeError('secret URL ' + url)
        value.downloader = bad
        await value.job(value.update)
        assert value.cache['last_error'] == 'proxy_operation_failed'
        assert len(state['loads']) == count
        assert 'fixture-subscription-secret' not in json.dumps(value.snapshot())
        await value.close()
    asyncio.run(run())


def test_admin_routes_reject_client_keys_and_redact_validation_input(store, control, tmp_path, monkeypatch):
    path = tmp_path/'control.json'
    path.write_text(json.dumps(control))
    monkeypatch.setenv('WECHAT_PROXY_CONTROL_FILE', str(path))
    app = create_app(Bridge(store), {'codex': hashlib.sha256(b'client-key').hexdigest()},
                     run_workers=False, admin_hash=hashlib.sha256(b'admin-key').hexdigest())
    with TestClient(app) as client:
        admin = {'Authorization': 'Bearer admin-key'}
        for route in ('/admin/api/proxy', '/admin/api/proxy/config', '/admin/api/proxy/update',
                      '/admin/api/proxy/check', '/admin/api/proxy/select'):
            method = client.get if route.endswith('/proxy') else client.post
            assert method(route).status_code == 401
            assert method(route, headers={'Authorization': 'Bearer client-key'}).status_code == 401
        body = {'enabled': False, 'update_interval': 21600, 'check_interval': 300,
                'priorities': ['日本 Pro'], 'subscription_url': 'https://example.com/?token=secret-value'}
        result = client.post('/admin/api/proxy/config', headers=admin, json=body)
        assert result.status_code == 200 and 'secret-value' not in result.text
        body['subscription_url'] = 'https://example.com/?token=' + 'secret-value'*400
        result = client.post('/admin/api/proxy/config', headers=admin, json=body)
        assert result.status_code == 422 and 'secret-value' not in result.text
        assert client.get('/admin/api/proxy', headers=admin).headers['cache-control'] == 'no-store'


def test_manager_is_optional_and_invalid_bootstrap_does_not_stop_bridge(store, monkeypatch):
    async def run():
        monkeypatch.delenv('WECHAT_PROXY_CONTROL_FILE', raising=False)
        value = ProxyManager(store)
        assert value.snapshot()['available'] is False
        await value.close()
        invalid = ProxyManager(store, {})
        assert invalid.snapshot()['last_error'] == 'proxy_control_configuration_invalid'
        await invalid.close()
    asyncio.run(run())


@pytest.mark.parametrize('status,size,reason', [(302, 1, 'subscription_download_failed'),
    (200, module.MAX_BYTES + 1, 'subscription_too_large')])
def test_download_rejects_redirects_and_oversized_responses(monkeypatch, status, size, reason):
    class Response:
        def __init__(self): self.status, self.left = status, size
        def read1(self, amount):
            result = b'x' * min(self.left, amount)
            self.left -= len(result)
            return result
    class Connection:
        def __init__(self, *a, **k): pass
        def request(self, *a, **k): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(module.http.client, 'HTTPSConnection', Connection)
    monkeypatch.setattr(module.socket, 'create_connection', lambda *a, **k: object())
    context = type('TLS', (), {'wrap_socket': lambda self, sock, **kw: sock})()
    monkeypatch.setattr(module.ssl, 'create_default_context', lambda: context)
    with pytest.raises(BridgeError) as error:
        module.download_subscription('https://example.com/private-feed')
    assert error.value.reason == reason


def test_reload_keeps_known_node_or_rejects_until_verified(store, control):
    async def run():
        value = ProxyManager(store, control)
        assert value.runtime([node('日本 Pro 1')])['proxy-groups'][0]['proxies'][0] == 'REJECT'
        value.cache['current'] = '日本 Pro 1'
        assert value.runtime([node('日本 Pro 1')])['proxy-groups'][0]['proxies'][0] == '日本 Pro 1'
        await value.close()
    asyncio.run(run())


def test_config_payload_preserves_emoji_for_mihomo_yaml_parser(store, control):
    async def run():
        value = ProxyManager(store, control)
        value.rpc = AsyncMock()
        await value.load(value.runtime([node('🇯🇵 日本 Pro 1')]))
        payload = value.rpc.call_args.kwargs['json']['payload']
        assert '🇯🇵' in payload and '\\ud83c' not in payload
        await value.close()
    asyncio.run(run())


def test_core_restart_restores_cached_runtime(store, control):
    async def run():
        value, state = manager(store, control, [node('日本 Pro 1')], {'日本 Pro 1': 30})
        await value.update()
        original = value.rpc
        async def restarted(method, path, **kwargs):
            if method == 'GET' and path == '/proxies/' + GROUP and len(state['loads']) == 1:
                raise BridgeError(502, 'proxy_controller_unavailable')
            return await original(method, path, **kwargs)
        value.rpc = restarted
        await value.check()
        assert len(state['loads']) == 2 and value.cache['current'] == '日本 Pro 1'
        await value.close()
    asyncio.run(run())


def test_failed_periodic_check_restores_controller_selection(store, control):
    async def run():
        value, state = manager(store, control, [node('日本 Pro 1'), node('美国 Pro 1')],
                               {'日本 Pro 1': 10, '美国 Pro 1': 20})
        await value.update()
        previous = state['selected']
        value.verify_selected = AsyncMock(return_value=False)
        await value.job(value.check)
        assert state['selected'] == value.cache['current'] == previous
        assert value.cache['last_error'] == 'proxy_no_available_node'
        await value.close()
    asyncio.run(run())
