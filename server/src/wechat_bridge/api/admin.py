"""Administrator routes and pairing UI."""
import os

from fastapi import Depends, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse, Response


from wechat_bridge.config import WEB
from wechat_bridge.api.schemas import PairStart, ClientName, PairSession, PairVerify

WEB = WEB / 'admin'


def mount_admin(app, authorize_admin):
    @app.get('/admin/api/clients', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def client_list():
        return {'clients': app.state.bridge.store.clients.list(),
                'base_url': os.environ.get('WECHAT_PUBLIC_BASE_URL', '')}

    async def change_client(operation, *args):
        bridge = app.state.bridge
        async with bridge.lock:
            result = getattr(bridge.store.clients, operation)(*args)
            if operation in ('create', 'rotate'):
                client, key = result
                return {'client': client, 'api_key': key,
                        'base_url': os.environ.get('WECHAT_PUBLIC_BASE_URL', '')}
            return {'client': result}

    @app.post('/admin/api/clients', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def client_create(body: ClientName):
        return await change_client('create', body.name)

    @app.post('/admin/api/clients/{client_id}/rotate', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def client_rotate(client_id: str):
        return await change_client('rotate', client_id)

    @app.post('/admin/api/clients/{client_id}/revoke', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def client_revoke(client_id: str):
        return await change_client('revoke', client_id)

    @app.post('/admin/api/clients/{client_id}/delete', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def client_delete(client_id: str):
        return await change_client('delete', client_id)

    @app.post('/admin/api/clients/{client_id}/rename', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def client_rename(client_id: str, body: ClientName):
        return await change_client('rename', client_id, body.name)

    @app.get('/', include_in_schema=False)
    def index():
        return RedirectResponse('admin/')

    @app.get('/admin', include_in_schema=False)
    def admin_redirect():
        return RedirectResponse('admin/')

    @app.get('/admin/', include_in_schema=False)
    def admin_page():
        return FileResponse(WEB / 'index.html')

    @app.get('/admin/app.js', include_in_schema=False)
    def admin_script():
        return FileResponse(WEB / 'app.js', media_type='text/javascript')

    @app.get('/admin/style.css', include_in_schema=False)
    def admin_style():
        return FileResponse(WEB / 'style.css', media_type='text/css')

    @app.get('/admin/api/status', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def admin_status():
        return {'service': app.state.bridge.store.status(), 'pairing': app.state.pairing.snapshot()}

    @app.post('/admin/api/pairing/start', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def pairing_start(body: PairStart):
        return await app.state.pairing.start(body.replace)

    @app.get('/admin/api/pairing/qr', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    def pairing_qr(session_id: str = Query(min_length=1, max_length=100)):
        current = app.state.pairing
        if current.session_id != session_id or not current.png:
            raise HTTPException(404, 'qr_unavailable')
        return Response(current.png, media_type='image/png')

    @app.post('/admin/api/pairing/verify', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def pairing_verify(body: PairVerify):
        return await app.state.pairing.verify(body.session_id, body.code)

    @app.post('/admin/api/pairing/cancel', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def pairing_cancel(body: PairSession):
        return await app.state.pairing.cancel(body.session_id)

