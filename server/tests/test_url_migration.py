import pytest
from wechat_bridge.config import public_base, oauth_base, cookie_path, chat_url


def test_legacy_issuer_and_new_public_url(monkeypatch):
    monkeypatch.setenv('WECHAT_PUBLIC_BASE_URL','https://notify.example.com/bridge')
    monkeypatch.setenv('WECHAT_OAUTH_BASE_URL','https://notify.example.com/wechat')
    assert public_base().endswith('/bridge')
    assert oauth_base().endswith('/wechat')
    assert cookie_path() == '/'
    assert chat_url('cid').startswith('https://notify.example.com/bridge/chat/')


def test_fresh_deployment_and_reject_cross_origin(monkeypatch):
    monkeypatch.setenv('WECHAT_PUBLIC_BASE_URL','https://notify.example.com/bridge')
    monkeypatch.delenv('WECHAT_OAUTH_BASE_URL',raising=False)
    assert oauth_base() == public_base()
    assert cookie_path() == '/bridge/chat/'
    monkeypatch.setenv('WECHAT_OAUTH_BASE_URL','https://other.example.com/wechat')
    with pytest.raises(ValueError): oauth_base()
