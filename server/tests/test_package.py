"""Contracts affected specifically by the package/layout migration."""
import json
from pathlib import Path

from wechat_bridge.app import create_app
from wechat_bridge.config import WEB
from wechat_bridge import __version__


def test_packaged_assets_and_version():
    for file in ('admin/index.html', 'admin/app.js', 'admin/style.css',
                 'chat/index.html', 'chat/app.js', 'chat/style.css',
                 'oauth/index.html', 'oauth/app.js', 'vendor/marked.js',
                 'vendor/purify.js', 'vendor/vendor-lock.json'):
        assert (WEB / file).is_file(), file
    assert create_app().version == __version__


def test_shared_tool_definitions_and_guide_match():
    root = Path(__file__).resolve().parents[2]
    assert (root / 'server/src/wechat_bridge/mcp/tools.py').read_bytes() == (
        root / 'mcp-plugin/server/toolkit.py').read_bytes()
    assert (root / 'server/src/wechat_bridge/mcp/errors.py').read_bytes() == (
        root / 'mcp-plugin/server/api_errors.py').read_bytes()
    assert (root / 'docs/wechat-markdown/微信Markdown排版指南.md').read_bytes() == (
        root / 'mcp-plugin/skills/wechat-notify/references/wechat-markdown.md').read_bytes()


def test_checked_in_openapi_matches_application():
    server = Path(__file__).resolve().parents[1]
    assert json.loads((server / 'openapi.json').read_text(encoding='utf-8')) == create_app().openapi()
