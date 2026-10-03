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
