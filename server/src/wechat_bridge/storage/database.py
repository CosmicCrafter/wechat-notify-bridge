"""SQLite schema, migration and encrypted persistent state."""
import hashlib
import json
import sqlite3
import time
from cryptography.fernet import Fernet
from wechat_bridge.storage.client_registry import ClientRegistry
from wechat_bridge.storage.conversations import Conversations
from wechat_bridge.services.commands import command_text, execute as execute_command
from wechat_bridge.services.portal import Portal
from wechat_bridge.wechat.protocol import BridgeError, INTERVAL, ACCEPTED, validate_base, send_recovery_hint

class Store:
    def __init__(self, path, key):
        self.cipher = Fernet(key)
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK(id=1), encrypted BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS outgoing (
            key TEXT PRIMARY KEY, message_hash TEXT NOT NULL, status TEXT NOT NULL,
            kind TEXT NOT NULL, caller TEXT NOT NULL, attempted_at REAL NOT NULL,
            finished_at REAL, error_code TEXT);
          CREATE TABLE IF NOT EXISTS inbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT, identity TEXT UNIQUE NOT NULL,
            received_at REAL NOT NULL, message_at REAL NOT NULL, encrypted BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS command_replies (
            id INTEGER PRIMARY KEY, encrypted_reply BLOB, status TEXT NOT NULL,
            client_id TEXT, issued_hash TEXT);
        ''')
        if 'kind' not in {row['name'] for row in self.db.execute('PRAGMA table_info(inbox)')}:
            self.db.execute("ALTER TABLE inbox ADD COLUMN kind TEXT NOT NULL DEFAULT 'message'")
        self.clients = ClientRegistry(self.db)
        self.conversations = Conversations(self.db)
        columns = {row['name'] for row in self.db.execute('PRAGMA table_info(inbox)')}
        if 'conversation_id' not in columns:
            self.db.execute('ALTER TABLE inbox ADD COLUMN conversation_id TEXT')
        if 'route_status' not in columns:
            self.db.execute("ALTER TABLE inbox ADD COLUMN route_status TEXT NOT NULL DEFAULT 'shared'")
        self.portal = Portal(self)

    def close(self):
        self.db.close()

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, json.dumps(value)))

    def transaction(self):
        return self.db

    def account(self):
        row = self.db.execute('SELECT encrypted FROM account WHERE id=1').fetchone()
        return json.loads(self.cipher.decrypt(row[0])) if row else None

    def save_account(self, value):
        validate_base(value['base_url'])
        encrypted = self.cipher.encrypt(json.dumps(value).encode())
        self.db.execute('INSERT OR REPLACE INTO account VALUES (1,?)', (encrypted,))

    def bootstrap(self, encrypted_bundle):
        if self.account() is not None:
            return
        bundle = json.loads(self.cipher.decrypt(encrypted_bundle))
        account = bundle['credentials']
        for k in ('bot_token', 'user_id', 'base_url', 'context_token'):
            if not account.get(k):
                raise ValueError('Incomplete bootstrap')
        latest = max(account.get('bound_at', 0), account.get('context_received_at', 0))
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.save_account(account)
            for digest, row in bundle.get('outgoing', {}).items():
                if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    raise ValueError('Invalid legacy journal')
                self.db.execute('INSERT OR IGNORE INTO outgoing VALUES (?,?,?,?,?,?,?,?)',
                    (digest, row['message_hash'], row['status'], 'legacy', 'legacy',
                     row['attempted_at'], row.get('phone_confirmed_at'), None))
                if row['status'] in ACCEPTED:
                    latest = max(latest, row['attempted_at'])
            self.set('last_activity_at', min(time.time(), latest or time.time()))
            self.set('heartbeat_interval_seconds', INTERVAL)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def touch(self, at):
        self.set('last_activity_at', max(at, self.get('last_activity_at', 0)))

    def bind(self, account):
        """Replace credentials for the same owner; keep message and dedup history."""
        for field in ('bot_token', 'bot_id', 'user_id', 'base_url'):
            if not isinstance(account.get(field), str) or not account[field]:
                raise ValueError('Incomplete binding')
        validate_base(account['base_url'])
        current = self.account()
        if current and current['user_id'] != account['user_id']:
            raise BridgeError(409, 'owner_mismatch')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.save_account(account)
            self.db.execute("DELETE FROM state WHERE key IN ('last_activity_at', 'last_heartbeat_attempt_at', "
                            "'last_heartbeat_status', 'last_poll_success_at', 'last_poll_error_code')")
            self.set('poll_status', 'starting')
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def next_heartbeat(self):
        return max(self.get('last_activity_at', 0), self.get('last_heartbeat_attempt_at', 0)) + INTERVAL

    def digest(self, dedup_key, client_id=None, conversation_id=None):
        account_hash = hashlib.sha256(self.account()['user_id'].encode()).hexdigest()
        scope = '\nclient:' + client_id if client_id else ''
        if conversation_id: scope += '\nconversation:' + conversation_id
        return hashlib.sha256((account_hash + scope + '\n' + dedup_key).encode()).hexdigest()

    def client_receipt(self, dedup_key, identity, conversation_id=None):
        row = self.receipt(self.digest(dedup_key, identity.id, conversation_id))
        if row is None and identity.legacy_name and not conversation_id:
            legacy = self.receipt(self.digest(dedup_key))
            if legacy and legacy['caller'] in (identity.legacy_name, 'legacy'):
                row = legacy
        return row

    def receipt(self, digest):
        row = self.db.execute('SELECT * FROM outgoing WHERE key=?', (digest,)).fetchone()
        return dict(row) if row else None

    def ingest(self, update, now):
        account = self.account()
        added = 0
        commands = []
        self.db.execute('BEGIN IMMEDIATE')
        try:
            for msg in update.get('msgs', []):
                if (msg.get('from_user_id') != account['user_id'] or msg.get('message_type') != 1
                        or msg.get('message_state') not in (None, 0, 2) or msg.get('delete_time_ms')):
                    continue
                command = command_text(msg)
                if command is not None and (msg.get('message_state') == 0 or
                        not (msg.get('message_id') or msg.get('seq'))):
                    continue
                identity_data = {'message_id': msg.get('message_id'), 'seq': msg.get('seq')}
                if not any(identity_data.values()):
                    identity_data = msg
                identity = hashlib.sha256(json.dumps(identity_data, sort_keys=True).encode()).hexdigest()
                if command is not None:
                    event = ['command', account['user_id'], msg.get('message_id') or 'seq:' + str(msg['seq'])]
                    identity = hashlib.sha256(json.dumps(event).encode()).hexdigest()
                stamp = msg.get('create_time_ms')
                at = min(now, stamp / 1000) if isinstance(stamp, (float, int)) and stamp > 0 else now
                texts = []
                kinds = []
                for item in msg.get('item_list', []):
                    kinds.append(item.get('type'))
                    text = item.get('text_item', {}).get('text') or item.get('voice_item', {}).get('text')
                    if isinstance(text, str):
                        texts.append(text)
                content = {'text': '\n'.join(texts), 'item_types': kinds}
                conversation_id, route_status = None, 'shared'
                if command is None:
                    conversation_id, route_status, content['text'], tag = self.conversations.route(content['text'])
                    if tag: content['routing_tag'] = tag
                cursor = self.db.execute('INSERT OR IGNORE INTO inbox(identity,received_at,message_at,encrypted,kind,conversation_id,route_status) VALUES (?,?,?,?,?,?,?)',
                    (identity, now, at, self.cipher.encrypt(json.dumps(content).encode()),
                     'command' if command is not None else 'message', conversation_id, route_status))
                changed = cursor.rowcount
                if changed:
                    added += 1
                    if command is None and conversation_id:
                        self.portal.add(conversation_id, 'user', 'wechat', content['text'], 'pending',
                                        inbox_id=cursor.lastrowid, at=at)
                    self.touch(at)
                    if msg.get('context_token') and at >= account.get('context_received_at', 0):
                        account['context_token'] = msg['context_token']
                        account['context_received_at'] = at
                    if command is not None:
                        # Old backlog is not permission to rotate/revoke today's keys.
                        if now - at > 600 or at < account.get('bound_at', 0) - 30:
                            self.db.execute("INSERT INTO command_replies(id,status) VALUES (?, 'ignored_old')", (cursor.lastrowid,))
                        else:
                            commands.append((cursor.lastrowid, command))
            if update.get('get_updates_buf'):
                account['get_updates_buf'] = update['get_updates_buf']
            self.save_account(account)
            self.set('last_poll_success_at', now)
            self.set('poll_status', 'receiving')
            for id, text in commands:
                reply = execute_command(self, text)
                self.db.execute('INSERT INTO command_replies VALUES (?,?,?,?,?)',
                    (id, self.cipher.encrypt(reply.text.encode()), 'pending', reply.client_id, reply.issued_hash))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return added

    def inbox(self, after_id, limit, conversation_id=None, include_unaddressed=False):
        if conversation_id:
            where = '(conversation_id=?' + (" OR route_status!='direct')" if include_unaddressed else ')')
            args = (after_id, conversation_id, limit)
        else:
            where, args = "route_status!='direct'", (after_id, limit)
        rows = self.db.execute("SELECT id,received_at,message_at,encrypted,conversation_id,route_status FROM inbox "
                               "WHERE id>? AND kind='message' AND " + where + ' ORDER BY id LIMIT ?', args).fetchall()
        self.db.executemany("UPDATE chat_messages SET status='client_read' WHERE inbox_id=? AND status IN ('pending','legacy')",
                            [(r['id'],) for r in rows])
        return [dict(id=r['id'], received_at=r['received_at'], message_at=r['message_at'],
                     conversation_id=r['conversation_id'], route_status=r['route_status'],
                     **json.loads(self.cipher.decrypt(r['encrypted']))) for r in rows]

    def status(self):
        now = time.time()
        account = self.account()
        last_send = self.db.execute('SELECT status,error_code,attempted_at FROM outgoing ORDER BY attempted_at DESC LIMIT 1').fetchone()
        ready = bool(account and account.get('context_token'))
        poll = self.get('poll_status', 'starting') if account else 'unbound'
        connection = 'unbound' if not account else (
            'session_expired' if poll == 'session_expired' else
            'retrying' if poll == 'retrying' else
            'waiting_message' if not ready else
            'connected' if poll == 'receiving' and now - self.get('last_poll_success_at', 0) < 120 else
            'connecting')
        return {'status': 'running', 'recipient': 'paired_owner' if account else None,
                'bound': bool(account), 'context_ready': ready, 'connection_status': connection,
                'last_activity_at': self.get('last_activity_at'),
                'next_heartbeat_at': self.next_heartbeat() if ready and poll != 'session_expired' else None,
                'heartbeat_interval_seconds': INTERVAL,
                'last_heartbeat_attempt_at': self.get('last_heartbeat_attempt_at'),
                'last_heartbeat_status': self.get('last_heartbeat_status'),
                'poll_status': poll,
                'last_poll_success_at': self.get('last_poll_success_at'),
                'last_poll_error_code': self.get('last_poll_error_code'),
                'last_send_status': last_send['status'] if last_send else None,
                'last_send_error_code': last_send['error_code'] if last_send else None,
                'last_send_at': last_send['attempted_at'] if last_send else None,
                'send_recovery_hint': send_recovery_hint(last_send['status'], last_send['error_code']) if last_send else None,
                'inbox_count': self.db.execute("SELECT count(*) FROM inbox WHERE kind='message'").fetchone()[0],
                'server_time': now, 'keepalive_guaranteed': False}


