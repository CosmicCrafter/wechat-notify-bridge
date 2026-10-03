"""Administrator-only subscription and Mihomo management, independent of event locks."""
import asyncio
import copy
import http.client
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import time
from urllib.parse import quote, urlsplit

import httpx
import yaml

from wechat_bridge.wechat.protocol import BridgeError

GROUP = 'WECHAT-CALLBACK'
MAX_BYTES = 2 * 1024 * 1024
DEFAULT_RULES = ['日本 Pro', '美国 Pro', '新加坡 Pro']
NODE_TYPES = {'ss', 'ssr', 'vmess', 'vless', 'trojan', 'hysteria', 'hysteria2', 'tuic', 'http', 'socks5', 'anytls'}


def fail(reason, status=422):
    raise BridgeError(status, reason)


def subscription_url(value):
    try:
        p = urlsplit(value)
        if (not isinstance(value, str) or len(value) > 4096 or p.scheme != 'https'
                or not p.hostname or p.port not in (None, 443) or p.username or p.password
                or p.fragment or any(c.isspace() for c in value)):
            fail('invalid_subscription_url')
        address = p.hostname
        try:
            ip = ipaddress.ip_address(address)
            if not ip.is_global or ip.is_multicast or ip.is_reserved:
                fail('invalid_subscription_url')
        except ValueError:
            if address.lower() in ('localhost',) or address.lower().endswith(('.local', '.localhost')):
                fail('invalid_subscription_url')
        return p
    except (ValueError, TypeError):
        fail('invalid_subscription_url')


def public_ips(host):
    values = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    if not values or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast
                         or ipaddress.ip_address(ip).is_reserved for ip in values):
        fail('subscription_address_not_public')
    return values


