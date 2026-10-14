"""Independent administrator fixtures using genuine account sessions, never Key auth."""

import secrets
from urllib.parse import urlsplit

from wechat_bridge.config import public_base
from wechat_bridge.storage.admin_accounts import ADMIN_COOKIE, password_hash


def configure_admin(app, headers):
    accounts = app.state.admin_accounts
    if not accounts.account():
        password = secrets.token_urlsafe(32)
        accounts.initialize("维护者", password_hash(password))
        app.state.test_admin_password = password
    token, csrf = accounts.issue()
    base = urlsplit(public_base() or "http://testserver")
    headers.clear()
    headers.update(
        {
            "Cookie": ADMIN_COOKIE + "=" + token,
            "Origin": base.scheme + "://" + base.netloc,
            "X-Admin-Request": "1",
            "X-Admin-CSRF": csrf,
        }
    )
    return headers
