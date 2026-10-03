"""Named chats under a verified API client; explicit incoming tag routing."""
import re
import time
import uuid

from wechat_bridge.storage.client_registry import ClientError


class Conversations:
    def __init__(self, db):
        self.db = db
        db.executescript('''
            CREATE TABLE IF NOT EXISTS conversations (
              id TEXT PRIMARY KEY, client_id TEXT NOT NULL, conversation_key TEXT NOT NULL,
              name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL,
              UNIQUE(client_id, conversation_key));
        ''')
        if 'deleted' not in {r['name'] for r in db.execute('PRAGMA table_info(conversations)')}:
            db.execute('ALTER TABLE conversations ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0')
        old_unique=any([r['name'] for r in db.execute('PRAGMA index_info("'+idx['name']+'")')]==['client_id','name']
                       and idx['origin']=='u' for idx in db.execute('PRAGMA index_list(conversations)'))
        if old_unique:
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('''CREATE TABLE conversations_next (
                    id TEXT PRIMARY KEY,client_id TEXT NOT NULL,conversation_key TEXT NOT NULL,
                    name TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created_at REAL NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,UNIQUE(client_id,conversation_key))''')
                db.execute('INSERT INTO conversations_next SELECT id,client_id,conversation_key,name,active,created_at,deleted FROM conversations')
                db.execute('DROP TABLE conversations')
                db.execute('ALTER TABLE conversations_next RENAME TO conversations')
                db.commit()
            except Exception:
                db.rollback();raise
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS active_conversation_name ON conversations(client_id,name) WHERE active=1 AND deleted=0')

    def rows(self, client_id=None, active_only=True):
        where, args = ['c.enabled=1', 's.deleted=0'], []
        if active_only: where.append('s.active=1')
        if client_id is not None:
            where.append('s.client_id=?')
            args.append(client_id)
        return self.db.execute('SELECT s.*,c.name AS caller FROM conversations s JOIN api_clients c '
                               'ON c.id=s.client_id WHERE ' + ' AND '.join(where) +
                               ' ORDER BY s.created_at,s.id', args).fetchall()

    def get(self, client_id, id, require_active=False):
        row = self.db.execute('SELECT s.*,c.name AS caller FROM conversations s JOIN api_clients c '
                              'ON c.id=s.client_id WHERE s.client_id=? AND s.id=? AND s.deleted=0', (client_id, id)).fetchone()
        if not row: raise ClientError('conversation_not_found', 404)
        if require_active and not row['active']: raise ClientError('conversation_closed')
        return row

    def public(self, row):
        count = len(self.rows(row['client_id']))
        tag = row['caller'] if count == 1 and row['active'] else row['caller'] + '-' + row['name']
        return dict(id=row['id'], name=row['name'], active=bool(row['active']),
                    caller=row['caller'], created_at=row['created_at'], display_tag='[' + tag + ']',
                    reply_tag='[' + row['caller'] + '-' + row['name'] + ']')

    def list(self, client_id=None, include_closed=False):
        return [self.public(row) for row in self.rows(client_id, not include_closed)]

    def register(self, client_id, conversation_key, name=None):
        if not isinstance(conversation_key, str) or not re.fullmatch(r'[a-zA-Z0-9_.:\-]{1,128}', conversation_key):
            raise ClientError('invalid_conversation_key', 422)
        if name is not None and not re.fullmatch(r'[a-zA-Z0-9_\-\u4e00-\u9fff]{1,20}', name):
            raise ClientError('invalid_conversation_name', 422)
        # The stable key makes retries and MCP restarts reuse the same chat.
        existing = self.db.execute('SELECT id FROM conversations WHERE client_id=? AND conversation_key=?',
                                   (client_id, conversation_key)).fetchone()
        if existing:
            return self.public(self.get(client_id, existing['id']))
        existing_names = {r['name'] for r in self.rows(client_id)}
        if name is None:
            number = 1
            while str(number) in existing_names: number += 1
            name = str(number)
        name = name.casefold()
        base, number = name, 2
        while name in existing_names:
            suffix = '-' + str(number)
            name, number = base[:20-len(suffix)] + suffix, number + 1
        id = uuid.uuid4().hex
        self.db.execute('INSERT INTO conversations(id,client_id,conversation_key,name,created_at) VALUES (?,?,?,?,?)',
                        (id, client_id, conversation_key, name, time.time()))
        return self.public(self.get(client_id, id))

    def set_active(self, client_id, id, active):
        row=self.get(client_id, id)
        if active and self.db.execute('SELECT 1 FROM conversations WHERE client_id=? AND name=? AND active=1 AND deleted=0 AND id<>?',(client_id,row['name'],id)).fetchone():
            raise ClientError('conversation_name_conflict',409)
        self.db.execute('UPDATE conversations SET active=? WHERE client_id=? AND id=?', (int(active), client_id, id))
        return self.public(self.get(client_id, id))

    def rename(self, client_id, id, name):
        if not re.fullmatch(r'[a-zA-Z0-9_\-\u4e00-\u9fff]{1,20}', name):
            raise ClientError('invalid_conversation_name', 422)
        row = self.get(client_id, id)
        name = name.casefold()
        if row['active'] and self.db.execute(
            'SELECT 1 FROM conversations WHERE client_id=? AND name=? AND active=1 AND deleted=0 AND id<>?',
            (client_id, name, id)).fetchone():
            raise ClientError('conversation_name_conflict', 409)
        self.db.execute('UPDATE conversations SET name=? WHERE id=?', (name, id))
        return self.public(self.get(client_id, id))

    def resolve(self, tag):
        tag = tag.casefold()
        matches = [row for row in self.rows() if tag in (row['caller'].casefold(),
                                                       (row['caller'] + '-' + row['name']).casefold())]
        if len(matches) == 1: return matches[0]['id'], 'direct'
        return None, 'ambiguous' if matches else 'unknown'

    def label(self, client_id, id):
        row = self.get(client_id, id, require_active=True)
        item = self.public(row)
        # Client names can themselves contain hyphens: never emit an ambiguous tag.
        for candidate in (item['display_tag'], item['reply_tag']):
            if self.resolve(candidate[1:-1]) == (id, 'direct'): return candidate
        raise ClientError('conversation_tag_conflict')

    def route(self, text):
        match = re.match(r'^\[([^\]\r\n]{1,80})\]\s*', text.lstrip())
        if not match: return None, 'shared', text, None
        tag = match.group(1)
        id, status = self.resolve(tag)
        body = text.lstrip()[match.end():] if status == 'direct' else text
        return id, status, body, '[' + tag + ']'
