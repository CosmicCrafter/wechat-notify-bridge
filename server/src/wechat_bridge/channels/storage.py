"""Optional channel settings and journals, isolated from WeChat quotas/timers."""
import hashlib
import json


class ChannelState:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS channel_settings (channel TEXT PRIMARY KEY, encrypted BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS channel_outgoing (
            key TEXT PRIMARY KEY, channel TEXT NOT NULL, conversation_id TEXT,
            message_hash TEXT NOT NULL, status TEXT NOT NULL, attempted_at REAL NOT NULL,
            finished_at REAL, error_code TEXT, provider_hash TEXT, encrypted BLOB);
          CREATE INDEX IF NOT EXISTS channel_outgoing_provider ON channel_outgoing(channel,provider_hash);
          CREATE INDEX IF NOT EXISTS channel_outgoing_conversation ON channel_outgoing(conversation_id);
          CREATE TABLE IF NOT EXISTS channel_commands (
            id TEXT PRIMARY KEY, channel TEXT NOT NULL, created_at REAL NOT NULL,
            encrypted BLOB, status TEXT NOT NULL DEFAULT 'pending');
        ''')

    def encrypt(self, value):
        return self.store.cipher.encrypt(json.dumps(value, ensure_ascii=False).encode())

    def decrypt(self, value):
        return json.loads(self.store.cipher.decrypt(value)) if value else {}

    def settings(self, channel):
        row = self.db.execute('SELECT encrypted FROM channel_settings WHERE channel=?', (channel,)).fetchone()
        return self.decrypt(row[0]) if row else {}

    def save_settings(self, channel, value):
        self.db.execute('INSERT OR REPLACE INTO channel_settings VALUES (?,?)', (channel, self.encrypt(value)))

    @staticmethod
    def digest(channel, owner, key, client_id=None, cid=None):
        # Structured fields avoid delimiter collisions; no dependency on a WeChat binding.
        return hashlib.sha256(json.dumps([channel, owner, client_id, cid, key], ensure_ascii=False).encode()).hexdigest()

    def receipt(self, key):
        row = self.db.execute('SELECT * FROM channel_outgoing WHERE key=?', (key,)).fetchone()
        return dict(row) if row else None

    def parent(self, channel, message_id):
        return self.db.execute('SELECT * FROM channel_outgoing WHERE channel=? AND provider_hash=?',
                               (channel, hashlib.sha256(message_id.encode()).hexdigest())).fetchone()
