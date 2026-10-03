"""Verify the actual distributable packages and their self-contained references."""
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

import pytest

TOOLS = Path(__file__).resolve().parents[1]/'tools'
sys.path.insert(0, str(TOOLS))
from package_checks import check
from build_local_plugin import build as local
from build_remote_plugin import build as remote


@pytest.mark.parametrize('transport', ['local', 'remote'])
def test_package_layout_and_references(tmp_path, transport):
    archive = tmp_path/'plugin.zip'
    if transport == 'local':
        local(archive)
    else:
        remote('https://notify.example.com/wechat', archive)
    with zipfile.ZipFile(archive) as bundle:
        assert {name.split('/')[0] for name in bundle.namelist()} == {'wechat-notify-local'}
        assert not any('.private' in name or '__pycache__' in name for name in bundle.namelist())
        bundle.extractall(tmp_path/'unpacked')
    root = tmp_path/'unpacked/wechat-notify-local'
    manifest = check(root)
    assert manifest['version'] == '1.7.0'
    assert manifest['extensions']['com.openai']['interface']['defaultPrompt'] == '通过微信通知插件查看服务状态。'
    if transport == 'local':
        assert (root/'server/api_errors.py').is_file()
    else:
        assert not (root/'server').exists()
        assert json.loads((root/'mcp.json').read_text())['mcpServers']['wechat-notify']['url'] == 'https://notify.example.com/wechat/mcp'


def test_builders_refuse_to_write_inside_plugin_source():
    output = TOOLS.parent/'bad.zip'
    with pytest.raises(ValueError): local(output)
    with pytest.raises(ValueError): remote('https://example.com/wechat', output)
    assert not output.exists()
