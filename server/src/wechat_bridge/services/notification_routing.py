"""Deterministic opt-in notification routes, suppression and fail-closed urgent delivery."""

import asyncio
import hashlib
import json
import time
from wechat_bridge.storage.client_registry import ClientError
from wechat_bridge.core.errors import BridgeError


class NotificationRouting:
    def __init__(self, hub):
        self.hub, self.store, self.db = hub, hub.store, hub.store.db
        self.lock = asyncio.Lock()
        self.db.executescript("""CREATE TABLE IF NOT EXISTS notification_policies (
          client_id TEXT PRIMARY KEY,default_bot TEXT,urgent_bot TEXT,urgent_enabled INTEGER NOT NULL DEFAULT 0,
          interval_seconds INTEGER NOT NULL DEFAULT 60,fallback_bot TEXT);
          CREATE TABLE IF NOT EXISTS notification_preferences (conversation_id TEXT PRIMARY KEY,bot_id TEXT);
          CREATE TABLE IF NOT EXISTS notification_routes (
          key TEXT PRIMARY KEY,client_id TEXT NOT NULL,conversation_id TEXT,payload_hash TEXT NOT NULL,
          level TEXT NOT NULL,selected_bot TEXT NOT NULL,rule TEXT NOT NULL,created_at REAL NOT NULL,
          encrypted BLOB NOT NULL,child_started INTEGER NOT NULL DEFAULT 0,message_id INTEGER);
        """)

    def policy(self, client_id):
        row = self.db.execute(
            "SELECT * FROM notification_policies WHERE client_id=?", (client_id,)
        ).fetchone()
        return {**dict(row), "urgent_enabled": bool(row["urgent_enabled"])} if row else None

    def validate_bot(self, client_id, bot_id):
        if bot_id and not self.store.bots.allowed(client_id, bot_id):
            raise ClientError("bot_access_denied", 403)

    def save_policy(self, client_id, value):
        self.store.clients.get(client_id)
        if value.get("urgent_enabled") and not value.get("urgent_bot"):
            raise ClientError("urgent_bot_required", 422)
        for field in ("default_bot", "urgent_bot", "fallback_bot"):
            self.validate_bot(client_id, value.get(field))
        if (
            value.get("urgent_bot")
            and self.store.bots.get(value["urgent_bot"])["platform"] != "feishu"
        ):
            raise ClientError("urgent_bot_must_be_feishu", 422)
        if value.get("urgent_bot") and value.get("urgent_bot") == value.get("default_bot"):
            raise ClientError("notification_targets_must_differ", 422)
        if value.get("fallback_bot") and value.get("fallback_bot") == value.get("urgent_bot"):
            raise ClientError("notification_targets_must_differ", 422)
        self.db.execute(
            "INSERT INTO notification_policies VALUES (?,?,?,?,?,?) ON CONFLICT(client_id) DO UPDATE SET default_bot=excluded.default_bot,urgent_bot=excluded.urgent_bot,urgent_enabled=excluded.urgent_enabled,interval_seconds=excluded.interval_seconds,fallback_bot=excluded.fallback_bot",
            (
                client_id,
                value.get("default_bot"),
                value.get("urgent_bot"),
                int(value.get("urgent_enabled", False)),
                value.get("interval_seconds", 60),
                value.get("fallback_bot"),
            ),
        )
        return self.policy(client_id)

    def preference(self, cid):
        row = self.db.execute(
            "SELECT bot_id FROM notification_preferences WHERE conversation_id=?", (cid,)
        ).fetchone()
        return row[0] if row else None

    def save_preference(self, cid, bot_id):
        row = self.db.execute(
            "SELECT client_id FROM conversations WHERE id=? AND deleted=0", (cid,)
        ).fetchone()
        if not row:
            raise ClientError("conversation_not_found", 404)
        self.validate_bot(row[0], bot_id)
        if bot_id and bot_id == (self.policy(row[0]) or {}).get("urgent_bot"):
            raise ClientError("urgent_not_authorized", 403)
        self.db.execute(
            "INSERT INTO notification_preferences VALUES (?,?) ON CONFLICT(conversation_id) DO UPDATE SET bot_id=excluded.bot_id",
            (cid, bot_id),
        )
        return {"bot_id": bot_id}

    def key(self, identity, cid, dedup_key, bot_id, channel):
        return hashlib.sha256(
            json.dumps(
                [identity.id, cid, dedup_key, bot_id, channel], separators=(",", ":")
            ).encode()
        ).hexdigest()

    def unpack(self, row):
        return json.loads(self.store.cipher.decrypt(row["encrypted"]))

    def receipt(self, identity, cid, dedup_key, bot_id=None, channel=None):
        row = self.db.execute(
            "SELECT * FROM notification_routes WHERE key=?",
            (self.key(identity, cid, dedup_key, bot_id, channel),),
        ).fetchone()
        if not row:
            return None
        self.store.clients.revalidate(identity)
        self.validate_bot(identity.id, row["selected_bot"])
        value = self.unpack(row)
        result = value["result"]
        if row["child_started"]:
            live = self.hub.raw_delivery(None, dedup_key, identity, cid, row["selected_bot"])
            if live.get("status") != "not_found":
                result = {**result, **live}
            elif result.get("status") == "attempting":
                result = {**result, "status": "unconfirmed_do_not_retry", "sent_now": False}
        return {
            **result,
            "duplicate": True,
            "notification_route": {
                "rule": row["rule"],
                "level": row["level"],
                "bot_id": row["selected_bot"],
                "attempts": value["attempts"],
                "logical_key": row["key"],
            },
        }

    def enabled(self, identity, cid):
        return bool(
            self.policy(identity.id)
            or cid
            and (self.preference(cid) or self.store.lifecycle.public(cid)["muted"])
        )

    def available(self, bot):
        if not bot["enabled"]:
            return False
        if bot["platform"] == "feishu":
            try:
                self.hub.adapter(bot["id"]).ready()
            except (BridgeError, ClientError):
                return False
        return True

    async def send(self, channel, bot_id, level, kwargs):
        identity = kwargs["identity"]
        raw_cid = kwargs.get("conversation_id")
        cid = raw_cid
        if not cid:
            rows = self.store.conversations.rows(identity.id)
            cid = rows[0]["id"] if len(rows) == 1 else None
        key = self.key(identity, raw_cid, kwargs["dedup_key"], bot_id, channel)
        recorded = self.db.execute(
            "SELECT 1 FROM notification_routes WHERE key=?", (key,)
        ).fetchone()
        if not self.enabled(identity, cid) and not recorded:
            return await self.hub.raw_send(channel, bot_id, **kwargs)
        if not cid:
            raise ClientError("conversation_required", 409)
        self.store.conversations.get(identity.id, cid, require_active=True)
        policy = self.policy(identity.id) or {}
        pref = self.preference(cid)
        key = self.key(identity, raw_cid, kwargs["dedup_key"], bot_id, channel)
        fingerprint = hashlib.sha256(
            json.dumps(
                [kwargs["text"], kwargs.get("task_card"), level], sort_keys=True, ensure_ascii=False
            ).encode()
        ).hexdigest()
        async with self.lock:
            identity = self.store.clients.revalidate(identity)
            self.store.receivers.authorize(identity, cid, write=True)
            previous = self.db.execute(
                "SELECT * FROM notification_routes WHERE key=?", (key,)
            ).fetchone()
            if previous:
                if previous["payload_hash"] != fingerprint:
                    raise ClientError("request_id_content_conflict", 409)
                current = self.receipt(identity, raw_cid, kwargs["dedup_key"], bot_id, channel)
                if not kwargs.get("retry_preparation"):
                    return current
                if current["status"] != "not_sent":
                    raise ClientError("delivery_retry_unsafe", 409)
                chosen = self.hub.registry.get(previous["selected_bot"])
                self.validate_bot(identity.id, chosen["id"])
                if chosen["id"] == policy.get("urgent_bot") and not policy.get("urgent_enabled"):
                    raise ClientError("urgent_not_authorized", 403)
                rule = previous["rule"]
                attempts = self.unpack(previous)["attempts"]
                if not previous["child_started"]:
                    kwargs = {k: v for k, v in kwargs.items() if k != "retry_preparation"}
            else:
                selected = bot_id
                rule = "explicit" if bot_id or channel else "application_default"
                if not bot_id and not channel:
                    selected = pref or policy.get("default_bot")
                    rule = "conversation_preference" if pref else "application_default"
                    if level == "urgent" and policy.get("urgent_bot"):
                        if not policy.get("urgent_enabled"):
                            raise ClientError("urgent_not_authorized", 403)
                        selected = policy["urgent_bot"]
                        rule = "authorized_urgent"
                chosen = self.hub.registry.select(identity, selected, channel, sending=False)
                attempts = []
                if chosen["id"] == policy.get("urgent_bot"):
                    if level != "urgent" or not policy.get("urgent_enabled"):
                        raise ClientError("urgent_not_authorized", 403)
                    recent = self.db.execute(
                        "SELECT count(*) FROM notification_routes WHERE client_id=? AND level='urgent' AND created_at>?",
                        (
                            identity.id,
                            time.time() - policy.get("interval_seconds", 60),
                        ),
                    ).fetchone()[0]
                    if recent:
                        raise ClientError("urgent_rate_limited", 429)
            muted = self.store.lifecycle.public(cid)["muted"] and not (
                level == "urgent" and policy.get("urgent_enabled")
            )
            message_id = None
            if muted:
                if kwargs.get("dry_run"):
                    return {
                        "status": "dry_run_ready",
                        "sent_now": False,
                        "muted": True,
                        "bot_id": chosen["id"],
                    }
                self.db.execute("BEGIN IMMEDIATE")
                try:
                    logical = "notification:" + key
                    task_id = (
                        self.store.portal.tasks.create(
                            cid, logical, kwargs["task_card"], time.time()
                        )
                        if kwargs.get("task_card")
                        else None
                    )
                    message_id = self.store.portal.add(
                        cid,
                        "assistant",
                        chosen["platform"],
                        kwargs["text"],
                        "muted",
                        outgoing_key=logical,
                        task_id=task_id,
                        bot_id=chosen["id"],
                    )
                    result = {
                        "status": "muted",
                        "sent_now": False,
                        "phone_delivery": "unconfirmed",
                        "bot_id": chosen["id"],
                        "channel": chosen["platform"],
                        "message_id": message_id,
                    }
                    if task_id:
                        result["task"] = self.store.portal.tasks.get(cid, task_id)
                    rule = "muted"
                    self.write(
                        key,
                        identity.id,
                        raw_cid,
                        fingerprint,
                        level,
                        chosen["id"],
                        rule,
                        result,
                        [
                            {
                                "bot_id": chosen["id"],
                                "status": "muted",
                                "platform_request_started": False,
                            }
                        ],
                        False,
                        message_id,
                    )
                    self.db.commit()
                except Exception:
                    self.db.rollback()
                    raise
            else:
                if not self.available(chosen):
                    attempts.append(
                        {
                            "bot_id": chosen["id"],
                            "status": "not_sent",
                            "phase": "preflight",
                            "platform_request_started": False,
                        }
                    )
                    fallback = policy.get("fallback_bot")
                    if fallback and not previous and not bot_id and not channel:
                        self.validate_bot(identity.id, fallback)
                        chosen = self.hub.registry.get(fallback)
                        rule += ":preflight_fallback"
                if not self.available(chosen):
                    result = {
                        "status": "not_sent",
                        "sent_now": False,
                        "bot_id": chosen["id"],
                        "channel": chosen["platform"],
                        "phase": "routing_preflight",
                        "platform_request_started": False,
                    }
                    if not kwargs.get("dry_run"):
                        self.write(
                            key,
                            identity.id,
                            raw_cid,
                            fingerprint,
                            level,
                            chosen["id"],
                            rule,
                            result,
                            attempts,
                            False,
                            None,
                        )
                else:
                    if not kwargs.get("dry_run"):
                        self.write(
                            key,
                            identity.id,
                            raw_cid,
                            fingerprint,
                            level,
                            chosen["id"],
                            rule,
                            {"status": "attempting", "sent_now": False},
                            attempts,
                            True,
                            None,
                        )
                    result = await self.hub.raw_send(None, chosen["id"], **kwargs)
                    message_id = result.get("message_id")
                    attempts.append({"bot_id": chosen["id"], "status": result["status"]})
                    if not kwargs.get("dry_run"):
                        self.write(
                            key,
                            identity.id,
                            raw_cid,
                            fingerprint,
                            level,
                            chosen["id"],
                            rule,
                            result,
                            attempts,
                            True,
                            message_id,
                        )
            return {
                **result,
                "notification_route": {
                    "rule": rule,
                    "level": level,
                    "bot_id": chosen["id"],
                    "attempts": attempts,
                    "logical_key": key,
                },
            }

    def write(
        self, key, client_id, cid, fingerprint, level, bot, rule, result, attempts, child, mid
    ):
        value = self.store.cipher.encrypt(
            json.dumps({"result": result, "attempts": attempts}, ensure_ascii=False).encode()
        )
        self.db.execute(
            "INSERT INTO notification_routes VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET encrypted=excluded.encrypted,child_started=excluded.child_started,message_id=excluded.message_id",
            (
                key,
                client_id,
                cid,
                fingerprint,
                level,
                bot,
                rule,
                time.time(),
                value,
                int(child),
                mid,
            ),
        )

    def rows(self, client_id=None, cid=None):
        where = []
        args = []
        if client_id:
            where.append("client_id=?")
            args.append(client_id)
        if cid:
            where.append("conversation_id=?")
            args.append(cid)
        query = (
            "SELECT * FROM notification_routes"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY created_at DESC LIMIT 100"
        )
        return [
            {
                **{
                    k: r[k]
                    for k in (
                        "key",
                        "client_id",
                        "conversation_id",
                        "level",
                        "selected_bot",
                        "rule",
                        "created_at",
                        "message_id",
                    )
                },
                **self.unpack(r),
            }
            for r in self.db.execute(query, args)
        ]
