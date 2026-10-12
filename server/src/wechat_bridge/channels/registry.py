"""Administrator-owned bots and explicit per-client bot grants."""
import time
import uuid

from wechat_bridge.storage.client_registry import ClientError

DEFAULT = 'default'
FEISHU_DEFAULT = 'feishu-default'


class BotRegistry:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS bots (
            id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, platform TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS client_bot_defaults (client_id TEXT PRIMARY KEY, bot_id TEXT);
          CREATE TABLE IF NOT EXISTS client_bot_grants (client_id TEXT NOT NULL, bot_id TEXT NOT NULL,
            PRIMARY KEY(client_id,bot_id));
          CREATE TABLE IF NOT EXISTS outgoing_bots (outgoing_key TEXT PRIMARY KEY,bot_id TEXT NOT NULL);
        ''')
        for id, name, platform, enabled in ((DEFAULT,'微信默认','wechat',1),(FEISHU_DEFAULT,'飞书默认','feishu',0)):
            self.db.execute('INSERT OR IGNORE INTO bots VALUES (?,?,?,?,?)', (id,name,platform,enabled,time.time()))
        self.ensure_clients()
        store.clients.on_create = self.grant_legacy

    def ensure_clients(self):
        for row in self.db.execute('SELECT id FROM api_clients'):
            if not self.db.execute('SELECT 1 FROM client_bot_defaults WHERE client_id=?',(row['id'],)).fetchone():
                self.grant_legacy(row['id'])

    def grant_legacy(self, client_id):
        self.set_grants(client_id, [DEFAULT], DEFAULT)

    @staticmethod
    def name(value):
        value = value.strip()
        if not value or len(value) > 40 or any(ord(c)<32 for c in value):
            raise ClientError('invalid_bot_name',422)
        return value

    def get(self, id):
        row = self.db.execute('SELECT * FROM bots WHERE id=?',(id,)).fetchone()
        if not row:
            raise ClientError('bot_not_found',404)
        return dict(row)

    def list(self):
        return [dict(row) for row in self.db.execute('SELECT * FROM bots ORDER BY created_at,id')]

    def create(self, name, platform):
        if platform not in ('wechat','feishu'):
            raise ClientError('unsupported_bot_platform',422)
        name = self.name(name)
        if self.db.execute('SELECT 1 FROM bots WHERE name=?',(name,)).fetchone():
            raise ClientError('bot_name_conflict')
        if self.db.execute('SELECT count(*) FROM bots').fetchone()[0] >= 32:
            raise ClientError('bot_limit_reached',429)
        id = uuid.uuid4().hex
        self.db.execute('INSERT INTO bots VALUES (?,?,?,?,?)',(id,name,platform,1,time.time()))
        return self.get(id)

    def update(self, id, name, enabled):
        self.get(id)
        name = self.name(name)
        if self.db.execute('SELECT 1 FROM bots WHERE name=? AND id<>?',(name,id)).fetchone():
            raise ClientError('bot_name_conflict')
        self.db.execute('UPDATE bots SET name=?,enabled=? WHERE id=?',(name,int(enabled),id))
        return self.get(id)

    def grants(self, client_id):
        self.store.clients.get(client_id)
        # Clients imported by a legacy seed or created by a legacy /getkey keep only WeChat access.
        row = self.db.execute('SELECT bot_id FROM client_bot_defaults WHERE client_id=?',(client_id,)).fetchone()
        if row is None:
            return dict(bot_ids=[DEFAULT],default_bot_id=DEFAULT)
        ids = [r[0] for r in self.db.execute('SELECT bot_id FROM client_bot_grants WHERE client_id=? ORDER BY bot_id',(client_id,))]
        return dict(bot_ids=ids,default_bot_id=row[0])

    def set_grants(self, client_id, bot_ids, default_bot_id):
        self.store.clients.get(client_id)
        if len(bot_ids) != len(set(bot_ids)) or len(bot_ids)>32 or (default_bot_id and default_bot_id not in bot_ids):
            raise ClientError('invalid_bot_grants',422)
        for id in bot_ids:
            self.get(id)
        # May be called inside an existing command/client transaction.
        self.db.execute('SAVEPOINT bot_grants')
        try:
            self.db.execute('DELETE FROM client_bot_grants WHERE client_id=?',(client_id,))
            self.db.executemany('INSERT INTO client_bot_grants VALUES (?,?)',[(client_id,id) for id in bot_ids])
            self.db.execute('INSERT OR REPLACE INTO client_bot_defaults VALUES (?,?)',(client_id,default_bot_id))
            self.db.execute('RELEASE bot_grants')
        except Exception:
            self.db.execute('ROLLBACK TO bot_grants'); self.db.execute('RELEASE bot_grants')
            raise
        return self.grants(client_id)

    def allowed(self, client_id, bot_id):
        return bot_id in self.grants(client_id)['bot_ids']

    def select(self, identity, bot_id=None, platform=None, *, sending=True):
        self.store.clients.revalidate(identity)
        grant = self.grants(identity.id)
        if bot_id:
            if bot_id not in grant['bot_ids']:
                raise ClientError('bot_access_denied',403)
            bot = self.get(bot_id)
            if platform and bot['platform'] != platform:
                raise ClientError('bot_platform_conflict',422)
        else:
            default = self.get(grant['default_bot_id']) if grant['default_bot_id'] else None
            if default and (not platform or default['platform']==platform):
                bot = default
            else:
                candidates = [self.get(id) for id in grant['bot_ids'] if not platform or self.get(id)['platform']==platform]
                if len(candidates) != 1:
                    raise ClientError('bot_required',409)
                bot = candidates[0]
        if sending and not bot['enabled']:
            raise ClientError('bot_disabled',409)
        return bot

    def scope(self, client_id):
        ids = self.grants(client_id)['bot_ids']
        if not ids:
            return '(bot_id IS NULL)', []
        return '(bot_id IS NULL OR bot_id IN (' + ','.join('?' for _ in ids) + '))', ids

    def check_wechat_binding(self, bot_id, account):
        for bot in self.list():
            if bot['id']==bot_id or bot['platform']!='wechat': continue
            other = self.store.account() if bot['id']==DEFAULT else self.store.channels.settings('wechat:'+bot['id'])
            if other and (other.get('user_id'),other.get('bot_id'))==(account.get('user_id'),account.get('bot_id')):
                raise ClientError('bot_binding_conflict')


class BotConversations:
    """Incoming tags may only address clients granted this bot."""
    def __init__(self, registry, bot_id):
        self.registry, self.bot_id = registry, bot_id
        self.core = registry.store.conversations

    def __getattr__(self, name):
        return getattr(self.core, name)

    def route(self, text):
        cid, status, body, tag = self.core.route(text)
        if cid:
            row = self.registry.db.execute('SELECT client_id FROM conversations WHERE id=?',(cid,)).fetchone()
            if not row or not self.registry.allowed(row['client_id'],self.bot_id):
                return None, 'unknown', text, tag
        return cid, status, body, tag
