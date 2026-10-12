"""Shared URL, cookie and packaged asset configuration."""

import os
import posixpath
from pathlib import Path
from urllib.parse import urlencode, urlsplit

SESSION_SECONDS = 30 * 86400
COOKIE = "wechat_chat_session"
WEB = Path(__file__).parent / "web"


def public_base():
    return validated_base(os.environ.get("WECHAT_PUBLIC_BASE_URL", ""))


def oauth_base():
    base = validated_base(os.environ.get("WECHAT_OAUTH_BASE_URL", "") or public_base())
    if base and urlsplit(base).netloc != urlsplit(public_base()).netloc:
        raise ValueError("OAuth base must share the public origin")
    if base and urlsplit(base).scheme != urlsplit(public_base()).scheme:
        raise ValueError("OAuth base must share the public origin")
    return base


def validated_base(value):
    base = value.rstrip("/")
    p = urlsplit(base)
    if not base:
        return ""
    if (
        p.scheme != "https"
        and not (p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1"))
        or not p.hostname
        or p.username
        or p.password
        or p.query
        or p.fragment
        or any(c in base for c in "\n\r()<>")
    ):
        raise ValueError("Invalid WECHAT_PUBLIC_BASE_URL")
    return base


def chat_url(conversation_id=None, message_id=None):
    base = public_base()
    if not base:
        return None
    params = {}
    if conversation_id:
        params["c"] = conversation_id
    if message_id:
        params["m"] = message_id
    return base + "/chat/" + ("?" + urlencode(params) if params else "")


def cookie_path():
    # A migration can retain an OAuth issuer on the legacy prefix.
    paths = [urlsplit(public_base()).path or "/", urlsplit(oauth_base()).path or "/"]
    return (
        posixpath.commonpath(paths).rstrip("/") + "/chat/"
        if paths[0] == paths[1]
        else posixpath.commonpath(paths).rstrip("/") + "/"
    )
