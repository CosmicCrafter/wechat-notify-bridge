"""Persistent API identities. Original keys are returned only when issued."""
from dataclasses import dataclass
import hashlib
import hmac
import re
import secrets
import time
import uuid


class ClientError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class Identity:
    id: str
    name: str
    key_hash: str
    legacy_name: str | None = None


def client_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_\-\u4e00-\u9fff]{1,32}', value):
        raise ClientError('invalid_client_name', 422)
    value = value.casefold()
    if value in ('admin', 'heartbeat', 'command', 'system', '系统', '微信通知桥'):
        raise ClientError('reserved_client_name', 422)
    return value


class ClientRegistry:
    def __init__(self, db):
        self.db = db
        db.executescript('''
            CREATE TABLE IF NOT EXISTS api_clients (
              id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, key_hash TEXT UNIQUE NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL,
              rotated_at REAL, revoked_at REAL, last_seen_at REAL, legacy_name TEXT);
            CREATE TABLE IF NOT EXISTS client_seed (name TEXT PRIMARY KEY);
        ''')

    def seed(self, clients):
        """Import each legacy file entry once; revoked/renamed keys never resurrect."""
        self.db.execute('BEGIN IMMEDIATE')
        try:
            for name, digest in clients.items():
                if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
                    raise ValueError('Invalid client hash configuration')
                if self.db.execute('SELECT 1 FROM client_seed WHERE name=?', (name,)).fetchone():
                    continue
                self.db.execute('INSERT OR IGNORE INTO api_clients(id,name,key_hash,created_at,legacy_name) VALUES (?,?,?,?,?)',
                                (uuid.uuid4().hex, name, digest, time.time(), name))
                self.db.execute('INSERT INTO client_seed VALUES (?)', (name,))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    @staticmethod
    def public(row):
        return {k: row[k] for k in ('id', 'name', 'enabled', 'created_at', 'rotated_at', 'revoked_at', 'last_seen_at')}

    def list(self):
        return [self.public(row) for row in self.db.execute('SELECT * FROM api_clients ORDER BY name')]

    def get(self, id):
        row = self.db.execute('SELECT * FROM api_clients WHERE id=?', (id,)).fetchone()
        if not row:
            raise ClientError('client_not_found', 404)
        return row

    def by_name(self, name):
        row = self.db.execute('SELECT * FROM api_clients WHERE name=?', (client_name(name),)).fetchone()
        if not row:
            raise ClientError('client_not_found', 404)
        return row

    @staticmethod
    def new_key():
        # 40 decimal digits, ~133 bits of randomness. Always treated as a string.
        key = secrets.choice('123456789') + ''.join(secrets.choice('0123456789') for _ in range(39))
        return key, hashlib.sha256(key.encode()).hexdigest()

    def create(self, name):
        name = client_name(name)
        if self.db.execute('SELECT 1 FROM api_clients WHERE name=?', (name,)).fetchone():
            raise ClientError('client_exists')
        key, digest = self.new_key()
        id = uuid.uuid4().hex
        self.db.execute('INSERT INTO api_clients(id,name,key_hash,created_at) VALUES (?,?,?,?)',
                        (id, name, digest, time.time()))
        return self.public(self.get(id)), key

    def rotate(self, id):
        self.get(id)
        key, digest = self.new_key()
        self.db.execute('UPDATE api_clients SET key_hash=?,enabled=1,rotated_at=?,revoked_at=NULL WHERE id=?',
                        (digest, time.time(), id))
        return self.public(self.get(id)), key

    def revoke(self, id):
        self.get(id)
        self.db.execute('UPDATE api_clients SET enabled=0,revoked_at=COALESCE(revoked_at,?) WHERE id=?',
                        (time.time(), id))
        return self.public(self.get(id))

    def delete(self, id):
        """Remove the credential, retaining messages and the legacy import ledger."""
        self.db.execute('BEGIN IMMEDIATE')
        try:
            client = self.public(self.get(id))
            # A queued /getkey reply must not disclose an already deleted key.
            self.db.execute("UPDATE command_replies SET status='deleted',encrypted_reply=NULL,issued_hash=NULL "
                            "WHERE client_id=? AND status='pending'", (id,))
            self.db.execute('DELETE FROM api_clients WHERE id=?', (id,))
            self.db.execute('UPDATE conversations SET active=0 WHERE client_id=?', (id,))
            self.db.commit()
            return client
        except Exception:
            self.db.rollback()
            raise

    def rename(self, id, name):
        row = self.get(id)
        name = client_name(name)
        if row['name'] != name and self.db.execute('SELECT 1 FROM api_clients WHERE name=?', (name,)).fetchone():
            raise ClientError('client_exists')
        self.db.execute('UPDATE api_clients SET name=? WHERE id=?', (name, id))
        return self.public(self.get(id))

    def authenticate(self, key):
        digest = hashlib.sha256(key.encode()).hexdigest()
        row = self.db.execute('SELECT * FROM api_clients WHERE key_hash=? AND enabled=1', (digest,)).fetchone()
        if not row:
            raise ClientError('invalid_client_key', 401)
        self.db.execute('UPDATE api_clients SET last_seen_at=? WHERE id=?', (time.time(), row['id']))
        return Identity(row['id'], row['name'], row['key_hash'], row['legacy_name'])

    def revalidate(self, identity):
        row = self.db.execute('SELECT * FROM api_clients WHERE id=?', (identity.id,)).fetchone()
        if not row or not row['enabled'] or not hmac.compare_digest(row['key_hash'], identity.key_hash):
            raise ClientError('invalid_client_key', 401)
        return Identity(row['id'], row['name'], row['key_hash'], row['legacy_name'])
