"""Per-bot WeChat runtime over the common transactional database."""

import hashlib
import json

from wechat_bridge.storage.database import Store
from wechat_bridge.storage.send_diagnostics import SendDiagnostics
from wechat_bridge.channels.registry import BotConversations
from wechat_bridge.wechat.protocol import validate_base


class BotClients:
    def __init__(self, root, bot_id):
        self.root, self.bot_id = root, bot_id

    def __getattr__(self, name):
        return getattr(self.root.clients, name)

    def create(self, name):
        client, key = self.root.clients.create(name)
        self.root.bots.set_grants(client["id"], [self.bot_id], self.bot_id)
        return client, key


class WeChatStore(Store):
    def __init__(self, root, bot_id):
        self.root, self.bot_id = root, bot_id
        self.db, self.cipher, self.channels, self.bots = (
            root.db,
            root.cipher,
            root.channels,
            root.bots,
        )
        self.portal = root.portal
        self.delivery_journal = root.delivery_journal
        self.clients = BotClients(root, bot_id)
        self.conversations = BotConversations(root.bots, bot_id)
        self.send_diagnostics = SendDiagnostics(self)

    def account(self):
        return self.channels.settings("wechat:" + self.bot_id) or None

    def save_account(self, value):
        validate_base(value["base_url"])
        self.bots.check_wechat_binding(self.bot_id, value)
        self.channels.save_settings("wechat:" + self.bot_id, value)

    def state_key(self, key):
        return "bot:" + self.bot_id + ":" + key

    def get(self, key, default=None):
        return self.root.get(self.state_key(key), default)

    def set(self, key, value):
        return self.root.set(self.state_key(key), value)

    def digest(self, dedup_key, client_id=None, conversation_id=None):
        value = [self.bot_id, self.account()["user_id"], client_id, conversation_id, dedup_key]
        return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()

    def close(self):
        # Database lifetime belongs to the root service, not a bot adapter.
        pass
