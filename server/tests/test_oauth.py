"""OAuth security and actual Streamable HTTP MCP calls against the existing API."""
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit, parse_qs
import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from wechat_bridge.app import create_app
from wechat_bridge.services.bridge import Bridge
from wechat_bridge.storage.database import Store
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

BASE='https://testserver/wechat'
ORIGIN={'Origin':'https://testserver','X-Chat-Request':'1'}
ADMIN={'Authorization':'Bearer admin-fixture'}

@pytest.fixture
def service(tmp_path,monkeypatch):
    monkeypatch.setenv('WECHAT_PUBLIC_BASE_URL',BASE)
    store=Store(tmp_path/'db',Fernet.generate_key())
    store.bind(dict(bot_token='fixture',bot_id='fixture',user_id='owner',context_token='fixture',base_url='https://ilinkai.weixin.qq.com',bound_at=time.time()))
    c,key=store.clients.create('codex'); other,otherkey=store.clients.create('gpt')
    bridge=Bridge(store,httpx.MockTransport(lambda r:httpx.Response(200,json={'ret':0})))
    app=create_app(bridge,{},False,admin_hash=hashlib.sha256(b'admin-fixture').hexdigest())
    with TestClient(app,base_url='https://testserver') as client:
        code=client.post('/admin/api/chat/login-code',headers=ADMIN).json()['code']
        client.post('/chat/api/login',headers=ORIGIN,json={'code':code})
        # Test transport strips the /wechat proxy prefix, so map cookie to internal route too.
        cookie=client.cookies.get('wechat_chat_session');client.cookies.set('wechat_chat_session',cookie,path='/chat/')
        yield app,store,client,c,key,other,otherkey
    asyncio.run(bridge.close());store.close()

def request(client):
    registered=client.post('/register',json={'client_name':'ChatGPT fixture','redirect_uris':['https://chatgpt.com/connector/oauth/fixture'],
        'token_endpoint_auth_method':'none','grant_types':['authorization_code','refresh_token'],'response_types':['code'],'scope':'wechat:bridge'})
    assert registered.status_code==201,registered.text
    oauth=registered.json(); verifier='a'*64
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    params=dict(client_id=oauth['client_id'],response_type='code',redirect_uri=oauth['redirect_uris'][0],
        code_challenge=challenge,code_challenge_method='S256',scope='wechat:bridge',state='state-fixture',resource=BASE+'/mcp')
    r=client.get('/authorize',params=params,follow_redirects=False)
    assert r.status_code==302,r.text
    sid=parse_qs(urlsplit(r.headers['location']).query)['request'][0]
    return oauth,verifier,sid,params

def grant(service):
    app,store,client,c,*_=service
    oauth,verifier,sid,params=request(client)
    info=client.get('/chat/oauth/request',params={'request_id':sid});assert info.status_code==200,info.text
    result=client.post('/chat/oauth/consent',headers=ORIGIN,json={'request_id':sid,'api_client':c['id'],'allow':True})
    assert result.status_code==200,result.text
    query=parse_qs(urlsplit(result.json()['redirect']).query);assert query['state']==['state-fixture']
    body=dict(client_id=oauth['client_id'],grant_type='authorization_code',code=query['code'][0],
        redirect_uri=params['redirect_uri'],code_verifier=verifier,resource=BASE+'/mcp')
    return oauth,body,sid

def test_discovery_consent_csrf_and_pkce(service):
    app,store,client,c,*_=service
    r=client.post('/mcp',json={});assert r.status_code==401
    assert '/.well-known/oauth-protected-resource/wechat/mcp' in r.headers['www-authenticate']
    md=client.get('/.well-known/oauth-protected-resource/wechat/mcp').json()
    assert md['resource']==BASE+'/mcp' and md['authorization_servers']==[BASE]
    assert 'S256' in client.get('/.well-known/oauth-authorization-server/wechat').json()['code_challenge_methods_supported']
    oauth,body,sid=grant(service)
    assert client.post('/token',data=dict(body,resource='https://evil.test/mcp')).status_code==400
    assert client.post('/token',data=dict(body,code_verifier='wrong')).json()['error']=='invalid_grant'
    token=client.post('/token',data=body);assert token.status_code==200,token.text
    assert client.post('/token',data=body).json()['error']=='invalid_grant'
    assert client.post('/chat/oauth/consent',headers=ORIGIN,json={'request_id':sid,'api_client':c['id'],'allow':True}).status_code==410
    dump=' '.join(store.db.iterdump())
    for value in [body['code'],token.json()['access_token'],token.json()['refresh_token']]: assert value not in dump
    oauth,verifier,sid,params=request(client)
    assert client.post('/chat/oauth/consent',json={'request_id':sid,'api_client':c['id'],'allow':True}).status_code==403
    cookies=client.cookies;client.cookies.clear()
    assert client.get('/chat/oauth/request',params={'request_id':sid}).status_code==401
    client.cookies=cookies
    bad=client.post('/register',json={'redirect_uris':['https://evil.test/cb#fragment']})
    assert bad.status_code==400

