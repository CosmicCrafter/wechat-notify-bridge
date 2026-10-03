import asyncio
import base64
import json
import time
from types import SimpleNamespace
from pathlib import Path
from test_oauth import service,grant,BASE
from mcp.shared.auth import OAuthClientInformationFull
from mcp.server.auth.provider import RegistrationError
import pytest

SECRET='whsec_'+base64.b64encode(b'x'*32).decode()

def setup_events(service):
 app,store,client,c,key,*_=service
 cid=store.conversations.register(c['id'],'security-regression','安全回归')['id']
 events=app.state.events;sent=[]
 def sender(url,secret,sid,eid,value,old=None):
  if 'challenge' in value:return 200,json.dumps(value).encode()
  sent.append(value);return 200,b'{}'
 events.sender=sender
 args={'name':'message.created','arguments':{'conversation_id':cid},'delivery':{'mode':'webhook','url':'https://callback.example/events','secret':SECRET}}
 return cid,events,args,sent

def test_revoked_grant_does_not_inherit_other_grant(service):
 app,store,client,c,key,*_=service;cid,events,args,sent=setup_events(service)
 oauth,body,_=grant(service);first=client.post('/token',data=body).json()
 provider=app.state.oauth
 second=provider.issue(oauth['client_id'],c['id'],store.clients.get(c['id'])['key_hash'],['wechat:bridge'])
 asyncio.run(events.handle('events/subscribe',args,first['access_token']))
 assert client.post('/revoke',data={'client_id':oauth['client_id'],'token':first['refresh_token'],'token_type_hint':'refresh_token'}).status_code==200
 assert asyncio.run(provider.load_access_token(second.access_token))
 store.portal.reply(cid,'must not leave revoked grant','grant-revoke-000001');asyncio.run(events.tick())
 assert sent==[]
 assert store.db.execute('SELECT status FROM mcp_event_subscriptions').fetchone()[0]=='revoked'

def test_token_refresh_preserves_subscription_and_revoke_stops_it(service):
 app,store,client,c,*_=service;cid,events,args,sent=setup_events(service)
 oauth,body,_=grant(service);first=client.post('/token',data=body).json()
 asyncio.run(events.handle('events/subscribe',args,first['access_token']))
 refreshed=client.post('/token',data={'client_id':oauth['client_id'],'grant_type':'refresh_token','refresh_token':first['refresh_token'],'resource':BASE+'/mcp'})
 assert refreshed.status_code==200
 second=refreshed.json()
 assert client.get('/api/status',headers={'Authorization':'Bearer '+first['access_token']}).status_code==401
 store.portal.reply(cid,'after token refresh','grant-refresh-00001');asyncio.run(events.tick());assert len(sent)==1
 assert client.post('/revoke',data={'client_id':oauth['client_id'],'token':second['refresh_token'],'token_type_hint':'refresh_token'}).status_code==200
 store.portal.reply(cid,'after revocation','grant-refresh-00002');asyncio.run(events.tick());assert len(sent)==1

def test_legacy_oauth_subscription_fails_closed_but_can_resubscribe(service):
 app,store,client,c,key,*_=service;cid,events,args,sent=setup_events(service)
 oauth,body,_=grant(service);token=client.post('/token',data=body).json()['access_token']
 asyncio.run(events.handle('events/subscribe',args,token))
 row=store.db.execute('SELECT * FROM mcp_event_subscriptions').fetchone();value=json.loads(store.cipher.decrypt(row['encrypted']));value.pop('grant_id')
 store.db.execute('UPDATE mcp_event_subscriptions SET encrypted=?',(store.cipher.encrypt(json.dumps(value).encode()),))
 store.portal.reply(cid,'legacy','legacy-grant-000001');asyncio.run(events.tick());assert sent==[]
 asyncio.run(events.handle('events/subscribe',args,token));asyncio.run(events.tick());assert len(sent)==1

@pytest.mark.parametrize('kind',['expired','revoked','failed'])
def test_subscription_capacity_recovers(service,kind):
 app,store,client,c,key,*_=service;cid,events,args,sent=setup_events(service)
 for i in range(20):
  args['delivery']['url']='https://callback.example/'+str(i)
  asyncio.run(events.handle('events/subscribe',args,key))
 if kind=='expired':store.db.execute('UPDATE mcp_event_subscriptions SET expires=?',(time.time()-1,))
 else:store.db.execute('UPDATE mcp_event_subscriptions SET status=?',(kind,))
 args['delivery']['url']='https://callback.example/new'
 result=asyncio.run(events.handle('events/subscribe',args,key));assert result['id']
 # A dormant subscription must not bypass the active limit when reactivated.
 for i in range(19):
  args['delivery']['url']='https://callback.example/extra'+str(i)
  asyncio.run(events.handle('events/subscribe',args,key))
 args['delivery']['url']='https://callback.example/0'
 with pytest.raises(ValueError,match='subscription limit'):asyncio.run(events.handle('events/subscribe',args,key))

def test_anonymous_registration_expiry_and_approved_preservation(service,monkeypatch):
 app,store,client,c,*_=service;provider=app.state.oauth
 oauth,body,_=grant(service);tokens=client.post('/token',data=body).json()
 for i in range(999):
  asyncio.run(provider.register_client(OAuthClientInformationFull(client_id='anonymous-'+str(i),redirect_uris=['https://example.com/cb'],token_endpoint_auth_method='none')))
 newcomer=OAuthClientInformationFull(client_id='newcomer',redirect_uris=['https://example.com/cb'],token_endpoint_auth_method='none')
 with pytest.raises(RegistrationError):asyncio.run(provider.register_client(newcomer))
 store.db.execute('UPDATE oauth_clients SET created_at=?',(time.time()-601,))
 asyncio.run(provider.register_client(newcomer))
 assert store.db.execute('SELECT count(*) FROM oauth_clients').fetchone()[0]==2
 assert asyncio.run(provider.get_client('anonymous-0')) is None
 assert asyncio.run(provider.get_client(oauth['client_id']))
 assert asyncio.run(provider.load_access_token(tokens['access_token']))

def test_legacy_registration_migration_preserves_existing_authorization(service):
 app,store,client,c,*_=service;provider=app.state.oauth
 oauth,body,_=grant(service);tokens=client.post('/token',data=body).json()
 db=store.db
 db.execute('ALTER TABLE oauth_clients RENAME TO oauth_clients_current')
 db.execute('CREATE TABLE oauth_clients(id TEXT PRIMARY KEY,metadata TEXT NOT NULL)')
 db.execute('INSERT INTO oauth_clients SELECT id,metadata FROM oauth_clients_current')
 db.execute('DROP TABLE oauth_clients_current')
 provider.initialize();provider.initialize()
 row=db.execute('SELECT * FROM oauth_clients').fetchone();assert row['approved']==1 and row['created_at']>0
 assert asyncio.run(provider.load_access_token(tokens['access_token']))

def test_proxy_example_allows_application_image_limit():
 from wechat_bridge.storage.images import MAX_UPLOAD
 import re
 text=(Path(__file__).resolve().parents[1]/'deploy/nginx.conf').read_text()
 size=int(re.search(r'client_max_body_size (\d+)m;',text).group(1))*1024*1024
 assert size>MAX_UPLOAD
