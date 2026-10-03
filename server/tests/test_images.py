import base64
import io
import time
from PIL import Image
from test_portal import portal,login,ORIGIN
from wechat_bridge.storage.images import normalize,MAX_UPLOAD
from wechat_bridge.storage.client_registry import ClientError
import pytest


def photo():
    out=io.BytesIO();im=Image.new('RGB',(90,60),'red');exif=Image.Exif();exif[270]='private metadata';im.save(out,format='JPEG',exif=exif);return out.getvalue()


def test_image_lifecycle_and_auth(portal):
    store,client,auth,other,chats,_,_=portal;cid=chats[0]['id'];url=f'/chat/api/conversations/{cid}'
    assert client.post(url+'/images',headers=ORIGIN,content=photo()).status_code==401
    login(client)
    assert client.post(url+'/images',content=photo()).status_code==403
    assert client.post(url+'/images',headers=ORIGIN,content=b'not image').status_code==422
    assert client.post(url+'/images',headers=ORIGIN,content=b'x'*(MAX_UPLOAD+1)).status_code==413
    uploaded=client.post(url+'/images',headers=ORIGIN,content=photo());assert uploaded.status_code==200,uploaded.text
    image=uploaded.json();id=image['id'];api=f'/api/conversations/{cid}/images/{id}'
    assert client.get(api,headers=auth).status_code==404
    body={'attachment_ids':[id],'request_id':'image-message-123456'}
    a=client.post(url+'/messages',headers=ORIGIN,json=body);assert a.status_code==200,a.text
    b=client.post(url+'/messages',headers=ORIGIN,json=body);assert b.json()['duplicate']
    assert a.json()['message']['attachments']==[image]
    assert client.get(api).status_code==401
    assert client.get(api,headers=other).status_code==404
    actual=client.get(api,headers=auth);assert actual.status_code==200
    raw=base64.b64decode(actual.json()['data']);assert b'private metadata' not in raw
    assert not Image.open(io.BytesIO(raw)).getexif()
    assert client.get(url+'/images/'+id).content==raw
    encrypted=store.db.execute('SELECT encrypted FROM image_attachments').fetchone()[0];assert raw not in encrypted
    inbox=client.get('/api/inbox',headers=auth,params={'conversation_id':cid}).json();assert inbox['messages'][0]['attachments']==[image]
    assert client.get('/chat/api/conversations').json()['conversations'][0]['preview']=='[图片]'
    assert client.post(url+'/messages',headers=ORIGIN,json={**body,'text':'different'}).status_code==409
    assert client.post(url+'/messages',headers=ORIGIN,json={**body,'request_id':'another-message-123456'}).status_code==409
    otherurl=f"/chat/api/conversations/{chats[1]['id']}"
    assert client.post(otherurl+'/messages',headers=ORIGIN,json=body).status_code==404
    assert client.get(otherurl+'/images/'+id).status_code==404
    assert client.post(url+'/archive',headers=ORIGIN,json={'archived':True}).status_code==200
    assert client.get(api,headers=auth).status_code==200
    assert client.post(url+'/images',headers=ORIGIN,content=photo()).status_code==409
    assert client.post(url+'/messages',headers=ORIGIN,json=body).status_code==409
    assert client.post(url+'/delete',headers=ORIGIN,json={}).status_code==200
    assert client.get(api,headers=auth).status_code==404
    assert store.db.execute('SELECT count(*) FROM image_attachments').fetchone()[0]==0


def test_pending_cleanup_and_validation(portal,monkeypatch):
    store,client,auth,_,chats,_,_=portal;login(client);cid=chats[0]['id'];path=f'/chat/api/conversations/{cid}'
    assert client.post(path+'/messages',headers=ORIGIN,json={'request_id':'empty-message-123456'}).status_code==422
    result=client.post(path+'/images',headers=ORIGIN,content=photo()).json();id=result['id']
    assert client.post(path+'/messages',headers=ORIGIN,json={'request_id':'duplicate-images-123456','attachment_ids':[id,id]}).status_code==422
    store.db.execute('UPDATE image_attachments SET created_at=?',(time.time()-90000,));store.portal.images.cleanup()
    assert store.db.execute('SELECT count(*) FROM image_attachments').fetchone()[0]==0
    monkeypatch.setattr('wechat_bridge.storage.images.MAX_STORAGE',1)
    assert client.post(path+'/images',headers=ORIGIN,content=photo()).status_code==507
    with pytest.raises(ClientError):normalize(b'<svg></svg>')


def test_mcp_returns_image_content():
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from wechat_bridge.mcp.tools import register_tools
    data,mime,_,_=normalize(photo())
    async def request(path):return {'mime':mime,'data':base64.b64encode(data).decode()}
    mcp=FastMCP('test-images');register_tools(mcp,request)
    result=asyncio.run(mcp.call_tool('getImage',{'conversation_id':'a'*32,'image_id':'b'*32}))
    assert result[0].type=='image' and result[0].mimeType=='image/jpeg'
    assert base64.b64decode(result[0].data)==data
