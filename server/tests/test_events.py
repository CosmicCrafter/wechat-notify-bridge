import asyncio
import base64
import json
import socket
import time
import pytest
from test_oauth import service
from test_conversations import ingest
from wechat_bridge.mcp.events import public_addresses, callback_parts, signing_key

SECRET='whsec_'+base64.b64encode(b'x'*32).decode()


def test_events_subscription_delivery_scope_refresh_and_revocation(service):
    app,store,client,c,key,other,otherkey=service
    cid=store.conversations.register(c['id'],'events-thread','事件')['id']
    events=app.state.events
    sent=[]
    def sender(url,secret,sid,eid,value,old=None):
        sent.append((eid,value,old))
        return 200,json.dumps({'challenge':value.get('challenge')}).encode()
    events.sender=sender
    def rpc(method,params={},credential=key):
        return client.post('/mcp',headers={'Authorization':'Bearer '+credential},
                           json={'jsonrpc':'2.0','id':1,'method':method,'params':params})
    assert rpc('server/discover').json()['result']['capabilities']['events']=={}
    assert rpc('events/list').json()['result']['events'][0]['name']=='message.created'
    assert rpc('events/list',credential='bad').status_code==401
    args={'name':'message.created','arguments':{'conversation_id':cid},
          'delivery':{'mode':'webhook','url':'https://callback.example/events','secret':SECRET}}
    assert 'error' in rpc('events/subscribe',args,otherkey).json()
    ingest(store,'[codex-事件] before subscription',101)
    first=rpc('events/subscribe',args).json()['result']
    again=rpc('events/subscribe',args).json()['result']
    assert first['id']==again['id']
    assert store.db.execute('SELECT count(*) FROM mcp_event_subscriptions').fetchone()[0]==1
    ingest(store,'[codex-事件] hello',102)
    asyncio.run(events.tick())
    delivered=[s for s in sent if s[0].startswith('wechat_')]
    assert len(delivered)==1 and delivered[0][1]['data']['text']=='hello'
    asyncio.run(events.tick())
    assert len([s for s in sent if s[0].startswith('wechat_')])==1
    # Persisted state can be reopened without replaying the event.
    events.initialize()
    asyncio.run(events.tick())
    assert len([s for s in sent if s[0].startswith('wechat_')])==1
    store.clients.rotate(c['id'])
    asyncio.run(events.tick())
    assert store.db.execute('SELECT status FROM mcp_event_subscriptions').fetchone()[0]=='revoked'


def test_callback_failure_unsubscribe_and_retry_event_id(service):
    app,store,client,c,key,*_=service
    cid=store.conversations.register(c['id'],'retry-thread','重试')['id']
    e=app.state.events
    args={'name':'message.created','arguments':{'conversation_id':cid},
          'delivery':{'mode':'webhook','url':'https://callback.example/events','secret':SECRET}}
    e.sender=lambda *a:(200,b'{"challenge":"wrong"}')
    with pytest.raises(Exception): asyncio.run(e.handle('events/subscribe',args,key))
    assert store.db.execute('SELECT count(*) FROM mcp_event_subscriptions').fetchone()[0]==0
    captured=[]
    def sender(url,secret,sid,eid,value,old=None):
        if 'challenge' in value:return 200,json.dumps(value).encode()
        captured.append(eid)
        return (500 if len(captured)==1 else 410),b''
    e.sender=sender
    asyncio.run(e.handle('events/subscribe',args,key))
    ingest(store,'[codex-重试] test',201)
    asyncio.run(e.tick())
    store.db.execute('UPDATE mcp_event_subscriptions SET next_attempt=0')
    asyncio.run(e.tick())
    assert len(captured)==2 and captured[0]==captured[1]
    assert store.db.execute('SELECT status FROM mcp_event_subscriptions').fetchone()[0]=='failed'
    asyncio.run(e.tick());assert len(captured)==2
    assert asyncio.run(e.handle('events/unsubscribe',args,key))=={}
    assert asyncio.run(e.handle('events/unsubscribe',args,key))=={}


@pytest.mark.parametrize('url',['http://example.com/a','https://user:pass@example.com','https://example.com:444/a','https://example.com/#fragment'])
def test_bad_callback_urls(url):
    with pytest.raises(ValueError):callback_parts(url)


@pytest.mark.parametrize('ip',['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1','224.0.0.1','ff02::1'])
def test_dns_private_and_mixed_answers_blocked(monkeypatch,ip):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**kw:[(0,0,0,'',('8.8.8.8',443)),(0,0,0,'',(ip,443))])
    with pytest.raises(ValueError):public_addresses('example.com')


def test_key_validation():
    assert len(signing_key(SECRET))==32
    with pytest.raises(ValueError):signing_key('whsec_abc')


def test_proxy_exact_scope_and_tls_tunnel(tmp_path, monkeypatch):
    import wechat_bridge.mcp.events as m
    config={'host':'127.0.0.1','port':18093,'username':'test','password':'secret',
            'allowed_hosts':['connectors.api.openai.com']}
    path=tmp_path/'proxy.json'
    path.write_text(json.dumps(config))
    monkeypatch.setenv('WECHAT_CALLBACK_PROXY_FILE',str(path))
    assert m.callback_proxy('connectors.api.openai.com')==config
    for host in ('evil.example','connectors.api.openai.com.evil.example','127.0.0.1'):
        with pytest.raises(ValueError):m.callback_proxy(host)
    calls=[]
    class Sock:
        def sendall(self,data):calls.append(('bytes',data))
        def makefile(self,*args,**kwargs):
            import io
            return io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}')
        def close(self):calls.append(('close',))
    class Tunnel:
        def __init__(self,host,port,timeout):calls.append(('proxy',host,port,timeout));self.sock=Sock()
        def set_tunnel(self,host,port,headers):calls.append(('tunnel',host,port,headers))
        def connect(self):pass
        def close(self):pass
    class TLS:
        def wrap_socket(self,sock,server_hostname):calls.append(('tls',server_hostname));return sock
    monkeypatch.setattr(m.http.client,'HTTPConnection',Tunnel)
    monkeypatch.setattr(m.ssl,'create_default_context',lambda:TLS())
    monkeypatch.setattr(m,'public_addresses',lambda host:pytest.fail('proxy must not use local destination DNS'))
    status,_=m.post_webhook('https://connectors.api.openai.com/test',SECRET,'s','e',{'test':True})
    assert status==200
    assert ('tls','connectors.api.openai.com') in calls
    tunnel=next(x for x in calls if x[0]=='tunnel')
    assert tunnel[1:3]==('connectors.api.openai.com',443)
    assert tunnel[3]['Proxy-Authorization']=='Basic '+base64.b64encode(b'test:secret').decode()
    sent=b''.join(x[1] for x in calls if x[0]=='bytes')
    assert b'Proxy-Authorization' not in sent
