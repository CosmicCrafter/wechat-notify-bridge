"""Private MCP OAuth grants, bound to an existing API client and key generation."""
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from mcp.server.auth.provider import (AccessToken, AuthorizationCode, AuthorizationParams,
    RefreshToken, TokenError, AuthorizeError, RegistrationError)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from wechat_bridge.storage.client_registry import ClientError, Identity
from wechat_bridge.config import COOKIE, WEB, public_base

SCOPE = 'wechat:bridge'
UNAUTHORIZED_CLIENT_TTL = 600
MAX_CLIENTS = 1000


def digest(value): return hashlib.sha256(value.encode()).hexdigest()


class Provider:
    def __init__(self, app, base):
        self.app, self.base = app, base
        self.resource = base + '/mcp'

    @property
    def store(self): return self.app.state.bridge.store

    def initialize(self):
        self.store.db.executescript('''
          CREATE TABLE IF NOT EXISTS oauth_clients (id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS oauth_pending (id TEXT PRIMARY KEY, metadata TEXT NOT NULL, expires_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS oauth_codes (hash TEXT PRIMARY KEY, metadata TEXT NOT NULL, expires_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS oauth_tokens (hash TEXT PRIMARY KEY, kind TEXT NOT NULL, grant_id TEXT NOT NULL,
            oauth_client TEXT NOT NULL, api_client TEXT NOT NULL, key_hash TEXT NOT NULL, scopes TEXT NOT NULL,
            expires_at REAL NOT NULL);
        ''')

        columns = {r['name'] for r in self.store.db.execute('PRAGMA table_info(oauth_clients)')}
        if 'created_at' not in columns:
            self.store.db.execute('BEGIN IMMEDIATE')
            try:
                self.store.db.execute('ALTER TABLE oauth_clients ADD COLUMN created_at REAL NOT NULL DEFAULT 0')
                self.store.db.execute('ALTER TABLE oauth_clients ADD COLUMN approved INTEGER NOT NULL DEFAULT 0')
                # Legacy registrations get a grace period; preserve existing authorized clients.
                self.store.db.execute('UPDATE oauth_clients SET created_at=?', (time.time(),))
                self.store.db.execute('UPDATE oauth_clients SET approved=1 WHERE id IN (SELECT oauth_client FROM oauth_tokens WHERE expires_at>?)', (time.time(),))
                for row in self.store.db.execute('SELECT metadata FROM oauth_codes WHERE expires_at>?', (time.time(),)).fetchall():
                    self.store.db.execute('UPDATE oauth_clients SET approved=1 WHERE id=?', (json.loads(row[0])['client_id'],))
                self.store.db.commit()
            except Exception:
                self.store.db.rollback()
                raise
        self.cleanup_clients()

    def cleanup_clients(self):
        self.store.db.execute('DELETE FROM oauth_clients WHERE approved=0 AND created_at<?',
                              (time.time()-UNAUTHORIZED_CLIENT_TTL,))

    async def register_client(self, client_info):
        for uri in client_info.redirect_uris or []:
            p = urlsplit(str(uri))
            if p.fragment or p.username or p.password or (p.scheme != 'https' and not
                    (p.scheme == 'http' and p.hostname in ('localhost', '127.0.0.1', '::1'))):
                raise RegistrationError('invalid_redirect_uri', 'HTTPS or loopback callback required')
        self.cleanup_clients()
        if self.store.db.execute('SELECT count(*) FROM oauth_clients').fetchone()[0] >= MAX_CLIENTS:
            raise RegistrationError('invalid_client_metadata', 'Registration capacity reached')
        # SDK-generated client secrets are encrypted, never returned by the owner UI.
        encoded = self.store.cipher.encrypt(client_info.model_dump_json().encode()).decode()
        self.store.db.execute('INSERT INTO oauth_clients(id,metadata,created_at,approved) VALUES (?,?,?,0)', (client_info.client_id, encoded, time.time()))

    async def get_client(self, client_id):
        self.cleanup_clients()
        row = self.store.db.execute('SELECT metadata FROM oauth_clients WHERE id=?', (client_id,)).fetchone()
        return OAuthClientInformationFull.model_validate_json(self.store.cipher.decrypt(row[0])) if row else None

    async def authorize(self, client, params):
        if params.resource != self.resource:
            raise AuthorizeError('invalid_request', 'The exact MCP resource is required')
        if params.scopes != [SCOPE]:
            raise AuthorizeError('invalid_scope', 'wechat:bridge scope required')
        now = time.time()
        self.store.db.execute('DELETE FROM oauth_pending WHERE expires_at<?', (now,))
        self.store.db.execute('DELETE FROM oauth_codes WHERE expires_at<?', (now,))
        if self.store.db.execute('SELECT count(*) FROM oauth_pending').fetchone()[0] >= 1000:
            raise AuthorizeError('temporarily_unavailable', 'Too many pending authorizations')
        sid = secrets.token_urlsafe(32)
        value = dict(client_id=client.client_id, params=params.model_dump(mode='json'))
        self.store.db.execute('INSERT INTO oauth_pending VALUES (?,?,?)', (digest(sid), json.dumps(value), now+600))
        return self.base + '/chat/oauth/?request=' + sid

    def pending(self, sid):
        row = self.store.db.execute('SELECT metadata FROM oauth_pending WHERE id=? AND expires_at>?',
                                    (digest(sid), time.time())).fetchone()
        if not row: raise HTTPException(410, 'authorization_request_expired')
        return json.loads(row[0])

    def consent(self, sid, api_client, allow):
        value = self.pending(sid)
        params = AuthorizationParams.model_validate(value['params'])
        values = {'state': params.state} if params.state is not None else {}
        if allow:
            if not self.store.db.execute('SELECT 1 FROM oauth_clients WHERE id=?',(value['client_id'],)).fetchone():
                raise HTTPException(410, 'authorization_request_expired')
            row = self.store.clients.get(api_client)
            if not row['enabled']: raise HTTPException(409, 'client_disabled')
            self.store.db.execute('UPDATE oauth_clients SET approved=1 WHERE id=?',(value['client_id'],))
            code = secrets.token_urlsafe(32)
            meta = dict(params=params.model_dump(mode='json'), client_id=value['client_id'],
                        api_client=row['id'], key_hash=row['key_hash'])
            self.store.db.execute('INSERT INTO oauth_codes VALUES (?,?,?)',
                                  (digest(code), json.dumps(meta), time.time()+120))
            values['code'] = code
        else:
            values['error'] = 'access_denied'
        self.store.db.execute('DELETE FROM oauth_pending WHERE id=?', (digest(sid),))
        p = urlsplit(str(params.redirect_uri))
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode(parse_qsl(p.query)+list(values.items())), ''))

    async def load_authorization_code(self, client, authorization_code):
        row = self.store.db.execute('SELECT metadata,expires_at FROM oauth_codes WHERE hash=?', (digest(authorization_code),)).fetchone()
        if not row: return None
        value = json.loads(row[0])
        if value['client_id'] != client.client_id: return None
        p = value['params']
        return AuthorizationCode(code=authorization_code, client_id=client.client_id, scopes=p['scopes'],
            expires_at=row[1], code_challenge=p['code_challenge'], redirect_uri=p['redirect_uri'],
            redirect_uri_provided_explicitly=p['redirect_uri_provided_explicitly'], resource=p['resource'])

    def identity(self, api_client, key_hash):
        row = self.store.clients.get(api_client)
        return self.store.clients.revalidate(Identity(row['id'], row['name'], key_hash, row['legacy_name']))

    def issue(self, client_id, api_client, key_hash, scopes, grant_id=None):
        self.identity(api_client, key_hash)
        access, refresh, grant = 'wna_'+secrets.token_urlsafe(32), 'wnr_'+secrets.token_urlsafe(32), grant_id or secrets.token_hex(16)
        now = time.time()
        self.store.db.execute('DELETE FROM oauth_tokens WHERE expires_at<?', (now,))
        for token, kind, expiry in [(access, 'access', now+3600), (refresh, 'refresh', now+30*86400)]:
            self.store.db.execute('INSERT INTO oauth_tokens VALUES (?,?,?,?,?,?,?,?)',
                (digest(token), kind, grant, client_id, api_client, key_hash, json.dumps(scopes), expiry))
        return OAuthToken(access_token=access, token_type='Bearer', expires_in=3600, refresh_token=refresh, scope=' '.join(scopes))

    async def exchange_authorization_code(self, client, authorization_code):
        db = self.store.db
        db.execute('BEGIN IMMEDIATE')
        try:
            row = db.execute('SELECT metadata,expires_at FROM oauth_codes WHERE hash=?', (digest(authorization_code.code),)).fetchone()
            if not row or row[1] <= time.time(): raise TokenError('invalid_grant', 'Expired or consumed code')
            value = json.loads(row[0])
            if value['client_id'] != client.client_id: raise TokenError('invalid_grant')
            db.execute('DELETE FROM oauth_codes WHERE hash=?', (digest(authorization_code.code),))
            token = self.issue(client.client_id, value['api_client'], value['key_hash'], authorization_code.scopes)
            db.commit()
            return token
        except ClientError:
            db.rollback(); raise TokenError('invalid_grant', 'Client credential revoked') from None
        except Exception:
            db.rollback(); raise

    def token_row(self, token, kind):
        row = self.store.db.execute('SELECT * FROM oauth_tokens WHERE hash=? AND kind=? AND expires_at>?',
                                    (digest(token), kind, time.time())).fetchone()
        if row:
            try: self.identity(row['api_client'], row['key_hash'])
            except ClientError: return None
        return row

    async def load_refresh_token(self, client, refresh_token):
        row = self.token_row(refresh_token, 'refresh')
        if not row or row['oauth_client'] != client.client_id: return None
        return RefreshToken(token=refresh_token, client_id=client.client_id, scopes=json.loads(row['scopes']),
                            expires_at=int(row['expires_at']), resource=self.resource, subject=row['api_client'])

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        db = self.store.db; db.execute('BEGIN IMMEDIATE')
        try:
            row = self.token_row(refresh_token.token, 'refresh')
            if not row or row['oauth_client'] != client.client_id: raise TokenError('invalid_grant')
            if not set(scopes).issubset(json.loads(row['scopes'])): raise TokenError('invalid_scope')
            db.execute('DELETE FROM oauth_tokens WHERE grant_id=?', (row['grant_id'],))
            token = self.issue(client.client_id, row['api_client'], row['key_hash'], scopes, grant_id=row['grant_id'])
            db.commit(); return token
        except Exception:
            db.rollback(); raise

    async def load_access_token(self, token):
        row = self.token_row(token, 'access')
        if row:
            return AccessToken(token=token, client_id=row['oauth_client'], scopes=json.loads(row['scopes']),
                expires_at=int(row['expires_at']), resource=self.resource, subject=row['api_client'])
        # Existing local clients may keep using their own private API-key configuration.
        if not token.startswith(('wna_', 'wnr_')):
            try: identity = self.store.clients.authenticate(token)
            except ClientError: return None
            return AccessToken(token=token, client_id='api-key:'+identity.id, scopes=[SCOPE],
                               resource=self.resource, subject=identity.id)
        return None

    async def verify_token(self, token):
        return await self.load_access_token(token)

    async def api_identity(self, token):
        row = self.token_row(token, 'access')
        if not row or SCOPE not in json.loads(row['scopes']): raise ClientError('invalid_client_key', 401)
        return self.identity(row['api_client'], row['key_hash'])

    async def revoke_token(self, token):
        row = self.store.db.execute('SELECT grant_id FROM oauth_tokens WHERE hash=?', (digest(token.token),)).fetchone()
        if row: self.store.db.execute('DELETE FROM oauth_tokens WHERE grant_id=?', (row[0],))


