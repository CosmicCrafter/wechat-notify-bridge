"""MCP adapter for the server-hosted WeChat API. No local WeChat session."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from mcp.server.fastmcp import FastMCP
from credential_store import dpapi
from api_errors import request_json

mcp=FastMCP('WeChat Notifications API',log_level='WARNING')

def settings():
    key=os.environ.get('WECHAT_NOTIFY_API_KEY')
    base=os.environ.get('WECHAT_NOTIFY_BASE_URL','')
    if not key:
        path=os.environ.get('WECHAT_NOTIFY_CREDENTIAL_FILE') or str(Path.home()/'.config/wechat-notify-bridge/client.json')
        try:
            config_path=Path(path).expanduser()
            raw=config_path.read_bytes()
            value=json.loads(dpapi(raw,decrypt=True) if config_path.suffix=='.dpapi' else raw)
            key,base=value['api_key'],value['base_url']
        except Exception:
            raise ValueError('Cannot read client configuration. Set WECHAT_NOTIFY_CREDENTIAL_FILE or the API environment variables.') from None
    if not isinstance(base,str) or not isinstance(key,str) or not base or not key:
        raise ValueError('Configure WECHAT_NOTIFY_BASE_URL and WECHAT_NOTIFY_API_KEY, or a credential file')
    p=urlsplit(base)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError('A trusted HTTPS API URL is required')
    return base.rstrip('/'),key

async def request(path,payload=None,params=None):
    base,key=settings()
    async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
        return await request_json(client, base+path, path,
            headers={'Authorization':'Bearer '+key}, payload=payload, params=params)

from toolkit import register_tools

async def request_proxy(path, payload=None, params=None):
    return await request(path, payload, params)

register_tools(mcp, request_proxy)

if __name__=='__main__':
    mcp.run(transport='stdio')
