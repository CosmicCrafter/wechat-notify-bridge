"""Encrypted decision cards; one transactional answer routed through the existing inbox."""
import json
import time
import uuid

from wechat_bridge.storage.client_registry import ClientError


class TaskCards:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS task_cards (
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
            outgoing_key TEXT NOT NULL UNIQUE, encrypted BLOB NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL,
            expires_at REAL NOT NULL, answered_at REAL, updated_at REAL NOT NULL,
            answer BLOB, result BLOB, inbox_id INTEGER UNIQUE);
          CREATE INDEX IF NOT EXISTS task_cards_conversation ON task_cards(conversation_id);
        ''')

    def encrypt(self, value):
        return self.store.cipher.encrypt(json.dumps(value, ensure_ascii=False, sort_keys=True).encode())

    def decrypt(self, value):
        return json.loads(self.store.cipher.decrypt(value)) if value else None

    @staticmethod
    def summary(definition):
        text = f"## 需要你决定 · {definition['title']}\n\n{definition['prompt']}\n\n"
        for option in definition['options']:
            text += f"- **{option['label']}**" + (' · 推荐' if option['recommended'] else '')
            if option['description']:
                text += '：' + option['description']
            text += '\n'
        if definition['allow_custom']:
            text += '\n也可以输入自己的安排。\n'
        return text + '\n点击下方链接，选择后提交决定。'

    def create(self, cid, outgoing_key, definition, now):
        # Called inside Bridge.send's outgoing/history transaction.
        id = uuid.uuid4().hex
        self.db.execute('INSERT INTO task_cards(id,conversation_id,outgoing_key,encrypted,created_at,expires_at,updated_at) '
                        'VALUES (?,?,?,?,?,?,?)',
                        (id, cid, outgoing_key, self.encrypt(definition), now, now + definition['expires_in'], now))
        return id

    def row(self, cid, id):
        row = self.db.execute('SELECT * FROM task_cards WHERE id=? AND conversation_id=?', (id, cid)).fetchone()
        if not row:
            raise ClientError('task_not_found', 404)
        return row

    def public(self, row):
        chat = self.store.portal.owner_chat(row['conversation_id'])
        definition = self.decrypt(row['encrypted'])
        status = row['status']
        if status == 'pending' and row['expires_at'] <= time.time():
            status = 'expired'
        return dict(id=row['id'], conversation_id=row['conversation_id'], status=status,
                    title=definition['title'], prompt=definition['prompt'], options=definition['options'],
                    allow_custom=definition['allow_custom'], created_at=row['created_at'],
                    expires_at=row['expires_at'], answered_at=row['answered_at'], updated_at=row['updated_at'],
                    answer=self.decrypt(row['answer']), result=self.decrypt(row['result']) or '',
                    can_answer=chat['active'] and status == 'pending')

    def get(self, cid, id):
        return self.public(self.row(cid, id))

    def answer(self, cid, id, body):
        self.store.portal.owner_chat(cid, writable=True)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.row(cid, id)
            definition = self.decrypt(row['encrypted'])
            option = next((item for item in definition['options'] if item['id'] == body.choice_id), None)
            if body.choice_id is not None and option is None:
                raise ClientError('invalid_task_choice', 422)
            if body.choice_id is None and (not definition['allow_custom'] or not body.text.strip()):
                raise ClientError('task_answer_required', 422)
            answer = dict(choice_id=body.choice_id, choice_label=option['label'] if option else None, text=body.text)
            previous = self.decrypt(row['answer'])
            if previous:
                if previous != answer:
                    raise ClientError('task_already_answered', 409)
                message = self.db.execute('SELECT * FROM chat_messages WHERE inbox_id=?', (row['inbox_id'],)).fetchone()
                duplicate = True
            else:
                if row['status'] != 'pending':
                    raise ClientError('task_not_pending', 409)
                if row['expires_at'] <= time.time():
                    raise ClientError('task_expired', 409)
                now = time.time()
                text = f"【任务答复】{definition['title']}\n"
                if option:
                    text += '选择：' + option['label'] + '\n'
                if body.text.strip():
                    text += '回复：' + body.text
                task_response = dict(task_id=id, title=definition['title'], **answer)
                content = dict(text=text.strip(), item_types=[1], source='web', attachments=[], task_response=task_response)
                cursor = self.db.execute("INSERT INTO inbox(identity,received_at,message_at,encrypted,kind,conversation_id,route_status) "
                                         "VALUES (?,?,?,?,'message',?,'direct')",
                                         ('task:' + cid + ':' + id, now, now, self.encrypt(content), cid))
                message_id = self.store.portal.add(cid, 'user', 'web', content['text'], 'pending', inbox_id=cursor.lastrowid, at=now)
                self.db.execute("UPDATE task_cards SET status='answered',answer=?,answered_at=?,updated_at=?,inbox_id=? WHERE id=?",
                                (self.encrypt(answer), now, now, cursor.lastrowid, id))
                message = self.db.execute('SELECT * FROM chat_messages WHERE id=?', (message_id,)).fetchone()
                duplicate = False
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        # Intentionally leaves the WeChat context and inactivity deadline untouched.
        return dict(task=self.get(cid, id), message=self.store.portal.decode(message), duplicate=duplicate)

    def update(self, cid, id, body):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.row(cid, id)
            if row['status'] == 'pending' and row['expires_at'] <= time.time():
                raise ClientError('task_state_conflict', 409)
            old_result = self.decrypt(row['result']) or ''
            if row['status'] == body.status:
                if old_result != body.result:
                    raise ClientError('task_state_conflict', 409)
                duplicate = True
            else:
                allowed = {'pending': {'cancelled'}, 'answered': {'processing', 'completed', 'cancelled'},
                           'processing': {'completed', 'cancelled'}}
                if body.status not in allowed.get(row['status'], set()):
                    raise ClientError('task_state_conflict', 409)
                self.db.execute('UPDATE task_cards SET status=?,result=?,updated_at=? WHERE id=?',
                                (body.status, self.encrypt(body.result), time.time(), id))
                duplicate = False
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return dict(task=self.get(cid, id), duplicate=duplicate)