class Consent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=40, max_length=64)
    api_client: str = Field(max_length=64)
    allow: bool


def mount_consent(app, provider):
    def owner(request):
        row = provider.store.db.execute('SELECT expires_at FROM web_sessions WHERE token_hash=?',
            (digest(request.cookies.get(COOKIE, '')),)).fetchone()
        if not row or row[0] <= time.time(): raise HTTPException(401, 'login_required')

    @app.get('/chat/oauth/', include_in_schema=False)
    async def page(): return FileResponse(WEB / 'oauth' / 'index.html')

    @app.get('/chat/oauth/app.js', include_in_schema=False)
    async def script(): return FileResponse(WEB / 'oauth' / 'app.js', media_type='text/javascript')

    @app.get('/chat/oauth/request', include_in_schema=False)
    async def info(request: Request, request_id: str):
        owner(request)
        value = provider.pending(request_id)
        client = await provider.get_client(value['client_id'])
        if client is None:
            raise HTTPException(410, 'authorization_request_expired')
        return {'client_name':client.client_name or 'MCP 客户端', 'redirect_uri':str(value['params']['redirect_uri']),
                'clients':[c for c in provider.store.clients.list() if c['enabled']]}

    @app.post('/chat/oauth/consent', include_in_schema=False)
    async def consent(request: Request, body: Consent):
        owner(request)
        base = urlsplit(public_base())
        if request.headers.get('Origin') != base.scheme+'://'+base.netloc or request.headers.get('X-Chat-Request') != '1':
            raise HTTPException(403, 'same_origin_required')
        async with app.state.bridge.lock:
            return {'redirect':provider.consent(body.request_id, body.api_client, body.allow)}
