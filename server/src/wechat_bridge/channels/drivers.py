"""Built-in channel construction and platform-specific operations.

Router owns identity and grants. Drivers own transport differences. These are
in-process extensions, not dynamically downloaded code or extra services.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ChannelDriver:
    create: Callable
    status: Callable
    delivery: Callable
    sync_task: Callable | None = None
    pairing: Callable | None = None


def make_wechat(store, bot_id):
    from wechat_bridge.services.bridge import Bridge
    from wechat_bridge.channels.wechat_store import WeChatStore

    return Bridge(WeChatStore(store, bot_id))


def make_feishu(store, bot_id):
    from wechat_bridge.channels.feishu.adapter import Feishu

    return Feishu(store, bot_id=bot_id)


def wechat_receipt(adapter, key, caller, cid):
    if not adapter.store.account():
        return {"status": "not_found"}
    row = adapter.store.client_receipt(key, caller, cid)
    return adapter.public_receipt(row) if row else {"status": "not_found"}


def make_pairing(adapter, run_workers):
    from wechat_bridge.wechat.pairing import Pairing

    return Pairing(adapter, run_workers=run_workers)


BUILTIN_DRIVERS = {
    "wechat": ChannelDriver(
        make_wechat, lambda adapter: adapter.store.status(), wechat_receipt, pairing=make_pairing
    ),
    "feishu": ChannelDriver(
        make_feishu,
        lambda adapter: adapter.status(),
        lambda adapter, key, caller, cid: adapter.delivery(key, caller, cid),
        sync_task=lambda adapter, cid, tid: adapter.sync_task(cid, tid),
    ),
}
