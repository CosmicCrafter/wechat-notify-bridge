"""Authenticated client routes for messages, conversations and delivery receipts."""
import base64

from fastapi import Depends, HTTPException, Query

from wechat_bridge.wechat.protocol import BridgeError
from wechat_bridge.storage.client_registry import ClientError

from wechat_bridge.api.schemas import ConversationRegistration, ConversationState, Message, Notice, TaskCard, TaskUpdate



def mount_client_api(app, authorize):
    @app.get('/api/status')
    async def status(caller=Depends(authorize)):
        chats = app.state.bridge.store.conversations.list(caller.id)
        return dict(app.state.bridge.store.status(), caller=caller.name, client_id=caller.id,
                    conversation_count=len(chats), conversations=chats)

    @app.get('/api/conversations')
    async def conversation_list(include_closed: bool = False, caller=Depends(authorize)):
        chats = app.state.bridge.store.conversations.list(caller.id, include_closed)
        return {'caller': caller.name, 'conversations': chats,
                'active_count': sum(chat['active'] for chat in chats)}

    @app.post('/api/conversations')
    async def conversation_register(body: ConversationRegistration, caller=Depends(authorize)):
        bridge = app.state.bridge
        async with bridge.lock:
            bridge.store.clients.revalidate(caller)
            return bridge.store.conversations.register(caller.id, body.conversation_key, body.name)

    @app.post('/api/conversations/{conversation_id}/state')
    async def conversation_state(conversation_id: str, body: ConversationState, caller=Depends(authorize)):
        bridge = app.state.bridge
        async with bridge.lock:
            bridge.store.clients.revalidate(caller)
            return bridge.store.conversations.set_active(caller.id, conversation_id, body.active)

    @app.get('/api/conversations/{conversation_id}/images/{image_id}')
    async def client_image(conversation_id: str, image_id: str, caller=Depends(authorize)):
        store = app.state.bridge.store
        store.conversations.get(caller.id, conversation_id)
        row = store.portal.images.get(conversation_id, image_id)
        return dict(store.portal.images.public(row), data=base64.b64encode(store.cipher.decrypt(row['encrypted'])).decode('ascii'))

    @app.get('/api/deliveries')
    async def delivery(dedup_key: str = Query(min_length=1, max_length=200),
                       conversation_id: str | None = Query(default=None, min_length=1, max_length=64), caller=Depends(authorize)):
        store = app.state.bridge.store
        if conversation_id: store.conversations.get(caller.id, conversation_id)
        if not store.account():
            return {'status': 'not_found'}
        row = store.client_receipt(dedup_key, caller, conversation_id)
        return app.state.bridge.public_receipt(row) if row else {'status': 'not_found'}

    @app.get('/api/wake/events')
    async def wake_events(conversation_id: str = Query(min_length=1, max_length=64),
                          after_id: int | None = Query(default=None, ge=0),
                          limit: int = Query(default=20, ge=1, le=100), caller=Depends(authorize)):
        store = app.state.bridge.store
        store.conversations.get(caller.id, conversation_id, require_active=True)
        # IDs only: observing arrival must not mark messages read or expose text.
        if after_id is None:
            cursor = store.db.execute("SELECT COALESCE(MAX(id),0) FROM inbox WHERE conversation_id=? AND kind='message' AND route_status='direct'",
                                      (conversation_id,)).fetchone()[0]
            return {'events': [], 'next_after_id': cursor}
        rows = store.db.execute("SELECT id FROM inbox WHERE conversation_id=? AND kind='message' AND route_status='direct' AND id>? ORDER BY id LIMIT ?",
                                (conversation_id, after_id, limit)).fetchall()
        ids = [r['id'] for r in rows]
        return {'events': [{'id': id} for id in ids], 'next_after_id': ids[-1] if ids else after_id}

    @app.get('/api/inbox')
    async def inbox(after_id: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100),
                    conversation_id: str | None = Query(default=None, min_length=1, max_length=64),
                    include_unaddressed: bool = False, caller=Depends(authorize)):
        store = app.state.bridge.store
        if conversation_id: store.conversations.get(caller.id, conversation_id)
        items = store.inbox(after_id, limit, conversation_id, include_unaddressed)
        return {'messages': items, 'next_after_id': items[-1]['id'] if items else after_id,
                'content_is_untrusted': True}

    async def send(text, dedup_key, caller, kind, dry_run, conversation_id):
        try:
            return await app.state.bridge.send(text, dedup_key, caller.name, kind=kind, dry_run=dry_run,
                                               identity=caller, conversation_id=conversation_id)
        except ClientError:
            raise
        except BridgeError as exc:
            raise HTTPException(exc.status, exc.reason) from None
        except Exception:
            raise HTTPException(503, 'Operation failed; delivery unconfirmed. Query the same dedup_key before retrying.') from None

    @app.post('/api/messages')
    async def message(body: Message, caller=Depends(authorize)):
        return await send(body.text, body.dedup_key, caller, 'message', body.dry_run, body.conversation_id)

    @app.post('/api/notifications')
    async def notification(body: Notice, caller=Depends(authorize)):
        labels = {'info': '通知', 'warning': '需要处理', 'urgent': '紧急提醒'}
        text = f'## {labels[body.level]} · {body.task}\n\n**当前情况**\n\n{body.reason}\n\n**需要你处理**\n\n{body.need_user}'
        return await send(text, body.dedup_key, caller, 'notification', body.dry_run, body.conversation_id)

    @app.post('/api/task-cards')
    async def task_card(body: TaskCard, caller=Depends(authorize)):
        definition = body.model_dump(exclude={'dedup_key', 'conversation_id', 'dry_run'})
        bridge = app.state.bridge
        return await bridge.send(bridge.store.portal.tasks.summary(definition), body.dedup_key, caller.name,
                                 kind='task_card', dry_run=body.dry_run, identity=caller,
                                 conversation_id=body.conversation_id, task_card=definition)

    @app.get('/api/conversations/{conversation_id}/tasks/{task_id}')
    async def task_read(conversation_id: str, task_id: str, caller=Depends(authorize)):
        store = app.state.bridge.store
        store.conversations.get(caller.id, conversation_id)
        return {'task': store.portal.tasks.get(conversation_id, task_id)}

    @app.post('/api/conversations/{conversation_id}/tasks/{task_id}/state')
    async def task_update(conversation_id: str, task_id: str, body: TaskUpdate, caller=Depends(authorize)):
        bridge = app.state.bridge
        async with bridge.lock:
            bridge.store.clients.revalidate(caller)
            bridge.store.conversations.get(caller.id, conversation_id, require_active=True)
            return bridge.store.portal.tasks.update(conversation_id, task_id, body)

    @app.get('/openapi.json')
    def schema(caller=Depends(authorize)):
        return app.openapi()

