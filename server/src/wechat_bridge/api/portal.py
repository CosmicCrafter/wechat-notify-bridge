"""Owner browser sessions and encrypted conversation history; no AI wake-up worker."""
import hashlib
import asyncio
import time
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from wechat_bridge.storage.images import normalize, MAX_UPLOAD

from wechat_bridge.config import COOKIE, SESSION_SECONDS, public_base, chat_url, WEB
from wechat_bridge.api.schemas import TaskAnswer

class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(pattern=r'^\d{8}$')


class WebReply(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(default='', max_length=20000)
    attachment_ids: list[str] = Field(default_factory=list,max_length=3)
    request_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{16,80}$')

    @field_validator('attachment_ids')
    @classmethod
    def distinct(cls, value):
        if len(set(value))!=len(value) or any(len(x)!=32 or any(c not in '0123456789abcdef' for c in x) for x in value):raise ValueError('Invalid attachment IDs')
        return value


class ReadPosition(BaseModel):
    message_id: int = Field(ge=0)


class ArchiveChat(BaseModel):
    model_config = ConfigDict(extra='forbid')
    archived: bool


class RenameChat(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(pattern=r'^[a-zA-Z0-9_\-\u4e00-\u9fff]{1,20}$')


class PinChat(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pinned: bool


def mount_portal(app, authorize_admin):
    def portal(): return app.state.bridge.store.portal

    def same_origin(request: Request):
        base = public_base() or str(request.base_url)
        p = urlsplit(base)
        expected = p.scheme + '://' + p.netloc
        if request.headers.get('Origin') != expected or request.headers.get('X-Chat-Request') != '1':
            raise HTTPException(403, 'same_origin_required')

    async def owner(request: Request):
        token = request.cookies.get(COOKIE, '')
        row = portal().db.execute('SELECT expires_at FROM web_sessions WHERE token_hash=?',
                                 (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row or row[0] <= time.time(): raise HTTPException(401, 'login_required')

    def cookie_path(): return urlsplit(public_base()).path.rstrip('/') + '/chat/'

    @app.get('/chat/', include_in_schema=False)
    def page(): return FileResponse(WEB / 'chat' / 'index.html')

    @app.get('/chat/assets/{filename}', include_in_schema=False)
    def asset(filename: str):
        if filename not in ('app.js', 'style.css', 'experience.css', 'tasks.js', 'tasks.css', 'forms.css', 'field-pickers.js', 'field-pickers.css', 'drafts.js', 'marked.js', 'purify.js'):
            raise HTTPException(404)
        return FileResponse(WEB / ('vendor' if filename in ('marked.js', 'purify.js') else 'chat') / filename, media_type='text/css' if filename.endswith('.css') else 'text/javascript')

    @app.post('/chat/api/login', dependencies=[Depends(same_origin)], include_in_schema=False)
    async def login(body: Login, response: Response):
        async with app.state.bridge.lock:
            token = portal().login(body.code)
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, path=cookie_path(),
                            httponly=True, secure=not public_base().startswith('http://'), samesite='strict')
        return {'authenticated': True}

    @app.post('/chat/api/logout', dependencies=[Depends(same_origin)], include_in_schema=False)
    async def logout(request: Request, response: Response):
        portal().db.execute('DELETE FROM web_sessions WHERE token_hash=?',
                            (hashlib.sha256(request.cookies.get(COOKIE, '').encode()).hexdigest(),))
        response.delete_cookie(COOKIE, path=cookie_path())
        return {'authenticated': False}

    @app.get('/chat/api/conversations', dependencies=[Depends(owner)], include_in_schema=False)
    async def chats():
        store = portal().store
        account = store.account() or {}
        scope = store.digest('browser-drafts') if account else 'unbound'
        return {'conversations': portal().chats(), 'draft_scope': scope}

    @app.get('/chat/api/tasks', dependencies=[Depends(owner)], include_in_schema=False)
    async def pending_tasks(before: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=50), q: str = Query('', max_length=80)):
        return portal().pending_tasks(before, limit, q.strip())

    @app.post('/chat/api/conversations/{cid}/pin', dependencies=[Depends(owner), Depends(same_origin)], include_in_schema=False)
    async def pin(cid: str, body: PinChat):
        async with app.state.bridge.lock:
            return portal().pin(cid, body.pinned)

    @app.post('/chat/api/conversations/{cid}/rename', dependencies=[Depends(owner), Depends(same_origin)], include_in_schema=False)
    async def rename(cid: str, body: RenameChat):
        async with app.state.bridge.lock:
            portal().owner_chat(cid)
            row = portal().db.execute('SELECT client_id FROM conversations WHERE id=?', (cid,)).fetchone()
            return {'conversation': portal().store.conversations.rename(row['client_id'], cid, body.name)}

    @app.get('/chat/api/conversations/{cid}/messages', dependencies=[Depends(owner)], include_in_schema=False)
    async def messages(cid: str, before: int = Query(0, ge=0), after: int = Query(0, ge=0),
                 around: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        if sum(bool(x) for x in (before, after, around)) > 1: raise HTTPException(422, 'one_cursor_only')
        return portal().history(cid, before, after, around, limit)

    @app.post('/chat/api/conversations/{cid}/messages', dependencies=[Depends(owner), Depends(same_origin)], include_in_schema=False)
    async def reply(cid: str, body: WebReply):
        if not body.text.strip() and not body.attachment_ids:raise HTTPException(422,'empty_message')
        async with app.state.bridge.lock:
            return portal().reply(cid, body.text, body.request_id,body.attachment_ids)

    @app.get('/chat/api/conversations/{cid}/tasks', dependencies=[Depends(owner)], include_in_schema=False)
    async def tasks(cid: str, ids: str = Query(min_length=32, max_length=3299)):
        portal().owner_chat(cid)
        values = ids.split(',')
        if len(values) > 100 or any(len(value) != 32 or any(c not in '0123456789abcdef' for c in value) for value in values):
            raise HTTPException(422, 'invalid_task_ids')
        return {'tasks': [portal().tasks.get(cid, id) for id in dict.fromkeys(values)]}

    @app.post('/chat/api/conversations/{cid}/tasks/{task_id}/answer', dependencies=[Depends(owner), Depends(same_origin)], include_in_schema=False)
    async def task_answer(cid: str, task_id: str, body: TaskAnswer):
        async with app.state.bridge.lock:
            return portal().tasks.answer(cid, task_id, body)

    @app.post('/chat/api/conversations/{cid}/images', dependencies=[Depends(owner), Depends(same_origin)], include_in_schema=False)
    async def upload_image(cid: str, request: Request):
        portal().owner_chat(cid,writable=True)
        async with portal().image_slots:
            raw=bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw)>MAX_UPLOAD:raise HTTPException(413,'image_too_large')
            normalized=await asyncio.to_thread(normalize,bytes(raw))
            async with app.state.bridge.lock:
                return portal().images.save(cid,normalized)

    @app.get('/chat/api/conversations/{cid}/images/{image_id}', dependencies=[Depends(owner)], include_in_schema=False)
    async def owner_image(cid: str,image_id: str):
        image=portal().images.get(cid,image_id)
        return Response(portal().store.cipher.decrypt(image['encrypted']),media_type=image['mime'])

    @app.post('/chat/api/conversations/{cid}/read', dependencies=[Depends(owner), Depends(same_origin)], include_in_schema=False)
    async def read(cid: str, body: ReadPosition):
        portal().owner_chat(cid)
        if body.message_id and not portal().db.execute('SELECT 1 FROM chat_messages WHERE id=? AND conversation_id=?', (body.message_id, cid)).fetchone():
            raise HTTPException(404, 'message_not_found')
        portal().db.execute('INSERT INTO web_reads VALUES (?,?) ON CONFLICT(conversation_id) DO UPDATE SET message_id=max(message_id,excluded.message_id)', (cid, body.message_id))
        return {'saved': True}

    @app.post('/chat/api/conversations/{cid}/delete', dependencies=[Depends(owner), Depends(same_origin)], include_in_schema=False)
    async def delete_chat(cid: str):
        async def remove():
            async with app.state.bridge.lock:
                return portal().delete_chat(cid)
        events=getattr(app.state,'events',None)
        if events:
            async with events.lock:
                return await remove()
        return await remove()

    @app.post('/chat/api/conversations/{cid}/archive', dependencies=[Depends(owner), Depends(same_origin)], include_in_schema=False)
    async def archive_chat(cid: str, body: ArchiveChat):
        async def change():
            async with app.state.bridge.lock:
                portal().owner_chat(cid)
                row=portal().db.execute('SELECT client_id FROM conversations WHERE id=?',(cid,)).fetchone()
                portal().store.conversations.set_active(row['client_id'],cid,not body.archived)
                if body.archived and getattr(app.state,'events',None):
                    portal().db.execute("UPDATE mcp_event_subscriptions SET status='revoked' WHERE conversation=?",(cid,))
                return portal().owner_chat(cid)
        events=getattr(app.state,'events',None)
        if events:
            async with events.lock:
                return await change()
        return await change()

    @app.post('/admin/api/chat/login-code', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def code():
        async with app.state.bridge.lock:
            return {'code': portal().issue_code(), 'expires_in': 600, 'url': chat_url()}

    @app.post('/admin/api/chat/revoke-sessions', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def revoke():
        async with app.state.bridge.lock:
            portal().db.execute('DELETE FROM web_sessions')
            portal().store.set('web_login', {})
        return {'revoked': True}
