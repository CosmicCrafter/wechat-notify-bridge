"""WeChat receive loop, delivery and inactivity heartbeat."""
import asyncio
import base64
import hashlib
import json
import logging
import secrets
import time
import httpx
from wechat_bridge.config import chat_url
from wechat_bridge.wechat.protocol import BridgeError, WeChatError, BASE_INFO, ACCEPTED, validate_base, response_status, send_recovery_hint
from wechat_bridge.services.presentation import present, push_budget_counter
from wechat_bridge.storage.send_diagnostics import wechat_category, redact_error_message

logger = logging.getLogger(__name__)

class Bridge:
    def __init__(self, store, transport=None):
        self.store = store
        self.http = httpx.AsyncClient(timeout=40, follow_redirects=False, transport=transport)
        self.lock = asyncio.Lock()
        self.tasks = []

    async def request(self, endpoint, payload, timeout=20, *, diagnostics=None):
        account = self.store.account()
        if account is None:
            raise BridgeError(409, 'wechat_not_bound')
        headers = {'iLink-App-Id': 'bot', 'iLink-App-ClientVersion': str((2 << 16) | (4 << 8) | 9),
                   'AuthorizationType': 'ilink_bot_token', 'Authorization': 'Bearer ' + account['bot_token'],
                   'X-WECHAT-UIN': base64.b64encode(str(secrets.randbits(32)).encode()).decode()}
        response = await self.http.post(validate_base(account['base_url']) + '/' + endpoint,
                                       json=dict(payload, base_info=BASE_INFO), headers=headers, timeout=timeout)
        if diagnostics is not None:
            diagnostics['http_status'] = response.status_code
        response.raise_for_status()
        value = response.json()
        if diagnostics is not None and isinstance(value, dict):
            for field in ('ret', 'errcode'):
                diagnostics['upstream_' + field] = value[field] if type(value.get(field)) is int else None
            message = value.get('errmsg')
            if not isinstance(message, str):
                message = value.get('msg')
            diagnostics['upstream_error_message'] = redact_error_message(message, account)
        response_status(value)
        return value

    def public_receipt(self, row, duplicate=False):
        message = self.store.db.execute('SELECT id,conversation_id FROM chat_messages WHERE outgoing_key=?', (row['key'],)).fetchone()
        diagnostics = self.store.send_diagnostics.public(row['key'])
        result = {'status': row['status'], 'duplicate': duplicate, 'attempted_at': row['attempted_at'],
                'error_code': row.get('error_code'),
                'recovery_hint': send_recovery_hint(row['status'], row.get('error_code'),
                                                    diagnostics.get('error_category') if diagnostics else None),
                'diagnostics': diagnostics,
                'message_id': message['id'] if message else None,
                'conversation_url': chat_url(message['conversation_id'], message['id']) if message else None,
                'phone_delivery': 'confirmed' if row['status'] == 'phone_confirmed' else 'unconfirmed'}
        task = self.store.db.execute('SELECT * FROM task_cards WHERE outgoing_key=?', (row['key'],)).fetchone()
        if task:
            result['task'] = self.store.portal.tasks.public(task)
        return result

    async def send(self, text, dedup_key, caller, *, kind='message', dry_run=False, expected_due=None,
                   identity=None, command_id=None, conversation_id=None, task_card=None):
        if task_card and (not identity or not conversation_id):
            raise BridgeError(422, 'Task cards require a client identity and conversation')
        if not text.strip() or len(text) > 20000 or not dedup_key.strip() or len(dedup_key) > 200:
            raise BridgeError(422, 'Invalid text or dedup_key')
        if dedup_key.startswith('server-heartbeat-') and caller != 'heartbeat':
            raise BridgeError(422, 'Reserved heartbeat key')
        if dedup_key.startswith('server-command-') and caller != 'command':
            raise BridgeError(422, 'Reserved command key')
        async with self.lock:
            now = time.time()
            if identity:
                identity = self.store.clients.revalidate(identity)
                caller = identity.name
            label = '[' + caller + ']'
            if conversation_id:
                if not identity: raise BridgeError(401, 'client_identity_required')
                label = self.store.conversations.label(identity.id, conversation_id)
            elif identity and len(self.store.conversations.rows(identity.id)) > 1:
                raise BridgeError(409, 'conversation_required')
            # Preserve the caller's original dedup scope for old clients without a chat ID.
            history_cid = conversation_id
            if identity and not history_cid:
                chats = self.store.conversations.rows(identity.id)
                if len(chats) == 1: history_cid = chats[0]['id']
            if command_id is not None:
                reply = self.store.db.execute('SELECT * FROM command_replies WHERE id=?', (command_id,)).fetchone()
                if not reply or reply['status'] != 'pending':
                    return {'status': 'already_processed'}
                if reply['issued_hash']:
                    current = self.store.clients.get(reply['client_id'])
                    if not current['enabled'] or current['key_hash'] != reply['issued_hash']:
                        return {'status': 'superseded'}
            account = self.store.account()
            if not account:
                raise BridgeError(409, 'wechat_not_bound')
            if expected_due is not None and (now < self.store.next_heartbeat() or expected_due != self.store.next_heartbeat()):
                return {'status': 'skipped_new_activity'}
            digest = self.store.digest(dedup_key, identity.id if identity else None, conversation_id)
            fingerprint = json.dumps({'text': text, 'task': task_card}, ensure_ascii=False, sort_keys=True) if task_card else text
            text_hash = hashlib.sha256(fingerprint.encode()).hexdigest()
            previous = self.store.client_receipt(dedup_key, identity, conversation_id) if identity else self.store.receipt(digest)
            if previous:
                if previous['message_hash'] != text_hash:
                    raise BridgeError(409, 'dedup_key already belongs to different content')
                return self.public_receipt(previous, duplicate=True)
            if not account.get('context_token'):
                raise BridgeError(409, 'waiting_for_first_wechat_message')
            context_diagnostics = self.store.send_diagnostics.context(now)
            budget_counter = push_budget_counter(context_diagnostics['accepted_sends_since_context'])
            def render_wire(message_id=None):
                link = chat_url(history_cid, message_id)
                prefix = f'{label}\n\n' if identity else ''
                action = '处理任务卡片' if task_card else '查看对话并回复'
                # Keep the action outside tables: WeChat can style table links without making them tappable.
                # Full-width padding shifts a normal link right; WeChat offers no responsive paragraph alignment.
                counter_width = sum(2 if ord(char) > 127 else 1 for char in budget_counter)
                padding = '\u3000' * max(0, 17 - len(action) - (counter_width + 2) // 2)
                footer = '\n\n---\n\n'
                if link:
                    footer += padding + budget_counter + ' [' + action + ' →](' + link + ')'
                else:
                    footer += budget_counter
                body = present(text, kind, task_card, now + task_card['expires_in'] if task_card else None)
                if len(prefix + body + footer) > 2000:
                    if not history_cid or not link:
                        raise BridgeError(422, 'Long messages require a conversation and public URL')
                    # A plain, escaped excerpt cannot leave an unclosed code fence or link.
                    import re
                    excerpt = re.sub(r'[\\`*_{}\[\]()<>#+!|~]', '', text[:700]).strip()
                    heading = '需要你决定' if task_card else '新消息'
                    body = '## ' + heading + '\n\n' + excerpt + '…\n\n完整内容已保存，点击下方链接查看。'
                return prefix + body + footer
            wire_text = render_wire()
            if dry_run:
                return {'status': 'dry_run_ready', 'sent_now': False, 'network_checked': False}
            diagnostics = {**context_diagnostics,
                           'request_characters': len(wire_text), 'request_utf8_bytes': len(wire_text.encode()),
                           'http_status': None, 'error_category': None}
            diagnostics.pop('quota_warning', None)
            self.store.db.execute('BEGIN IMMEDIATE')
            try:
                self.store.db.execute('INSERT INTO outgoing VALUES (?,?,?,?,?,?,?,?)',
                    (digest, text_hash, 'attempting', kind, caller, now, None, None))
                if history_cid:
                    task_id = self.store.portal.tasks.create(history_cid, digest, task_card, now) if task_card else None
                    message_id = self.store.portal.add(history_cid, 'assistant', 'api', text, 'attempting', outgoing_key=digest, at=now, task_id=task_id)
                    wire_text = render_wire(message_id)
                    diagnostics['request_characters'] = len(wire_text)
                    diagnostics['request_utf8_bytes'] = len(wire_text.encode())
                self.store.send_diagnostics.save(digest, diagnostics)
                if kind == 'heartbeat':
                    self.store.set('last_heartbeat_attempt_at', now)
                self.store.db.commit()
            except Exception:
                self.store.db.rollback()
                raise
            status, error = 'unconfirmed_do_not_retry', None
            started = time.monotonic()
            try:
                account = self.store.account()
                value = await self.request('ilink/bot/sendmessage', {'msg': {
                    'from_user_id': '', 'to_user_id': account['user_id'],
                    'client_id': 'codex-wechat-' + digest[:32], 'message_type': 2, 'message_state': 2,
                    'context_token': account['context_token'], 'item_list': [{'type': 1, 'text_item': {'text': wire_text}}]}},
                    diagnostics=diagnostics)
                status = response_status(value)
            except WeChatError as exc:
                status, error = 'api_rejected', str(exc.code)
                diagnostics['upstream_error_field'] = exc.field
                diagnostics['error_category'] = wechat_category(exc.code, diagnostics.get('upstream_error_message'))
            except httpx.TimeoutException as exc:
                error = type(exc).__name__
                diagnostics['error_category'] = 'network_timeout'
            except httpx.HTTPStatusError as exc:
                error = type(exc).__name__
                diagnostics['error_category'] = 'http_error'
            except httpx.TransportError as exc:
                error = type(exc).__name__
                diagnostics['error_category'] = 'network_error'
            except ValueError as exc:
                error = type(exc).__name__
                diagnostics['error_category'] = 'invalid_response'
            except Exception as exc:
                error = type(exc).__name__
                diagnostics['error_category'] = 'internal_error'
            diagnostics['duration_ms'] = round((time.monotonic() - started) * 1000)
            self.store.db.execute('BEGIN IMMEDIATE')
            try:
                finished = time.time()
                self.store.db.execute('UPDATE outgoing SET status=?,finished_at=?,error_code=? WHERE key=?',
                                      (status, finished, error, digest))
                self.store.db.execute('UPDATE chat_messages SET status=? WHERE outgoing_key=?', (status, digest))
                self.store.send_diagnostics.save(digest, diagnostics)
                if status in ACCEPTED:
                    self.store.touch(finished)
                if kind == 'heartbeat':
                    self.store.set('last_heartbeat_status', status)
                self.store.db.commit()
            except Exception:
                self.store.db.rollback()
                raise
            if status not in ACCEPTED:
                logger.warning('WeChat send failed: key=%s category=%s code=%s http=%s context_age=%s accepted_before=%s',
                               digest, diagnostics.get('error_category'), error, diagnostics.get('http_status'),
                               diagnostics['context_age_seconds'], diagnostics['accepted_sends_since_context'])
            return self.public_receipt(self.store.receipt(digest))

    async def command_once(self):
        account = self.store.account()
        if not account or not account.get('context_token') or self.store.get('poll_status') == 'session_expired':
            return {'status': 'waiting_for_connection'}
        row = self.store.db.execute("SELECT * FROM command_replies WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return {'status': 'idle'}
        text = self.store.cipher.decrypt(row['encrypted_reply']).decode()
        result = await self.send(text, 'server-command-' + str(row['id']), 'command',
                                 kind='command', command_id=row['id'])
        # Do not resend ambiguous deliveries. Purge the temporary encrypted key reply.
        self.store.db.execute('UPDATE command_replies SET status=?,encrypted_reply=NULL WHERE id=?',
                              (result['status'], row['id']))
        return result

    async def command_loop(self):
        while True:
            try:
                await self.command_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.store.set('last_command_error', type(exc).__name__)
            await asyncio.sleep(1)

    async def heartbeat_once(self):
        account = self.store.account()
        if not account or not account.get('context_token'):
            return {'status': 'waiting_for_binding_or_message'}
        due = self.store.next_heartbeat()
        if time.time() < due:
            return {'status': 'not_due'}
        # A server-rejected session cannot be revived by repeatedly sending chat messages.
        if self.store.get('poll_status') == 'session_expired':
            return {'status': 'session_expired'}
        return await self.send('## 微信通知桥 · 空闲心跳\n\n服务仍在运行。\n\n> 已连续 12 小时没有有效微信收发；正常沟通时不会发送心跳。',
                               'server-heartbeat-' + str(int(due * 1000)), 'heartbeat',
                               kind='heartbeat', expected_due=due)

    async def poll_loop(self):
        failures = 0
        while True:
            try:
                account = self.store.account()
                result = await self.request('ilink/bot/getupdates',
                    {'get_updates_buf': account.get('get_updates_buf', '')}, timeout=45)
                async with self.lock:
                    self.store.ingest(result, time.time())
                failures = 0
                await asyncio.sleep(0.3)
            except httpx.ReadTimeout:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except WeChatError as exc:
                self.store.set('last_poll_error_code', exc.code)
                self.store.set('poll_status', 'session_expired' if exc.code == -14 else 'retrying')
                failures += 1
                await asyncio.sleep(3600 if exc.code == -14 else min(60, 2 ** min(failures, 6)))
            except Exception as exc:
                self.store.set('last_poll_error_code', type(exc).__name__)
                self.store.set('poll_status', 'retrying')
                failures += 1
                await asyncio.sleep(min(60, 2 ** min(failures, 6)))

    async def heartbeat_loop(self):
        while True:
            try:
                await self.heartbeat_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.store.set('last_heartbeat_status', type(exc).__name__)
            await asyncio.sleep(15)

    async def start(self):
        if self.tasks or not self.store.account():
            return
        try:
            await self.request('ilink/bot/msg/notifystart', {}, timeout=10)
        except Exception:
            self.store.set('poll_status', 'start_notice_unconfirmed')
        self.tasks = [asyncio.create_task(self.poll_loop()), asyncio.create_task(self.heartbeat_loop()),
                      asyncio.create_task(self.command_loop())]

    async def stop_workers(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.tasks:
            try:
                await self.request('ilink/bot/msg/notifystop', {}, timeout=5)
            except Exception:
                pass
        self.tasks = []

    async def bind_account(self, account, run_workers=True):
        async with self.lock:
            current = self.store.account()
            if current and current['user_id'] != account['user_id']:
                raise BridgeError(409, 'owner_mismatch')
            await self.stop_workers()
            try:
                self.store.bind(account)
            finally:
                if run_workers:
                    await self.start()

    async def close(self):
        await self.stop_workers()
        await self.http.aclose()
