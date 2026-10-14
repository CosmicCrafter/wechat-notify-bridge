"""Administrator read views over the existing shared message ledger."""

import time
import hashlib


class AdminQueries:
    def __init__(self, store):
        self.store, self.db = store, store.db

    def conversations(self, *, q="", client_id=None, archived=None, offset=0, limit=30):
        where = ["s.deleted=0"]
        args = []
        if q:
            where.append(
                "(instr(lower(s.name),lower(?))>0 OR instr(lower(c.name),lower(?))>0 OR s.id=?)"
            )
            args += [q, q, q]
        if client_id:
            where.append("s.client_id=?")
            args.append(client_id)
        if archived is not None:
            where.append("s.active=?")
            args.append(0 if archived else 1)
        clause = " AND ".join(where)
        total = self.db.execute(
            "SELECT count(*) FROM conversations s LEFT JOIN api_clients c ON c.id=s.client_id WHERE "
            + clause,
            args,
        ).fetchone()[0]
        rows = self.db.execute(
            "SELECT s.*,c.name AS caller,c.enabled AS client_enabled,c.last_seen_at,"
            "(SELECT max(id) FROM chat_messages WHERE conversation_id=s.id) AS last_message_id,"
            "coalesce((SELECT pinned FROM web_preferences WHERE conversation_id=s.id),0) AS pinned "
            "FROM conversations s LEFT JOIN api_clients c ON c.id=s.client_id WHERE "
            + clause
            + " ORDER BY pinned DESC,coalesce(last_message_id,0) DESC,s.created_at DESC,s.id LIMIT ? OFFSET ?",
            [*args, limit, offset],
        ).fetchall()
        items = []
        for row in rows:
            item = self.store.portal.owner_chat(row["id"])
            last = self.db.execute(
                "SELECT * FROM chat_messages WHERE id=?", (row["last_message_id"],)
            ).fetchone()
            decoded = self.store.portal.decode(last) if last else None
            item.update(
                client_id=row["client_id"],
                last_seen_at=row["last_seen_at"],
                last_message=decoded,
                pinned=bool(row["pinned"]),
                pending_tasks=self.db.execute(
                    "SELECT count(*) FROM task_cards WHERE conversation_id=? AND status='pending' AND expires_at>?",
                    (row["id"], time.time()),
                ).fetchone()[0],
                receive_method="http_inbox"
                if row["client_enabled"]
                and self.store.clients.credentials.can_receive(row["client_id"])
                else None,
            )
            items.append(item)
        return {"conversations": items, "total": total, "offset": offset, "limit": limit}

    def history(self, cid, **kwargs):
        result = self.store.portal.history(cid, **kwargs)
        result.pop("read_through", None)
        return result

    def message_states(self, cid, ids):
        return self.store.portal.message_states(cid, ids)

    def deliveries(
        self,
        *,
        client_id=None,
        bot_id=None,
        cid=None,
        status=None,
        q="",
        after=0,
        before=0,
        offset=0,
        limit=30,
    ):
        where = ["1=1"]
        args = []
        for value, clause in (
            (client_id, "coalesce(c.client_id,r.client_id)=?"),
            (bot_id, "d.bot_id=?"),
            (cid, "d.conversation_id=?"),
            (status, "d.status=?"),
        ):
            if value:
                where.append(clause)
                args.append(value)
        if after:
            where.append("d.attempted_at>=?")
            args.append(after)
        if before:
            where.append("d.attempted_at<=?")
            args.append(before)
        if q:
            where.append(
                "(d.key=? OR CAST(d.message_id AS TEXT)=? OR instr(d.caller,?)>0 OR r.dedup_hash=?)"
            )
            args += [q, q, q, hashlib.sha256(q.encode()).hexdigest()]
        cte = """WITH d AS (
         SELECT o.key,o.status,o.attempted_at,o.finished_at,o.error_code,'wechat' AS channel,
          coalesce(b.bot_id,'default') AS bot_id,m.conversation_id,m.id AS message_id,o.caller
         FROM outgoing o LEFT JOIN outgoing_bots b ON b.outgoing_key=o.key
          LEFT JOIN chat_messages m ON m.outgoing_key=o.key
         UNION ALL
         SELECT o.key,o.status,o.attempted_at,o.finished_at,o.error_code,'feishu',
          substr(o.channel,8),o.conversation_id,m.id,coalesce(a.name,'系统')
         FROM channel_outgoing o LEFT JOIN chat_messages m ON m.outgoing_key=o.key
          LEFT JOIN conversations c ON c.id=o.conversation_id LEFT JOIN api_clients a ON a.id=c.client_id
        ) """
        join = (
            " FROM d LEFT JOIN conversations c ON c.id=d.conversation_id LEFT JOIN delivery_requests r ON r.key=d.key WHERE "
            + " AND ".join(where)
        )
        total = self.db.execute(cte + "SELECT count(*)" + join, args).fetchone()[0]
        rows = self.db.execute(
            cte
            + "SELECT d.*,coalesce(c.client_id,r.client_id) AS client_id"
            + join
            + " ORDER BY d.attempted_at DESC,d.key LIMIT ? OFFSET ?",
            [*args, limit, offset],
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            if row["channel"] == "wechat":
                item["diagnostics"] = self.store.send_diagnostics.public(row["key"])
            else:
                parent = self.store.channels.receipt(row["key"])
                data = (
                    self.store.channels.decrypt(parent["encrypted"])
                    if parent and parent["encrypted"]
                    else {}
                )
                item["diagnostics"] = {
                    k: v for k, v in (data or {}).items() if k != "provider_message_id"
                }
            item["phone_delivery"] = "unconfirmed"
            item.update(self.store.delivery_journal.public(row["key"]))
            evidence = item["diagnostics"] or {}
            item["retryable"] = (
                row["channel"] == "feishu"
                and row["status"] == "not_sent"
                and evidence.get("phase") == "preparation"
                and evidence.get("platform_request_started") is False
                and item["history_complete"]
            )
            items.append(item)
        return {"deliveries": items, "total": total, "offset": offset, "limit": limit}

    def overview(self):
        since = time.time() - 86400
        counts = {}
        for label, states in {
            "failed": ("api_rejected", "not_sent"),
            "unknown": ("unconfirmed_do_not_retry", "attempting"),
        }.items():
            placeholders = ",".join("?" for _ in states)
            counts[label] = sum(
                self.db.execute(
                    "SELECT count(*) FROM "
                    + table
                    + " WHERE attempted_at>=? AND status IN ("
                    + placeholders
                    + ")",
                    [since, *states],
                ).fetchone()[0]
                for table in ("outgoing", "channel_outgoing")
            )
        pending = self.db.execute(
            "SELECT count(*) FROM task_cards t JOIN conversations c ON c.id=t.conversation_id JOIN api_clients a ON a.id=c.client_id WHERE t.status='pending' AND t.expires_at>? AND c.active=1 AND c.deleted=0 AND a.enabled=1",
            (time.time(),),
        ).fetchone()[0]
        return {
            "window_seconds": 86400,
            "counts": dict(counts, pending_tasks=pending),
            "applications": len(self.store.clients.list()),
            "conversations": self.conversations(limit=5)["conversations"],
            "recent_deliveries": self.deliveries(limit=5)["deliveries"],
        }