@pytest.mark.parametrize('operation',['rotate','revoke','delete'])
def test_refresh_rotation_and_client_revocation(service,operation):
    app,store,client,c,*_=service
    oauth,body,sid=grant(service);tokens=client.post('/token',data=body).json()
    refresh=dict(client_id=oauth['client_id'],grant_type='refresh_token',refresh_token=tokens['refresh_token'],resource=BASE+'/mcp')
    new=client.post('/token',data=refresh);assert new.status_code==200,new.text
    assert client.post('/token',data=refresh).json()['error']=='invalid_grant'
    assert client.get('/api/status',headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==401
    token=new.json()['access_token'];auth={'Authorization':'Bearer '+token}
    assert client.get('/api/status',headers=auth).json()['client_id']==c['id']
    getattr(store.clients,operation)(c['id'])
    assert client.get('/api/status',headers=auth).status_code==401
    assert asyncio.run(app.state.oauth.load_access_token(token)) is None

def test_actual_remote_tools_isolation_and_dry_run(service):
    app,store,client,c,key,other,otherkey=service
    oauth,body,sid=grant(service);token=client.post('/token',data=body).json()['access_token']
    cid=store.conversations.register(c['id'],'fixture-chat','开发')['id']
    othercid=store.conversations.register(other['id'],'other','其他')['id']
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),headers={'Authorization':'Bearer '+token}) as http:
            async with streamable_http_client('https://testserver/mcp',http_client=http) as (read,write,_):
                async with ClientSession(read,write) as session:
                    await session.initialize();tools=await session.list_tools();assert len(tools.tools)==9
                    r=await session.call_tool('getCallerIdentity',{});assert not r.isError
                    assert json.loads(r.content[0].text)['client_id']==c['id']
                    r=await session.call_tool('sendMessage',dict(text='test',dedup_key='dry-test',dry_run=True,conversation_id=cid))
                    assert not r.isError,r
                    assert json.loads(r.content[0].text)['status']=='dry_run_ready'
                    r=await session.call_tool('getMessages',{'conversation_id':othercid});assert r.isError
                    assert 'conversation_not_found' in r.content[0].text
                    assert 'Delivery unconfirmed' not in r.content[0].text
                    assert not next(t for t in tools.tools if t.name=='getMessages').annotations.readOnlyHint
    asyncio.run(run())
    assert store.db.execute('SELECT count(*) FROM outgoing').fetchone()[0]==0
    assert store.db.execute('SELECT count(*) FROM chat_messages').fetchone()[0]==0

def test_oauth_revoke_invalidates_access_and_refresh(service):
    _,store,client,*_=service
    oauth,body,_=grant(service);tokens=client.post('/token',data=body).json()
    r=client.post('/revoke',data={'client_id':oauth['client_id'],'token':tokens['refresh_token'],'token_type_hint':'refresh_token'});assert r.status_code==200
    assert client.get('/api/status',headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==401


def test_legacy_local_keys_are_supported_by_remote_verifier(service):
    app,store,_,*_=service
    store.clients.seed({'legacy':hashlib.sha256(b'legacy-numeric-format-not-required').hexdigest()})
    token=asyncio.run(app.state.oauth.verify_token('legacy-numeric-format-not-required'))
    assert token and token.resource==BASE+'/mcp'
    assert token.subject==store.clients.by_name('legacy')['id']
    assert asyncio.run(app.state.oauth.verify_token('invalid-key')) is None
    store.clients.revoke(token.subject)
    assert asyncio.run(app.state.oauth.verify_token('legacy-numeric-format-not-required')) is None
