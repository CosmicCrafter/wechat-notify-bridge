"""Experimental MCP Events webhook adapter, retaining the legacy MCP transport."""
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import time
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse

NAME = 'message.created'
VERSION = '2026-07-28'


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')


def signing_key(secret):
    if not isinstance(secret, str) or not secret.startswith('whsec_'):
        raise ValueError('invalid signing secret')
    key = base64.b64decode(secret[6:], validate=True)
    if not 24 <= len(key) <= 64:
        raise ValueError('invalid signing key length')
    return key


def callback_parts(url):
    p = urlsplit(url)
    if (p.scheme != 'https' or not p.hostname or p.port not in (None, 443)
            or p.username or p.password or p.fragment or len(url) > 4096):
        raise ValueError('invalid callback URL')
    return p


def public_addresses(host):
    addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    def unsafe(ip):
        value=ipaddress.ip_address(ip)
        return not value.is_global or value.is_multicast or value.is_reserved or value.is_unspecified
    if not addresses or any(unsafe(ip) for ip in addresses):
        raise ValueError('non-public callback address')
    return addresses


def post_webhook(url, secret, subscription, event_id, value, old_secret=None):
    p = callback_parts(url)
    proxy = callback_proxy(p.hostname)
    addresses = public_addresses(p.hostname) if proxy is None else []
    print('mcp_callback_host='+p.hostname,flush=True)
    body = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
    if len(body) > 262144:
        raise ValueError('event too large')
    timestamp = str(int(time.time()))
    signed = event_id.encode() + b'.' + timestamp.encode() + b'.' + body
    keys = [secret] + ([old_secret] if old_secret else [])
    signatures = ' '.join('v1,' + base64.b64encode(hmac.digest(signing_key(k), signed, 'sha256')).decode() for k in keys)
    # Connect to the already validated IP, retaining original TLS SNI and Host.
    class PinnedHTTPS(http.client.HTTPSConnection):
        def connect(self):
            if proxy is not None:
                tunnel = http.client.HTTPConnection(proxy['host'], proxy['port'], timeout=10)
                credentials = (proxy['username']+':'+proxy['password']).encode()
                tunnel.set_tunnel(p.hostname, 443, headers={
                    'Proxy-Authorization': 'Basic '+base64.b64encode(credentials).decode()})
                try:
                    tunnel.connect()
                    raw = tunnel.sock
                    tunnel.sock = None
                    try:
                        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=p.hostname)
                    except BaseException:
                        raw.close()
                        raise
                finally:
                    tunnel.close()
                return
            raw = socket.create_connection((addresses[0], 443), timeout=10)
            print('mcp_callback_tcp_connected',flush=True)
            try:
                self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=p.hostname)
                print('mcp_callback_tls_connected',flush=True)
            except BaseException:
                raw.close()
                raise
    conn = PinnedHTTPS(p.hostname, timeout=10)
    try:
        conn.request('POST', (p.path or '/') + ('?' + p.query if p.query else ''), body=body,
                     headers={'Content-Type':'application/json', 'webhook-id':event_id,
                              'webhook-timestamp':timestamp, 'webhook-signature':signatures,
                              'X-MCP-Subscription-Id':subscription})
        response = conn.getresponse()
        data = response.read(65537)
        if len(data) > 65536:
            raise ValueError('callback response too large')
        return response.status, data  # No redirect handling.
    finally:
        conn.close()


def callback_proxy(host):
    """Opt-in trusted egress; exact administrator allowlist, no direct fallback.

    The proxy must restrict destinations and resolve the allowlisted names on
    its trusted egress. Never accept this configuration from an MCP request.
    """
    path = os.environ.get('WECHAT_CALLBACK_PROXY_FILE')
    if not path:
        return None
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    allowed = config.get('allowed_hosts', [])
    if not isinstance(allowed, list) or host not in allowed:
        raise ValueError('callback host not allowed by proxy configuration')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('callback must use an approved DNS name')
    if not isinstance(config.get('host'), str) or not config['host']:
        raise ValueError('invalid proxy host')
    port = config.get('port')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('invalid proxy port')
    if any(not isinstance(config.get(k), str) or not config[k] for k in ('username','password')):
        raise ValueError('proxy credentials required')
    return config


