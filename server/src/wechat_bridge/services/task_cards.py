"""Encrypted decision cards; one transactional answer routed through the existing inbox."""
import json
import time
import uuid
import re
from datetime import date
from decimal import Decimal

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
          CREATE INDEX IF NOT EXISTS task_cards_pending ON task_cards(status,expires_at);
        ''')

    def encrypt(self, value):
        return self.store.cipher.encrypt(json.dumps(value, ensure_ascii=False, sort_keys=True).encode())

    def decrypt(self, value):
        return json.loads(self.store.cipher.decrypt(value)) if value else None

    @staticmethod
    def summary(definition):
        mode = definition.get('mode', 'single')
        heading = '需要你补充' if mode in ('input', 'form') else '需要你决定'
        text = f"## {heading} · {definition['title']}\n\n{definition['prompt']}\n\n"
        for option in definition['options']:
            text += f"- **{option['label']}**" + (' · 推荐' if option['recommended'] else '')
            if option['description']:
                text += '：' + option['description']
            text += '\n'
        if mode == 'form':
            for field in definition['fields']:
                text += '- **' + field['label'] + '**' + (' · 必填' if field['required'] else ' · 选填') + '\n'
        if mode == 'multiple':
            text += f"\n可选 {definition['min_choices']}–{definition['max_choices']} 项。\n"
        if definition['allow_custom'] and mode != 'input':
            text += '\n也可以输入自己的安排。\n'
        action = {'input': '填写后提交回复', 'form': '填写后提交回复', 'confirm': '点击对应按钮提交决定'}.get(mode, '选择后提交决定')
        return text + '\n点击下方链接，' + action + '。'

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
                    mode=definition.get('mode', 'single'),
                    min_choices=definition.get('min_choices', 1), max_choices=definition.get('max_choices', 1),
                    input_hint=definition.get('input_hint', ''),
                    fields=definition.get('fields', []),
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
            answer = self.validate_answer(definition, body)
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
                selected = answer.get('choice_labels') or ([answer['choice_label']] if answer['choice_label'] else [])
                if selected:
                    text += '选择：' + '、'.join(selected) + '\n'
                if body.text.strip():
                    text += '回复：' + body.text
                for field in answer.get('fields', []):
                    text += field['label'] + '：' + (field['value'] or '未填写') + '\n'
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

    @staticmethod
    def validate_answer(definition, body):
        mode = definition.get('mode', 'single')
        answer = dict(choice_id=None, choice_label=None, text=body.text)
        if mode == 'form':
            if body.choice_id is not None or body.choice_ids or body.text or any(key not in {f['id'] for f in definition['fields']} for key in body.field_values):
                raise ClientError('invalid_task_fields', 422)
            values, fields = {}, []
            for field in definition['fields']:
                value = body.field_values.get(field['id'], '')
                if field['required'] and not value.strip():
                    raise ClientError('task_field_required', 422)
                if value.strip():
                    if field['type'] == 'select':
                        option = next((o for o in field['options'] if o['id'] == value), None)
                        if option is None:
                            raise ClientError('invalid_task_fields', 422)
                    elif field['type'] == 'number':
                        if not re.fullmatch(r'-?\d{1,12}(?:\.\d{1,6})?', value.strip()):
                            raise ClientError('invalid_task_fields', 422)
                        value = format(Decimal(value.strip()).normalize(), 'f')
                        if value == '-0': value = '0'
                    elif field['type'] == 'date':
                        try:
                            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) or date.fromisoformat(value).year < 1:
                                raise ValueError()
                        except ValueError:
                            raise ClientError('invalid_task_fields', 422) from None
                else:
                    value = ''
                values[field['id']] = value
                label = option['label'] if field['type'] == 'select' and value else value
                fields.append(dict(id=field['id'], label=field['label'], type=field['type'], value=label))
            return dict(**answer, field_values=values, fields=fields)
        if body.field_values:
            raise ClientError('invalid_task_fields', 422)
        if mode == 'multiple':
            ids = body.choice_ids or []
            options = {option['id']: option for option in definition['options']}
            if body.choice_id is not None or len(set(ids)) != len(ids) or any(id not in options for id in ids):
                raise ClientError('invalid_task_choice', 422)
            if ids:
                if not definition['min_choices'] <= len(ids) <= definition['max_choices']:
                    raise ClientError('task_choice_limit', 422)
                if body.text and not definition['allow_custom']:
                    raise ClientError('invalid_task_choice', 422)
            elif not definition['allow_custom'] or not body.text.strip():
                raise ClientError('task_answer_required', 422)
            # Canonical order makes retrying the same set idempotent on another device.
            selected = [option for option in definition['options'] if option['id'] in ids]
            answer.update(choice_ids=[item['id'] for item in selected], choice_labels=[item['label'] for item in selected])
        else:
            if body.choice_ids:
                raise ClientError('invalid_task_choice', 422)
            option = next((item for item in definition['options'] if item['id'] == body.choice_id), None)
            if body.choice_id is not None and (option is None or mode == 'input'):
                raise ClientError('invalid_task_choice', 422)
            if body.choice_id is None and (not definition['allow_custom'] or not body.text.strip()):
                raise ClientError('task_answer_required', 422)
            answer.update(choice_id=body.choice_id, choice_label=option['label'] if option else None)
        return answer

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
