"""Owner browser sessions and encrypted conversation history; no AI wake-up worker."""
import hashlib
import asyncio
import hmac
import json
import secrets
import time

from wechat_bridge.storage.client_registry import ClientError
from wechat_bridge.storage.images import Images

from wechat_bridge.config import SESSION_SECONDS

class Portal:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
            direction TEXT NOT NULL, source TEXT NOT NULL, encrypted BLOB NOT NULL,
            created_at REAL NOT NULL, status TEXT NOT NULL,
            outgoing_key TEXT UNIQUE, inbox_id INTEGER UNIQUE);
          CREATE INDEX IF NOT EXISTS chat_timeline ON chat_messages(conversation_id,id);
          CREATE TABLE IF NOT EXISTS web_sessions (token_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS web_reads (conversation_id TEXT PRIMARY KEY, message_id INTEGER NOT NULL);
        ''')
        self.images=Images(store)
        self.image_slots=asyncio.Semaphore(1)
        # Only recover text that was actually saved. Old outgoing hashes are not transcripts.
        self.db.execute("INSERT OR IGNORE INTO chat_messages(conversation_id,direction,source,encrypted,created_at,status,inbox_id) "
            "SELECT conversation_id,'user','wechat',encrypted,message_at,'legacy',id FROM inbox "
            "WHERE kind='message' AND conversation_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM chat_messages m WHERE m.inbox_id=inbox.id) ORDER BY id")

    def add(self, cid, direction, source, text, status, *, outgoing_key=None, inbox_id=None, at=None, attachments=None):
        encrypted = self.store.cipher.encrypt(json.dumps({'text': text,'attachments':attachments or []}, ensure_ascii=False).encode())
        result = self.db.execute('INSERT INTO chat_messages(conversation_id,direction,source,encrypted,created_at,status,outgoing_key,inbox_id) '
            'VALUES (?,?,?,?,?,?,?,?)', (cid, direction, source, encrypted, at or time.time(), status, outgoing_key, inbox_id))
        return result.lastrowid

    def owner_chat(self, cid, writable=False):
        row = self.db.execute("SELECT s.*,coalesce(c.name,'已删除客户端') AS caller,coalesce(c.enabled,0) AS enabled "
            'FROM conversations s LEFT JOIN api_clients c ON c.id=s.client_id WHERE s.id=? AND s.deleted=0', (cid,)).fetchone()
        if not row: raise ClientError('conversation_not_found', 404)
        if writable and (not row['active'] or not row['enabled']): raise ClientError('conversation_closed', 409)
        return dict(id=row['id'], name=row['name'], caller=row['caller'], active=bool(row['active'] and row['enabled']), archived=not bool(row['active']))

    def chats(self):
        rows = self.db.execute('SELECT s.id, max(m.id) AS latest FROM conversations s LEFT JOIN chat_messages m '
            'ON s.id=m.conversation_id WHERE s.deleted=0 GROUP BY s.id ORDER BY coalesce(max(m.created_at),s.created_at) DESC,s.id').fetchall()
        result = []
        for row in rows:
            item = self.owner_chat(row['id'])
            last = self.db.execute('SELECT * FROM chat_messages WHERE id=?', (row['latest'],)).fetchone()
            read = self.db.execute('SELECT message_id FROM web_reads WHERE conversation_id=?', (row['id'],)).fetchone()
            item.update(last_at=last['created_at'] if last else None,
                        preview=(self.decode(last)['text'][:100] or '[图片]') if last else '还没有消息',
                        unread=self.db.execute("SELECT count(*) FROM chat_messages WHERE conversation_id=? AND direction='assistant' AND id>?",
                                               (row['id'], read[0] if read else 0)).fetchone()[0])
            result.append(item)
        return result

    def delete_chat(self, cid):
        row=self.db.execute('SELECT deleted FROM conversations WHERE id=?',(cid,)).fetchone()
        if not row: raise ClientError('conversation_not_found',404)
        if row['deleted']: return {'deleted':True,'messages_removed':0}
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('UPDATE conversations SET deleted=1,active=0 WHERE id=?',(cid,))
            count=self.db.execute('DELETE FROM chat_messages WHERE conversation_id=?',(cid,)).rowcount
            # Retain only minimal deduplication tombstones, never message bodies.
            empty=self.store.cipher.encrypt(b'{}')
            self.db.execute("UPDATE inbox SET kind='deleted',encrypted=? WHERE conversation_id=?",(empty,cid))
            self.db.execute('DELETE FROM web_reads WHERE conversation_id=?',(cid,))
            self.db.execute('DELETE FROM image_attachments WHERE conversation_id=?',(cid,))
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mcp_event_subscriptions'").fetchone():
                self.db.execute('DELETE FROM mcp_event_subscriptions WHERE conversation=?',(cid,))
            self.db.commit()
        except Exception:
            self.db.rollback();raise
        return {'deleted':True,'messages_removed':count}

    def decode(self, row):
        return dict(id=row['id'], conversation_id=row['conversation_id'], direction=row['direction'],
                    source=row['source'], created_at=row['created_at'], status=row['status'],
                    **json.loads(self.store.cipher.decrypt(row['encrypted'])))

    def history(self, cid, before=0, after=0, around=0, limit=50):
        chat = self.owner_chat(cid)
        where, args = 'conversation_id=?', [cid]
        if around:
            anchor = self.db.execute('SELECT id FROM chat_messages WHERE conversation_id=? AND id=?', (cid, around)).fetchone()
            if not anchor: raise ClientError('message_not_found', 404)
            older = self.db.execute('SELECT id FROM chat_messages WHERE conversation_id=? AND id<=? ORDER BY id DESC LIMIT ?',
                                    (cid, around, max(1, limit//2))).fetchall()
            where += ' AND id>=?'
            args.append(older[-1]['id'])
        elif before:
            where += ' AND id<?'; args.append(before)
        elif after:
            where += ' AND id>?'; args.append(after)
        ascending = bool(after or around)
        rows = self.db.execute('SELECT * FROM chat_messages WHERE ' + where + ' ORDER BY id ' +
                              ('ASC' if ascending else 'DESC') + ' LIMIT ?', (*args, limit)).fetchall()
        if not ascending: rows.reverse()
        first, last = (rows[0]['id'], rows[-1]['id']) if rows else (0, 0)
        return dict(conversation=chat, messages=[self.decode(r) for r in rows],
            has_older=bool(first and self.db.execute('SELECT 1 FROM chat_messages WHERE conversation_id=? AND id<? LIMIT 1', (cid, first)).fetchone()),
            has_newer=bool(last and self.db.execute('SELECT 1 FROM chat_messages WHERE conversation_id=? AND id>? LIMIT 1', (cid, last)).fetchone()))

    def reply(self, cid, text, request_id, attachment_ids=None):
        self.owner_chat(cid, writable=True)
        attachment_ids=attachment_ids or []
        identity = 'web:' + cid + ':' + request_id
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old = self.db.execute('SELECT id,encrypted FROM inbox WHERE identity=?', (identity,)).fetchone()
            if old:
                previous=json.loads(self.store.cipher.decrypt(old['encrypted']))
                if previous['text'] != text or [x['id'] for x in previous.get('attachments',[])]!=attachment_ids:
                    raise ClientError('request_id_content_conflict', 409)
                row = self.db.execute('SELECT * FROM chat_messages WHERE inbox_id=?', (old['id'],)).fetchone()
            else:
                attachments=[]
                for id in attachment_ids:
                    image=self.images.get(cid,id,pending=True)
                    if image['inbox_id'] is not None:raise ClientError('image_already_sent',409)
                    attachments.append(self.images.public(image))
                now = time.time()
                content = self.store.cipher.encrypt(json.dumps({'text': text, 'item_types': ([1] if text else [])+([2] if attachments else []), 'source': 'web','attachments':attachments}).encode())
                cursor = self.db.execute("INSERT INTO inbox(identity,received_at,message_at,encrypted,kind,conversation_id,route_status) VALUES (?,?,?,?,'message',?,'direct')",
                                        (identity, now, now, content, cid))
                for image in attachments:
                    self.db.execute('UPDATE image_attachments SET inbox_id=? WHERE id=?',(cursor.lastrowid,image['id']))
                id = self.add(cid, 'user', 'web', text, 'pending', inbox_id=cursor.lastrowid, at=now,attachments=attachments)
                row = self.db.execute('SELECT * FROM chat_messages WHERE id=?', (id,)).fetchone()
            self.db.commit()
        except Exception:
            self.db.rollback(); raise
        # Web activity is not WeChat activity: never touch context_token or idle heartbeat.
        return dict(message=self.decode(row), duplicate=bool(old))

    def issue_code(self):
        code = ''.join(secrets.choice('0123456789') for _ in range(8))
        self.store.set('web_login', dict(hash=hashlib.sha256(code.encode()).hexdigest(), expires_at=time.time()+600, attempts=0))
        return code

    def login(self, code):
        now = time.time()
        state = self.store.get('web_login', {})
        if state.get('expires_at', 0) < now or state.get('attempts', 6) >= 6:
            raise ClientError('login_code_expired', 401)
        state['attempts'] += 1
        self.store.set('web_login', state)
        if not hmac.compare_digest(state['hash'], hashlib.sha256(code.encode()).hexdigest()):
            raise ClientError('invalid_login_code', 401)
        self.store.set('web_login', {})
        token = secrets.token_urlsafe(32)
        self.db.execute('DELETE FROM web_sessions WHERE expires_at<?', (now,))
        self.db.execute('INSERT INTO web_sessions VALUES (?,?)', (hashlib.sha256(token.encode()).hexdigest(), now+SESSION_SECONDS))
        return token