class Events:
    def __init__(self, provider, sender=post_webhook):
        self.provider, self.sender = provider, sender
        self.lock = asyncio.Lock()
        self.callbacks = {}
        self.verifications = {}
        self.delivering = set()
        self.callback_timeout = 15
        self.max_callbacks = 8

    async def callback(self, key, *args):
        # Timed-out threads still occupy their slot until the network call exits.
        # Do not start duplicate calls or grow the executor queue without bound.
        if key in self.callbacks or len(self.callbacks) >= self.max_callbacks:
            raise CallbackBusy('busy')
        task = asyncio.create_task(asyncio.to_thread(self.sender, *args))
        self.callbacks[key] = task
        def finished(done):
            self.callbacks.pop(key, None)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        return await asyncio.wait_for(asyncio.shield(task), self.callback_timeout)

    @property
    def store(self):
        return self.provider.store

    def initialize(self):
        self.store.db.execute('''CREATE TABLE IF NOT EXISTS mcp_event_subscriptions (
            id TEXT PRIMARY KEY, principal TEXT NOT NULL, conversation TEXT NOT NULL,
            encrypted BLOB NOT NULL, cursor INTEGER NOT NULL, expires REAL NOT NULL,
            status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0)''')

    async def auth(self, token):
        access = await self.provider.verify_token(token)
        if not access or 'wechat:bridge' not in access.scopes:
            raise PermissionError('invalid token')
        identity = (await self.provider.api_identity(token) if token.startswith('wna_')
                    else self.store.clients.authenticate(token))
        return access.client_id + ':' + identity.id, identity, access.client_id

    def definition(self):
        return {'name':NAME, 'description':'A new message from the paired owner in a specific WeChat or mobile web conversation. Subscribe only to the conversation registered for this chat.',
                'delivery':['webhook'],
                'inputSchema':{'type':'object','properties':{'conversation_id':{'type':'string','description':'Registered conversation ID owned by this client.'}},'required':['conversation_id'],'additionalProperties':False},
                'payloadSchema':{'type':'object','properties':{'conversation_id':{'type':'string'},'message_id':{'type':'integer'},'text':{'type':'string'},'source':{'type':'string'}},'required':['conversation_id','message_id','text','source'],'additionalProperties':False}}

    async def handle(self, method, params, token):
        principal, identity, oauth_client = await self.auth(token)
        if method == 'server/discover':
            return {'resultType':'complete','supportedVersions':[VERSION,'2025-11-25'],
                    'serverInfo':{'name':'WeChat Notifications','version':'1.9.1'},'capabilities':{'tools':{},'events':{}}}
        if method == 'events/list':
            return {'events':[self.definition()]}
        if params.get('name') != NAME or set(params.get('arguments', {})) != {'conversation_id'}:
            raise ValueError('invalid event filter')
        cid = params['arguments']['conversation_id']
        self.store.conversations.get(identity.id, cid, require_active=method == 'events/subscribe')
        delivery = params.get('delivery', {})
        if delivery.get('mode') != 'webhook':
            raise ValueError('only webhook delivery is supported')
        url = delivery.get('url', '')
        callback_parts(url)
        sid = 'sub_' + hashlib.sha256(json.dumps([principal, NAME, cid, url],separators=(',', ':')).encode()).hexdigest()
        async with self.lock:
            self.store.db.execute('DELETE FROM mcp_event_subscriptions WHERE expires<=?', (time.time(),))
            if method == 'events/unsubscribe':
                self.verifications.pop(sid, None)
                self.store.db.execute('DELETE FROM mcp_event_subscriptions WHERE id=? AND principal=?',(sid,principal))
                return {}
            secret = delivery.get('secret')
            signing_key(secret)
            existing=self.store.db.execute("SELECT 1 FROM mcp_event_subscriptions WHERE id=? AND status='active'",(sid,)).fetchone()
            if not existing and self.store.db.execute("SELECT count(*) FROM mcp_event_subscriptions WHERE principal=? AND status='active' AND expires>?",(principal,time.time())).fetchone()[0]>=20:
                raise ValueError('subscription limit')
            ttl = params.get('ttlMs',86400000)
            if ttl is not None and (isinstance(ttl,bool) or not isinstance(ttl,(int,float)) or ttl <= 0):
                raise ValueError('invalid ttl')
            ttl = min(86400,max(60,(ttl or 86400000)/1000))
            verification = object()
            self.verifications[sid] = verification
        try:
            challenge = secrets.token_urlsafe(32)
            try:
                status, raw = await self.callback(('verify', sid),url,secret,sid,'verify_'+secrets.token_hex(16),
                                                       {'type':'verification','challenge':challenge})
            except Exception as exc:
                print('mcp_callback_exception='+type(exc).__name__,flush=True)
                raise CallbackError('unreachable') from None
            try:
                echoed = json.loads(raw).get('challenge','')
                verified = 200 <= status < 300 and isinstance(echoed,str) and hmac.compare_digest(echoed,challenge)
            except (ValueError,AttributeError):
                verified = False
            if not verified:
                print('mcp_callback_status='+str(status),flush=True)
                raise CallbackError('challenge_failed')
        except BaseException:
            if self.verifications.get(sid) is verification:
                self.verifications.pop(sid, None)
            raise
        async with self.lock:
            if self.verifications.get(sid) is not verification:
                raise ValueError('subscription changed during verification')
            self.verifications.pop(sid, None)
            existing=self.store.db.execute("SELECT 1 FROM mcp_event_subscriptions WHERE id=? AND status='active'",(sid,)).fetchone()
            if not existing and self.store.db.execute("SELECT count(*) FROM mcp_event_subscriptions WHERE principal=? AND status='active' AND expires>?",(principal,time.time())).fetchone()[0]>=20:
                raise ValueError('subscription limit')
            # Recheck identity after outbound I/O, before persisting the subscription.
            await self.auth(token)
            self.store.conversations.get(identity.id,cid,require_active=True)
            old = self.store.db.execute('SELECT * FROM mcp_event_subscriptions WHERE id=?',(sid,)).fetchone()
            cursor = (old['cursor'] if old and old['expires']>time.time() else
                      self.store.db.execute("SELECT COALESCE(MAX(id),0) FROM inbox WHERE conversation_id=?",(cid,)).fetchone()[0])
            value = {'url':url,'secret':secret,'client':identity.id,'key_hash':identity.key_hash,'oauth_client':oauth_client}
            if token.startswith('wna_'):
                value['grant_id'] = self.provider.token_row(token, 'access')['grant_id']
            if old:
                previous=json.loads(self.store.cipher.decrypt(old['encrypted']))
                if previous['secret'] != secret:
                    value.update(old_secret=previous['secret'],rotation_until=time.time()+300)
                elif previous.get('rotation_until',0)>time.time():
                    value.update(old_secret=previous['old_secret'],rotation_until=previous['rotation_until'])
            expiry = time.time()+ttl
            self.store.db.execute('INSERT OR REPLACE INTO mcp_event_subscriptions VALUES (?,?,?,?,?,?,?,0,0)',
                (sid,principal,cid,self.store.cipher.encrypt(json.dumps(value).encode()),cursor,expiry,'active'))
            return {'id':sid,'refreshBefore':iso(expiry),'cursor':None,'truncated':False}

    def permitted(self, value, cid):
        self.provider.identity(value['client'],value['key_hash'])
        self.store.conversations.get(value['client'],cid,require_active=True)
        if not value['oauth_client'].startswith('api-key:'):
            row=self.store.db.execute('SELECT 1 FROM oauth_tokens WHERE grant_id=? AND oauth_client=? AND api_client=? AND key_hash=? AND expires_at>? LIMIT 1',
                (value.get('grant_id'),value['oauth_client'],value['client'],value['key_hash'],time.time())).fetchone()
            if not row:
                raise PermissionError('connection revoked')

    async def deliver_one(self, sub):
        sid = sub['id']
        if sid in self.delivering:
            return
        self.delivering.add(sid)
        try:
            await self.deliver_snapshot(sub)
        finally:
            self.delivering.discard(sid)

    async def deliver_snapshot(self, sub):
        async with self.lock:
            current = self.store.db.execute('SELECT * FROM mcp_event_subscriptions WHERE id=?', (sub['id'],)).fetchone()
            if not current or tuple(current) != tuple(sub) or sub['expires'] <= time.time():
                return
            value=json.loads(self.store.cipher.decrypt(sub['encrypted']))
            try:
                self.permitted(value,sub['conversation'])
            except Exception:
                self.store.db.execute("UPDATE mcp_event_subscriptions SET status='revoked' WHERE id=?",(sub['id'],))
                return
            row=self.store.db.execute("SELECT * FROM inbox WHERE conversation_id=? AND id>? AND kind='message' AND route_status='direct' ORDER BY id LIMIT 1",(sub['conversation'],sub['cursor'])).fetchone()
            if not row:
                return
            body=json.loads(self.store.cipher.decrypt(row['encrypted']))
            eid='wechat_'+sub['conversation']+'_'+str(row['id'])
            event={'eventId':eid,'name':NAME,'timestamp':iso(row['received_at']),
                   'data':{'conversation_id':sub['conversation'],'message_id':row['id'],
                           'text':str(body.get('text',''))[:20000],'source':body.get('source','wechat')},'cursor':None}
        try:
            old=value.get('old_secret') if value.get('rotation_until',0)>time.time() else None
            status,_=await self.callback(('delivery', sub['id']),value['url'],value['secret'],sub['id'],eid,event,old)
        except CallbackBusy:
            return
        except Exception:
            status=0
        async with self.lock:
            current = self.store.db.execute('SELECT * FROM mcp_event_subscriptions WHERE id=?', (sub['id'],)).fetchone()
            # A late result must not overwrite refresh, unsubscribe, archive or deletion.
            if not current or tuple(current) != tuple(sub) or current['expires'] <= time.time():
                return
            try:
                self.permitted(value, sub['conversation'])
            except Exception:
                self.store.db.execute("UPDATE mcp_event_subscriptions SET status='revoked' WHERE id=?", (sub['id'],))
                return
            if 200 <= status < 300:
                self.store.db.execute('UPDATE mcp_event_subscriptions SET cursor=?,attempts=0,next_attempt=0 WHERE id=?',(row['id'],sub['id']))
            else:
                attempts=sub['attempts']+1
                terminal=status in (410,413) or (400<=status<500 and status not in (408,429)) or attempts>=6
                self.store.db.execute('UPDATE mcp_event_subscriptions SET attempts=?,next_attempt=?,status=? WHERE id=?',
                    (attempts,time.time()+min(300,2**attempts),'failed' if terminal else 'active',sub['id']))

    async def tick(self):
        async with self.lock:
            rows=self.store.db.execute("SELECT * FROM mcp_event_subscriptions WHERE status='active' AND expires>? AND next_attempt<=? LIMIT 100",(time.time(),time.time())).fetchall()
        await asyncio.gather(*(self.deliver_one(sub) for sub in rows))

    async def run(self):
        while True:
            try:
                await self.tick()
            except Exception:
                pass  # Do not leak callback URLs, secrets, or message text to logs.
            await asyncio.sleep(3)


