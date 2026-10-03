"""Regression cases from the release review; fake callbacks and temporary data only."""
import asyncio
import base64
import importlib.util
import json
from pathlib import Path
import threading

import pytest
from test_oauth import service
from test_conversations import ingest
from wechat_bridge.mcp.events import CallbackBusy, CallbackError


def subscription(cid, suffix='one'):
    return {'name': 'message.created', 'arguments': {'conversation_id': cid},
            'delivery': {'mode': 'webhook', 'url': 'https://callback.example/' + suffix,
                         'secret': 'whsec_' + base64.b64encode(b'x' * 32).decode()}}


@pytest.mark.parametrize('change', ['unsubscribe', 'archive', 'delete', 'rotate', 'refresh'])
def test_slow_delivery_does_not_block_or_overwrite_changes(service, change):
    app, store, client, c, key, *_ = service
    cid = store.conversations.register(c['id'], 'review-delivery', '审查')['id']
    events = app.state.events
    started, release = threading.Event(), threading.Event()
    fast_delivered = threading.Event()

    def sender(url, secret, sid, eid, value, old=None):
        if 'challenge' in value:
            return 200, json.dumps(value).encode()
        if url.endswith('/one'):
            started.set()
            assert release.wait(5)
        else:
            fast_delivered.set()
        return 200, b'{}'

    events.sender = sender

    async def run():
        args = subscription(cid)
        sid = (await events.handle('events/subscribe', args, key))['id']
        await events.handle('events/subscribe', subscription(cid, 'two'), key)
        ingest(store, '[codex-审查] review', 990)
        task = asyncio.create_task(events.tick())
        try:
            assert await asyncio.to_thread(started.wait, 2)
            assert await asyncio.to_thread(fast_delivered.wait, 2)
            if change == 'unsubscribe':
                await asyncio.wait_for(events.handle('events/unsubscribe', args, key), .5)
            elif change == 'refresh':
                await asyncio.wait_for(events.handle('events/subscribe', args, key), .5)
            else:
                await asyncio.wait_for(events.lock.acquire(), .5)
                try:
                    if change == 'archive':
                        store.conversations.set_active(c['id'], cid, False)
                        store.db.execute("UPDATE mcp_event_subscriptions SET status='revoked' WHERE conversation=?", (cid,))
                    elif change == 'delete':
                        store.portal.delete_chat(cid)
                    else:
                        store.clients.rotate(c['id'])
                finally:
                    events.lock.release()
            before = store.db.execute('SELECT * FROM mcp_event_subscriptions WHERE id=?', (sid,)).fetchone()
        finally:
            release.set()
            await task
        after = store.db.execute('SELECT * FROM mcp_event_subscriptions WHERE id=?', (sid,)).fetchone()
        if change == 'rotate':
            assert after['status'] == 'revoked' and after['cursor'] == before['cursor']
        else:
            assert (tuple(after) if after else None) == (tuple(before) if before else None)

    asyncio.run(run())


def test_unsubscribe_during_verification_cannot_resurrect_subscription(service):
    app, store, client, c, key, *_ = service
    cid = store.conversations.register(c['id'], 'review-verify', '验证')['id']
    events = app.state.events
    started, release = threading.Event(), threading.Event()

    def sender(*args):
        started.set()
        assert release.wait(5)
        return 200, json.dumps(args[4]).encode()

    events.sender = sender

    async def run():
        args = subscription(cid)
        task = asyncio.create_task(events.handle('events/subscribe', args, key))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            await asyncio.wait_for(events.handle('events/unsubscribe', args, key), .5)
        finally:
            release.set()
        with pytest.raises(ValueError, match='subscription changed'):
            await task
        assert store.db.execute('SELECT count(*) FROM mcp_event_subscriptions').fetchone()[0] == 0

    asyncio.run(run())


def test_callback_timeout_keeps_bounded_slot_until_thread_finishes(service):
    events = service[0].state.events
    events.callback_timeout = .05
    events.max_callbacks = 1
    release = threading.Event()
    events.sender = lambda: (release.wait(5), b'{}')

    async def run():
        try:
            with pytest.raises(asyncio.TimeoutError):
                await events.callback('slow')
            assert len(events.callbacks) == 1
            with pytest.raises(CallbackBusy):
                await events.callback('another')
            async with events.lock:
                pass
        finally:
            release.set()
            await asyncio.gather(*events.callbacks.values())
            await asyncio.sleep(0)
        assert not events.callbacks

    asyncio.run(run())


def prepare_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'prepare_secrets.py'
    spec = importlib.util.spec_from_file_location('prepare_review_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('names', [['admin'], ['heartbeat'], ['a' * 33], ['Codex', 'codex']])
def test_invalid_seed_names_rejected_before_creating_files(tmp_path, names):
    output = tmp_path / 'provisioned'
    with pytest.raises(Exception):
        prepare_module().prepare(None, output, 'https://example.com/wechat', names)
    assert not output.exists()


def test_seed_names_use_runtime_normalization_and_support_commands(service, tmp_path):
    store = service[1]
    output = tmp_path / 'provisioned'
    prepare_module().prepare(None, output, 'https://example.com/wechat', ['Review_AI', '测试'])
    store.clients.seed(json.loads((output / 'secrets' / 'clients.json').read_text()))
    from wechat_bridge.services.commands import execute
    for name in ['review_ai', '测试']:
        assert execute(store, '/resetkey ' + name).issued_hash
        execute(store, '/revoke ' + name)
        assert not store.clients.by_name(name)['enabled']
