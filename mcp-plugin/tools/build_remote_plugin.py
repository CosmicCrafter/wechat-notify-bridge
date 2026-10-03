"""Build the same plugin for cloud/local OAuth hosts; never package API keys."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
import zipfile
from package_checks import check, public_files


def build(base_url, output):
    base = base_url.rstrip('/')
    p = urlsplit(base)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError('An HTTPS service base URL without credentials/query/fragment is required')
    source = Path(__file__).resolve().parents[1]
    manifest = check(source)
    compat = json.loads((source / '.codex-plugin/plugin.json').read_text(encoding='utf-8'))
    name = manifest['name']
    mcp = {'$schema':'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json',
           'mcpServers':{'wechat-notify':{'type':'streamable-http','url':base+'/mcp'}}}
    legacy = {'mcpServers':{'wechat-notify':{'url':base+'/mcp'}}}
    output = Path(output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_relative_to(source):
        raise ValueError('Write the archive outside the plugin source directory')
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for file, value in [('plugin.json',manifest),('.codex-plugin/plugin.json',compat),('mcp.json',mcp),('.mcp.json',legacy)]:
            archive.writestr(name+'/'+file, json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        for path in public_files(source/'skills', {'.md', '.yaml'}):
            archive.write(path, name+'/'+path.relative_to(source).as_posix())
        archive.writestr(name+'/README.md', '# 微信通知（云端与本机）\n\n'
            '使用公开 HTTPS 的 Streamable HTTP MCP。首次连接通过 OAuth 授权页面登录并选择客户端身份。\n\n'
            '登录码在微信发送 /web 获取；密钥、访问令牌和手机登录码都不要粘贴到 AI 聊天。\n\n'
            '连接后先查询身份，再为每个聊天登记名称。服务器统一管理收发、会话和空闲心跳。\n\n'
            '本包不需要本机 Python，也不包含服务器登录凭据。每个宿主需要单独完成授权。\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(build(args.base_url, args.output))