def download_subscription(url):
    """Pin a checked public address, verify TLS, reject redirects and bound response size."""
    p = subscription_url(url)
    addresses = public_ips(p.hostname)
    context = ssl.create_default_context()
    last = None
    for address in addresses[:3]:
        connection = http.client.HTTPSConnection(p.hostname, timeout=15, context=context)
        try:
            connection.sock = context.wrap_socket(socket.create_connection((address, 443), timeout=10), server_hostname=p.hostname)
            connection.request('GET', (p.path or '/') + ('?' + p.query if p.query else ''),
                               headers={'User-Agent': 'clash', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status != 200:
                fail('subscription_download_failed', 502)
            chunks, size, deadline = [], 0, time.monotonic() + 30
            while True:
                if time.monotonic() >= deadline:
                    fail('subscription_download_failed', 502)
                chunk = response.read1(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    fail('subscription_too_large')
                chunks.append(chunk)
            raw = b''.join(chunks)
            usage = {}
            for part in (response.getheader('subscription-userinfo') or '').split(';'):
                field, sep, value = part.strip().partition('=')
                if sep and field in ('upload', 'download', 'total', 'expire') and value.isdigit():
                    usage[field] = min(int(value), 2**63-1)
            return raw, usage
        except BridgeError:
            raise
        except Exception:
            last = 'subscription_download_failed'
        finally:
            connection.close()
    fail(last or 'subscription_download_failed', 502)


class SubscriptionLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        depth = getattr(self, '_depth', 0)
        if depth >= 12 or self.check_event(yaml.AliasEvent):
            fail('invalid_subscription_content')
        self._depth = depth + 1
        try:
            return super().compose_node(parent, index)
        finally:
            self._depth = depth


def parse_subscription(raw):
    try:
        if len(raw) > MAX_BYTES:
            fail('subscription_too_large')
        value = yaml.load(raw, Loader=SubscriptionLoader)
        nodes = value.get('proxies') if isinstance(value, dict) else None
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= 300:
            fail('invalid_subscription_content')
        result, seen, deadline = [], set(), time.monotonic() + 45
        for node in nodes:
            if not isinstance(node, dict) or node.get('type') not in NODE_TYPES:
                continue
            name, host, port = node.get('name'), node.get('server'), node.get('port')
            if (not isinstance(name, str) or not 1 <= len(name) <= 160 or name in seen
                    or name.upper() in ('DIRECT', 'REJECT', 'GLOBAL', GROUP)
                    or any(ord(c) < 32 for c in name)
                    or not isinstance(host, str) or not host or len(host) > 253
                    or type(port) is not int or not 1 <= port <= 65535):
                fail('invalid_subscription_content')
            if time.monotonic() > deadline:
                fail('invalid_subscription_content')
            public_ips(host)
            # Import only outbound nodes, never subscription rules/providers/listeners.
            clean = copy.deepcopy(node)
            for key in ('dialer-proxy', 'interface-name', 'routing-mark'):
                clean.pop(key, None)
            if len(json.dumps(clean)) > 16384:
                fail('invalid_subscription_content')
            result.append(clean)
            seen.add(name)
        if not result:
            fail('subscription_has_no_supported_nodes')
        return result
    except BridgeError:
        raise
    except Exception:
        fail('invalid_subscription_content')


def node_tiers(nodes, priorities):
    if not priorities:
        return [nodes]
    return [[node for node in nodes if all(word.casefold() in node['name'].casefold()
                                          for word in rule.split())] for rule in priorities]


class ProxyManager:
    def __init__(self, store, control=None, *, transport=None, downloader=download_subscription):
        self.store, self.downloader = store, downloader
        self.available = False
        self.source, self.task, self.loop_task = 'env', None, None
        self.http = httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False, transport=transport)
        self.cache, self.settings = {}, {}
        try:
            if control is None:
                path = os.environ.get('WECHAT_PROXY_CONTROL_FILE')
                if not path:
                    return
                control = json.loads(Path(path).read_text(encoding='utf-8'))
            self.control = control
            p = urlsplit(control['controller_url'])
            if p.scheme != 'http' or not p.hostname or p.username or p.password or p.query or p.fragment:
                raise ValueError('controller_url')
            if not control['controller_secret'] or not control['allowed_hosts']:
                raise ValueError('controller_secret')
            self.settings = self.read('settings') or {
                'enabled': True,
                'subscription_url': os.environ.get('WECHAT_PROXY_SUBSCRIPTION_URL', ''),
                'update_interval': int(os.environ.get('WECHAT_PROXY_UPDATE_INTERVAL', '21600')),
                'check_interval': int(os.environ.get('WECHAT_PROXY_CHECK_INTERVAL', '300')),
                'priorities': json.loads(os.environ.get('WECHAT_PROXY_PRIORITIES', json.dumps(DEFAULT_RULES))),
                'mode': 'auto', 'manual_node': None,
            }
            self.validate(self.settings)
            self.source = 'admin' if store.get('proxy_settings') else 'env'
            self.cache = self.read('cache') or {'nodes': control['base_config'].get('proxies', []),
                                              'delays': {}, 'current': None, 'last_error': None}
            self.available = True
        except Exception:
            self.settings = {}
            self.cache = {'last_error': 'proxy_control_configuration_invalid'}

    def read(self, key):
        encrypted = self.store.get('proxy_' + key)
        return json.loads(self.store.cipher.decrypt(encrypted.encode())) if encrypted else None

    def write(self, key, value):
        self.store.set('proxy_' + key, self.store.cipher.encrypt(json.dumps(value).encode()).decode())

    @staticmethod
    def validate(settings):
        if settings.get('subscription_url'):
            subscription_url(settings['subscription_url'])
        if (type(settings['enabled']) is not bool or type(settings['update_interval']) is not int
                or not 300 <= settings['update_interval'] <= 604800
                or type(settings['check_interval']) is not int or not 30 <= settings['check_interval'] <= 3600
                or not isinstance(settings['priorities'], list) or len(settings['priorities']) > 8
                or any(not isinstance(x, str) or not x.strip() or len(x) > 100 for x in settings['priorities'])
                or settings['mode'] not in ('auto', 'manual')):
            fail('invalid_proxy_settings')

    def snapshot(self):
        settings, cache = self.settings, self.cache
        return {'available': self.available, 'busy': self.task is not None and not self.task.done(),
                'source': self.source, 'enabled': settings.get('enabled', False),
                'subscription_configured': bool(settings.get('subscription_url')),
                'subscription_label': urlsplit(settings.get('subscription_url', '')).hostname or '未配置',
                'update_interval': settings.get('update_interval', 21600),
                'check_interval': settings.get('check_interval', 300),
                'priorities': settings.get('priorities', DEFAULT_RULES), 'mode': settings.get('mode', 'auto'),
                'current_node': cache.get('current'), 'manual_node': settings.get('manual_node'),
                'last_update_at': cache.get('last_update_at'), 'next_update_at': cache.get('next_update_at'),
                'last_check_at': cache.get('last_check_at'), 'last_error': cache.get('last_error'),
                'usage': cache.get('usage', {}), 'nodes': [
                    {'name': n['name'], 'type': n['type'], 'udp': bool(n.get('udp')),
                     'delay': cache.get('delays', {}).get(n['name'])} for n in cache.get('nodes', [])]}

    def ready(self):
        if not self.available:
            fail('proxy_manager_not_configured', 503)
        if self.task and not self.task.done():
            fail('proxy_operation_running', 409)

    def save(self, body):
        self.ready()
        settings = dict(self.settings)
        values = body.model_dump(exclude_none=True)
        if values.get('subscription_url') == '':
            values.pop('subscription_url')  # An empty password field preserves the saved URL.
        settings.update(values)
        settings['priorities'] = [x.strip() for x in settings['priorities']]
        self.validate(settings)
        self.write('settings', settings)
        self.settings, self.source = settings, 'admin'
        self.cache['next_update_at'] = time.time()
        self.write('cache', self.cache)
        return self.snapshot()

    async def rpc(self, method, path, **kwargs):
        try:
            response = await self.http.request(method, self.control['controller_url'].rstrip('/') + path,
                headers={'Authorization': 'Bearer ' + self.control['controller_secret']}, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else {}
        except asyncio.CancelledError:
            raise
        except Exception:
            fail('proxy_controller_unavailable', 502)

    def runtime(self, nodes):
        config = copy.deepcopy(self.control['base_config'])
        config['proxies'] = nodes
        names = [n['name'] for n in nodes]
        current = self.cache.get('current')
        # Keep the known selection during a reload; otherwise start closed until verified.
        initial = current if current in names else 'REJECT'
        config['proxy-groups'] = [{'name': GROUP, 'type': 'select',
                                   'proxies': [initial] + [n for n in names + ['REJECT'] if n != initial]}]
        config['rules'] = ['DOMAIN,' + host + ',' + GROUP for host in self.control['allowed_hosts']] + ['MATCH,REJECT']
        config.pop('proxy-providers', None)
        config.pop('rule-providers', None)
        return config

    async def load(self, runtime):
        # Mihomo parses this string as YAML; JSON surrogate escapes for emoji are invalid YAML.
        await self.rpc('PUT', '/configs?force=true', json={'payload': json.dumps(runtime, ensure_ascii=False)})

    async def delay(self, node):
        try:
            value = await self.rpc('GET', '/proxies/' + quote(node['name'], safe='') + '/delay',
                                   params={'url': 'https://www.gstatic.com/generate_204', 'timeout': 5000})
            result = value.get('delay')
            return result if type(result) is int and result > 0 else None
        except BridgeError:
            return None

    async def verify_selected(self):
        callback = self.control['callback']
        credentials = quote(callback['username'], safe='') + ':' + quote(callback['password'], safe='')
        proxy = 'http://' + credentials + '@' + callback['host'] + ':' + str(callback['port'])
        try:
            async with httpx.AsyncClient(proxy=proxy, timeout=10, trust_env=False, follow_redirects=False) as client:
                response = await client.get('https://' + self.control['allowed_hosts'][0] + '/')
                return response.status_code < 500
        except Exception:
            return False

    async def choose(self, nodes):
        tiers = node_tiers(nodes, self.settings['priorities'])
        if self.settings['mode'] == 'manual':
            tiers = [[n for n in nodes if n['name'] == self.settings['manual_node']]]
        limiter = asyncio.Semaphore(6)
        async def measure(node):
            async with limiter:
                value = await self.delay(node)
                self.cache.setdefault('delays', {})[node['name']] = value
                return node, value
        for tier in tiers:
            measured = await asyncio.gather(*(measure(n) for n in tier))
            alive = [(n, d) for n, d in measured if d is not None]
            alive.sort(key=lambda item: (item[0]['name'] != self.cache.get('current'), item[1]))
            for node, value in alive:
                await self.rpc('PUT', '/proxies/' + GROUP, json={'name': node['name']})
                if await self.verify_selected():
                    self.cache['current'] = node['name']
                    return node['name']
                self.cache['delays'][node['name']] = None
        fail('proxy_no_available_node', 502)

    async def update(self):
        url = self.settings['subscription_url']
        if not url:
            fail('proxy_subscription_required')
        raw, usage = await asyncio.to_thread(self.downloader, url)
        nodes = await asyncio.to_thread(parse_subscription, raw)
        old = copy.deepcopy(self.cache)
        previous_runtime = old.get('runtime') or self.control['base_config']
        runtime = self.runtime(nodes)
        try:
            await self.load(runtime)
            await self.choose(nodes)
        except BaseException:
            self.cache = old
            try:
                await asyncio.shield(self.load(previous_runtime))
                if old.get('current'):
                    await asyncio.shield(self.rpc('PUT', '/proxies/' + GROUP, json={'name': old['current']}))
            except Exception:
                self.cache['last_error'] = 'proxy_rollback_failed'
            raise
        self.cache.update(nodes=nodes, runtime=runtime, usage=usage, last_update_at=time.time(), last_error=None)
        self.cache['next_update_at'] = time.time() + self.settings['update_interval']
        self.cache['last_check_at'] = time.time()
        self.write('cache', self.cache)

    async def check(self):
        nodes = self.cache.get('nodes', [])
        if not nodes:
            return await self.update()
        # Restore after an independent core restart without reloading a healthy core.
        runtime = self.cache.get('runtime') or self.runtime(nodes)
        try:
            await self.rpc('GET', '/proxies/' + GROUP)
        except BridgeError:
            await self.load(runtime)
        await self.choose(nodes)
        self.cache.update(runtime=runtime, last_error=None, last_check_at=time.time())
        self.write('cache', self.cache)

    def action(self, kind, name=None):
        self.ready()
        previous_settings = copy.deepcopy(self.settings)
        previous_node = self.cache.get('current')
        if kind == 'select':
            if name is not None and name not in {n['name'] for n in self.cache.get('nodes', [])}:
                fail('proxy_node_not_found', 404)
            self.settings.update(mode='auto' if name is None else 'manual', manual_node=name)
            self.write('settings', self.settings)
            self.source = 'admin'
        async def select():
            try:
                await self.check()
            except BaseException:
                self.settings = previous_settings
                self.write('settings', self.settings)
                if previous_node:
                    try:
                        await asyncio.shield(self.rpc('PUT', '/proxies/' + GROUP, json={'name': previous_node}))
                    except Exception:
                        self.cache['last_error'] = 'proxy_rollback_failed'
                raise
        operation = self.update if kind == 'update' else select if kind == 'select' else self.check
        self.task = asyncio.create_task(self.job(operation))
        return self.snapshot()

    async def job(self, operation):
        try:
            await asyncio.wait_for(operation(), timeout=180)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self.cache.get('last_error') != 'proxy_rollback_failed':
                self.cache['last_error'] = exc.reason if isinstance(exc, BridgeError) else 'proxy_operation_failed'
            self.cache['last_check_at'] = time.time()
            self.cache['retry_after'] = time.time() + 300
            self.cache['next_update_at'] = time.time() + min(300, self.settings['update_interval'])
            self.write('cache', self.cache)

    async def run(self):
        while True:
            now = time.time()
            if self.settings['enabled'] and not (self.task and not self.task.done()):
                if self.settings['subscription_url'] and now >= self.cache.get('next_update_at', 0):
                    self.action('update')
                elif now >= self.cache.get('last_check_at', 0) + self.settings['check_interval']:
                    if self.cache.get('last_error') and self.settings['subscription_url'] and now >= self.cache.get('retry_after', 0):
                        self.action('update')
                    else:
                        self.action('check')
            await asyncio.sleep(5)

    def start(self):
        if self.available:
            self.loop_task = asyncio.create_task(self.run())

    async def close(self):
        tasks = [t for t in (self.loop_task, self.task) if t]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.http.aclose()
