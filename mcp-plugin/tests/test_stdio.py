"""Exercise real stdio MCP discovery and identity calls without a live API or credentials."""
import asyncio
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_tools_and_server_verified_identity(tmp_path):
    server=Path(__file__).resolve().parents[1]/'server'
    harness=tmp_path/'mock_mcp.py'
    harness.write_text('''import sys
sys.path.insert(0, sys.argv[1])
import http_bridge
async def fixture_request(path, payload=None, params=None):
    if path == '/api/status':
        return {'caller':'codex','client_id':'fixture-stable-id','status':'running','conversation_count':0,'conversations':[]}
    if path == '/api/conversations' and payload:
        assert payload['conversation_key'] in ('one','two')
        return {'id':payload['conversation_key'],'name':payload['name']}
    if path == '/api/messages':
        assert payload['dry_run'] and payload['conversation_id'] in ('one','two')
        return {'status':'dry_run_ready','conversation_id':payload['conversation_id']}
    if path == '/api/inbox':
        return {'messages':[],'conversation_id':params['conversation_id'],'next_after_id':0}
    if path == '/api/task-cards':
        assert payload['dry_run']
        mode=payload.get('mode','single')
        if mode=='single':
            assert set(payload)=={'conversation_id','dedup_key','title','prompt','options','allow_custom','expires_in','dry_run'}
            assert payload['allow_custom'] is True
        if mode=='input':
            assert payload['options']==[]
        else:
            assert payload['options'][0]['id']=='a'
        return {'status':'dry_run_ready'}
    if path == '/api/deliveries':
        from api_errors import failure
        raise failure('network_error', 'Check the connection.', path)
    raise AssertionError('Unexpected request')
http_bridge.request=fixture_request
http_bridge.mcp.run(transport='stdio')
''',encoding='utf-8')
    async def run():
        async with asyncio.timeout(20):
            parameters=StdioServerParameters(command=sys.executable,args=[str(harness),str(server)],env={'PYTHONUTF8':'1'})
            async with stdio_client(parameters) as (reader,writer):
                async with ClientSession(reader,writer) as session:
                    await session.initialize()
                    names={tool.name for tool in (await session.list_tools()).tools}
                    assert names=={'getCallerIdentity','getDeliveryStatus','getMessages','sendMessage','sendNotification',
                                   'registerConversation','listConversations','setConversationActive','getImage',
                                   'sendTaskCard','getTaskCard','updateTaskCard'}
                    card=await session.call_tool('sendTaskCard', {'conversation_id':'a'*32,'dedup_key':'card','title':'Choose',
                        'prompt':'Choose a plan','options':[{'id':'a','label':'A'},{'id':'b','label':'B'}],'dry_run':True})
                    assert not card.isError and json.loads(card.content[0].text)['status']=='dry_run_ready'
                    for mode in ['multiple','confirm','input']:
                        card=await session.call_tool('sendTaskCard', {'conversation_id':'a'*32,'dedup_key':mode,
                            'title':'Reply','prompt':'Please reply','mode':mode,'dry_run':True,
                            **({'options':[{'id':'a','label':'A'},{'id':'b','label':'B'}]} if mode!='input' else {})})
                        assert not card.isError and json.loads(card.content[0].text)['status']=='dry_run_ready'
                    result=await session.call_tool('getCallerIdentity',{})
                    assert not result.isError
                    value=json.loads(result.content[0].text)
                    assert value['caller']=='codex' and value['client_id']=='fixture-stable-id'
                    failed=await session.call_tool('getDeliveryStatus',{'dedup_key':'original','conversation_id':'one'})
                    assert failed.isError and 'network_error' in failed.content[0].text
                    error_text=failed.content[0].text
                    assert 'delivery' not in json.loads(error_text[error_text.index('{'):])
                    for id,name in [('one','通知桥'),('two','tibo')]:
                        registered=await session.call_tool('registerConversation',{'conversation_key':id,'name':name})
                        assert not registered.isError
                        assert json.loads(registered.content[0].text)['id']==id
                    for id in ('two','one'):
                        sent=await session.call_tool('sendMessage',{'text':'test','dedup_key':'key','dry_run':True,'conversation_id':id})
                        assert not sent.isError and json.loads(sent.content[0].text)['conversation_id']==id
                        received=await session.call_tool('getMessages',{'conversation_id':id})
                        assert not received.isError and json.loads(received.content[0].text)['conversation_id']==id
    asyncio.run(run())
