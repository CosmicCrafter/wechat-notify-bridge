"""Configuration must work outside the original author's computer."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from http_bridge import settings


def test_private_json_works_without_windows_or_personal_defaults(tmp_path,monkeypatch):
    path=tmp_path/'client.json'
    path.write_text(json.dumps({'base_url':'https://notify.example.com/wechat','api_key':'fixture-key'}))
    monkeypatch.delenv('WECHAT_NOTIFY_API_KEY',raising=False)
    monkeypatch.delenv('WECHAT_NOTIFY_BASE_URL',raising=False)
    monkeypatch.setenv('WECHAT_NOTIFY_CREDENTIAL_FILE',str(path))
    assert settings()==('https://notify.example.com/wechat','fixture-key')


def test_environment_key_requires_explicit_url(monkeypatch):
    monkeypatch.setenv('WECHAT_NOTIFY_API_KEY','fixture-key')
    monkeypatch.delenv('WECHAT_NOTIFY_BASE_URL',raising=False)
    with pytest.raises(ValueError):
        settings()


def test_numeric_key_is_preserved_as_text(tmp_path,monkeypatch):
    path=tmp_path/'client.json'
    key='1234567890123456789012345678901234567890'
    path.write_text(json.dumps({'base_url':'https://notify.example.com/wechat','api_key':key}))
    monkeypatch.delenv('WECHAT_NOTIFY_API_KEY',raising=False)
    monkeypatch.setenv('WECHAT_NOTIFY_CREDENTIAL_FILE',str(path))
    assert settings()[1]==key
    path.write_text(json.dumps({'base_url':'https://notify.example.com/wechat','api_key':int(key)}))
    with pytest.raises(ValueError): settings()


@pytest.mark.parametrize('url,allowed', [('http://127.0.0.1:8092',True),('http://[::1]:8092',True),('http://192.168.1.2:8092',False),('http://example.com',False),('https://example.com/bridge',True)])
def test_loopback_only_http(url,allowed,monkeypatch):
    monkeypatch.setenv('WECHAT_NOTIFY_API_KEY','fixture-key')
    monkeypatch.setenv('WECHAT_NOTIFY_BASE_URL',url)
    if allowed: assert settings()[0]==url
    else:
        with pytest.raises(ValueError):settings()


def test_environment_credentials_ignore_invalid_optional_launcher_file(tmp_path,monkeypatch):
    import runpy
    import subprocess
    path=tmp_path/'bad.json';path.write_text('{invalid')
    monkeypatch.setenv('WECHAT_NOTIFY_API_KEY','fixture-key')
    monkeypatch.setenv('WECHAT_NOTIFY_BASE_URL','https://example.com/bridge')
    monkeypatch.setenv('WECHAT_NOTIFY_CREDENTIAL_FILE',str(path))
    monkeypatch.delenv('WECHAT_NOTIFY_PYTHON',raising=False)
    called=[]
    monkeypatch.setattr(subprocess,'call',lambda args: called.append(args) or 0)
    with pytest.raises(SystemExit) as exit:
        runpy.run_path(str(Path(__file__).parents[1]/'server/launch.py'),run_name='__main__')
    assert exit.value.code==0 and called


def test_configured_default_bot_is_used_without_overriding_explicit_bot(monkeypatch):
    import asyncio,httpx,http_bridge
    monkeypatch.setenv('WECHAT_NOTIFY_API_KEY','fixture-key')
    monkeypatch.setenv('WECHAT_NOTIFY_BASE_URL','https://example.com/bridge')
    monkeypatch.setenv('WECHAT_NOTIFY_BOT_ID','selected-bot')
    seen=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(200,json={'ok':True})
    client=httpx.AsyncClient
    monkeypatch.setattr(http_bridge.httpx,'AsyncClient',lambda **kwargs:client(transport=httpx.MockTransport(handler),**kwargs))
    async def run():
        await http_bridge.request('/api/messages',{'text':'fixture','dry_run':True})
        await http_bridge.request('/api/messages',{'text':'fixture','dry_run':True,'bot_id':'explicit-bot'})
        await http_bridge.request('/api/deliveries',params={'dedup_key':'fixture'})
    asyncio.run(run())
    assert json.loads(seen[0].content)['bot_id']=='selected-bot'
    assert json.loads(seen[1].content)['bot_id']=='explicit-bot'
    assert seen[2].url.params['bot_id']=='selected-bot'