class CallbackError(Exception):
    pass


class CallbackBusy(CallbackError):
    pass


class EventGateway:
    def __init__(self, app, events, host):
        self.app,self.events,self.host=app,events,host

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] != 'POST' or scope['path'].rstrip('/') != '/mcp':
            return await self.app(scope,receive,send)
        request=Request(scope,receive)
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>65536:
                return await JSONResponse({'error':'request_too_large'},status_code=413)(scope,receive,send)
        async def replay():
            return {'type':'http.request','body':bytes(raw),'more_body':False}
        try:
            value=json.loads(raw)
        except ValueError:
            return await self.app(scope,replay,send)
        method=value.get('method') if isinstance(value,dict) else None
        if method not in ('server/discover','events/list','events/subscribe','events/unsubscribe'):
            # Tools retain the existing tested SDK implementation. New event hosts
            # may reuse their discovery protocol header for ordinary tool calls.
            if request.headers.get('mcp-protocol-version')==VERSION:
                scope=dict(scope,headers=[(k,b'2025-11-25' if k.lower()==b'mcp-protocol-version' else v) for k,v in scope['headers']])
            return await self.app(scope,replay,send)
        if request.headers.get('host') != self.host or (request.headers.get('origin') and request.headers['origin']!='https://'+self.host):
            return await JSONResponse({'error':'invalid_origin'},status_code=403)(scope,replay,send)
        auth=request.headers.get('authorization','')
        rid=value.get('id')
        # Method-only diagnostics: never log credentials, callback URLs, or payloads.
        print('mcp_event_method='+method,flush=True)
        try:
            if not auth.lower().startswith('bearer '):
                raise PermissionError()
            if value.get('jsonrpc') != '2.0' or not isinstance(value.get('params',{}),dict):
                raise ValueError('invalid request')
            result=await self.events.handle(method,value.get('params',{}),auth[7:])
            response={'jsonrpc':'2.0','id':rid,'result':result}
        except PermissionError:
            base=urlsplit(self.events.provider.base)
            metadata=base.scheme+'://'+base.netloc+'/.well-known/oauth-protected-resource'+base.path+'/mcp'
            return await JSONResponse({'error':'unauthorized'},status_code=401,
                headers={'WWW-Authenticate':'Bearer resource_metadata="'+metadata+'"'})(scope,replay,send)
        except CallbackError:
            response={'jsonrpc':'2.0','id':rid,'error':{'code':-32015,'message':'Callback verification failed','data':{'reason':'challenge_failed'}}}
        except Exception as exc:
            print('mcp_event_error='+type(exc).__name__,flush=True)
            response={'jsonrpc':'2.0','id':rid,'error':{'code':-32602,'message':'Invalid or unauthorized event request'}}
        await JSONResponse(response)(scope,replay,send)
