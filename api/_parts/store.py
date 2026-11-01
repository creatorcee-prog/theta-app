"""Storage: MemoryStore and KVStore (Upstash Redis), and store().

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part(), not imported: everything here
is still index.<name>, so tests that swap index.<name> keep working.
Names from index.py (os, json, time, _REQ, KV_URL, ...) are in scope."""

# ---- Storage: one interface, two backends ----
class MemoryStore:
    """Fallback: lives only as long as this process. Fine for local
    tests; on Vercel it resets between requests, so never rely on it
    for real bot traffic."""

    def __init__(self):
        self.reports, self.escalations, self.orders = [], [], {}
        self.order_ids, self.fitness, self.processed, self.seq = [], [], set(), 0
        self.seen, self.activity = {}, {}
        self.allchat = []  # newest first
        self.meta = {}
        self.ledger = {}  # "YYYY-MM" -> {id: expense}

    def _next_id(self):
        self.seq += 1
        return self.seq

    def add_report(self, bot_id, event_type, payload):
        item = {"id": self._next_id(), "bot_id": bot_id, "event_type": event_type,
                "payload": payload, "created_at": _now()}
        self.reports.insert(0, item)
        return item["id"]

    def list_reports(self, limit, event_type=None):
        rows = self.reports if event_type is None else [
            r for r in self.reports if r["event_type"] == event_type]
        return rows[:limit]

    def add_escalation(self, from_bot, from_role, to_role, issue, context, status):
        item = {"id": self._next_id(), "from_bot": from_bot, "from_role": from_role,
                "to_role": to_role, "issue": issue, "context": context,
                "status": status, "created_at": _now()}
        self.escalations.insert(0, item)
        return item["id"]

    def list_escalations(self, limit, open_only=False):
        rows = self.escalations if not open_only else [
            e for e in self.escalations if e["status"] != "resolved"]
        return rows[:limit]

    def add_order(self, request, issued_by, targets=None, expires_at=None):
        oid = self._next_id()
        self.orders[oid] = {"id": oid, "request": request, "issued_by": issued_by,
                            "status": "active", "acked_by": [], "created_at": _now(),
                            "targets": list(targets or []), "expires_at": expires_at}
        self.order_ids.insert(0, oid)
        _ORDERS_CACHE["at"] = 0
        return oid

    def list_active_orders(self):
        return [self.orders[i] for i in self.order_ids
                if self.orders[i]["status"] == "active" and order_live(self.orders[i])]

    def close_order(self, order_id):
        order = self.orders.get(order_id)
        if not order or order["status"] != "active":
            return None
        order["status"] = "done"
        _ORDERS_CACHE["at"] = 0
        return order

    def ack_order(self, order_id, bot_id):
        order = self.orders.get(order_id)
        if not order:
            return None
        if bot_id not in order["acked_by"]:
            order["acked_by"].append(bot_id)
            _ORDERS_CACHE["at"] = 0
        return order["acked_by"]

    def add_fitness(self, bot_id, summary):
        self.fitness.insert(0, {"id": self._next_id(), "bot_id": bot_id,
                                "summary": summary, "created_at": _now()})

    def list_fitness(self, limit):
        return self.fitness[:limit]

    def unprocessed_reports(self, limit):
        return [r for r in self.reports if r["id"] not in self.processed][:limit]

    def mark_processed(self, ids):
        self.processed.update(ids)

    def touch(self, bot_id, activity=None):
        self.seen[bot_id] = time.time()
        if activity is not None:
            self.activity[bot_id] = activity

    def add_chat(self, sender, text, kind="message", image=None, channel=None, buttons=None, extra=None, attachments=None):
        if _round_capture(sender, text, kind, image, buttons):
            return {"id": 0, "from": sender, "text": text, "kind": kind, "at": _now()}
        item = {"id": self._next_id(), "from": sender, "text": text, "kind": kind, "at": _now(), **(extra or {})}
        if image:
            item["image"] = image
        if attachments:
            item["attachments"] = attachments
        if channel:
            item["ch"] = channel
        if buttons:
            item["buttons"] = buttons
        self.allchat.insert(0, item)
        del self.allchat[ALLCHAT_KEEP:]
        return item

    def get_meta(self, key):
        return self.meta.get(key)

    def add_expenses(self, month, rows):
        """rows: {id: expense}; returns how many were new (ids dedupe)."""
        book = self.ledger.setdefault(month, {})
        new = {k: v for k, v in rows.items() if k not in book}
        book.update(new)
        return len(new)

    def list_expenses(self, month):
        return list(self.ledger.get(month, {}).values())

    def expense_items(self, month):
        """{id: expense} for a month, so one can be removed."""
        return dict(self.ledger.get(month, {}))

    def remove_expenses(self, month, ids):
        book = self.ledger.get(month, {})
        return sum(1 for i in ids if book.pop(i, None) is not None)

    def set_meta(self, key, value):
        self.meta[key] = value

    def get_meta_many(self, keys):
        return {k: self.meta.get(k) for k in keys}

    def set_meta_many(self, pairs):
        self.meta.update(pairs)

    def list_chat(self, limit):
        return list(reversed(self.allchat[:limit]))  # oldest first

    def list_status(self):
        return {b: {"seen": t, "activity": self.activity.get(b, "")}
                for b, t in self.seen.items()}


class KVStore:
    """Vercel KV over its REST API (Upstash-compatible). One POST per
    command, body is a JSON array: ["LPUSH", key, value]."""

    def __init__(self, url, token):
        self.url, self.token = url, token

    def _cmd(self, *args):
        _REQ.calls = getattr(_REQ, "calls", 0) + 1  # for the Speed card
        req = urllib.request.Request(
            self.url, data=json.dumps(list(args)).encode(),
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            out = json.loads(resp.read())
        if "result" not in out:
            raise RuntimeError(f"KV error: {out}")
        return out["result"]

    def _next_id(self):
        return int(self._cmd("INCR", "hub:seq"))

    def add_report(self, bot_id, event_type, payload):
        rid = self._next_id()
        self._cmd("LPUSH", "hub:reports", json.dumps(
            {"id": rid, "bot_id": bot_id, "event_type": event_type,
             "payload": payload, "created_at": _now()}))
        return rid

    def list_reports(self, limit, event_type=None):
        rows = [json.loads(r) for r in self._cmd("LRANGE", "hub:reports", "0", "99")]
        if event_type is not None:
            rows = [r for r in rows if r["event_type"] == event_type]
        return rows[:limit]

    def add_escalation(self, from_bot, from_role, to_role, issue, context, status):
        eid = self._next_id()
        self._cmd("LPUSH", "hub:escalations", json.dumps(
            {"id": eid, "from_bot": from_bot, "from_role": from_role,
             "to_role": to_role, "issue": issue, "context": context,
             "status": status, "created_at": _now()}))
        return eid

    def list_escalations(self, limit, open_only=False):
        rows = [json.loads(r) for r in self._cmd("LRANGE", "hub:escalations", "0", "99")]
        if open_only:
            rows = [e for e in rows if e["status"] != "resolved"]
        return rows[:limit]

    def add_order(self, request, issued_by, targets=None, expires_at=None):
        oid = self._next_id()
        self._cmd("HSET", f"hub:order:{oid}",
                  "request", request, "issued_by", issued_by,
                  "status", "active", "acked_by", "[]", "created_at", _now(),
                  "targets", json.dumps(list(targets or [])), "expires_at", str(expires_at or ""))
        self._cmd("LPUSH", "hub:order_ids", str(oid))
        _ORDERS_CACHE["at"] = 0
        return oid

    def close_order(self, order_id):
        if self._cmd("HGET", f"hub:order:{order_id}", "status") != "active":
            return None
        self._cmd("HSET", f"hub:order:{order_id}", "status", "done")
        _ORDERS_CACHE["at"] = 0
        flat = self._cmd("HGETALL", f"hub:order:{order_id}")
        return dict(zip(flat[::2], flat[1::2]), id=order_id)

    def list_active_orders(self):
        out = []
        for oid in self._cmd("LRANGE", "hub:order_ids", "0", "99"):
            flat = self._cmd("HGETALL", f"hub:order:{oid}")
            order = dict(zip(flat[::2], flat[1::2]))
            if order.get("status") == "active":
                order["id"] = int(oid)
                order["acked_by"] = json.loads(order.get("acked_by", "[]"))
                order["targets"] = json.loads(order.get("targets") or "[]")
                order["expires_at"] = float(order["expires_at"]) if order.get("expires_at") else None
                if order_live(order):
                    out.append(order)
        return out

    def ack_order(self, order_id, bot_id):
        acked = self._cmd("HGET", f"hub:order:{order_id}", "acked_by")
        if acked is None:
            return None
        names = json.loads(acked)
        if bot_id not in names:
            names.append(bot_id)
            self._cmd("HSET", f"hub:order:{order_id}", "acked_by", json.dumps(names))
            _ORDERS_CACHE["at"] = 0
        return names

    def add_fitness(self, bot_id, summary):
        self._cmd("LPUSH", "hub:fitness", json.dumps(
            {"id": self._next_id(), "bot_id": bot_id,
             "summary": summary, "created_at": _now()}))

    def list_fitness(self, limit):
        return [json.loads(r) for r in self._cmd("LRANGE", "hub:fitness", "0", str(limit - 1))]

    def unprocessed_reports(self, limit):
        done = set(self._cmd("SMEMBERS", "hub:processed") or [])
        return [r for r in self.list_reports(50) if str(r["id"]) not in done][:limit]

    def mark_processed(self, ids):
        if ids:
            self._cmd("SADD", "hub:processed", *[str(i) for i in ids])

    def touch(self, bot_id, activity=None):
        self._cmd("HSET", "hub:seen", bot_id, str(int(time.time())))
        if activity is not None:
            self._cmd("HSET", "hub:activity", bot_id, activity)

    def add_chat(self, sender, text, kind="message", image=None, channel=None, buttons=None, extra=None, attachments=None):
        if _round_capture(sender, text, kind, image, buttons):
            return {"id": 0, "from": sender, "text": text, "kind": kind, "at": _now()}
        item = {"id": self._next_id(), "from": sender, "text": text, "kind": kind, "at": _now(), **(extra or {})}
        if image:
            item["image"] = image
        if attachments:
            item["attachments"] = attachments
        if channel:
            item["ch"] = channel
        if buttons:
            item["buttons"] = buttons
        self._cmd("LPUSH", "hub:allchat", json.dumps(item))
        self._cmd("LTRIM", "hub:allchat", "0", str(ALLCHAT_KEEP - 1))
        return item

    def get_meta(self, key):
        # Within one request, values the hub usually needs are fetched together
        # in one round trip and kept for a few seconds (each trip to Upstash
        # costs tens of ms, and a page reads dozens of values).
        cache = getattr(_REQ, "meta", None)
        if cache is None:
            return self._cmd("HGET", "hub:meta", key)
        now = time.time()
        hit = cache.get(key)
        if hit and now - hit[1] < META_CACHE_SECONDS:
            return hit[0]
        want = [key] + [k for k in _HOT_META if k != key and not (k in cache and now - cache[k][1] < META_CACHE_SECONDS)][:80]
        for k, v in zip(want, self._cmd("HMGET", "hub:meta", *want)):
            cache[k] = (v, now)
        if not key.startswith(_BIG_META):
            _HOT_META.add(key)
        return cache[key][0]

    def add_expenses(self, month, rows):
        """rows: {id: expense}; returns how many were new (ids dedupe)."""
        have = set((self._cmd("HGETALL", f"hub:ledger:{month}") or [])[::2])
        new = [x for k, v in rows.items() if k not in have for x in (k, json.dumps(v))]
        if new:
            self._cmd("HSET", f"hub:ledger:{month}", *new)
        return len(new) // 2

    def list_expenses(self, month):
        flat = self._cmd("HGETALL", f"hub:ledger:{month}") or []
        return [json.loads(v) for v in flat[1::2]]

    def expense_items(self, month):
        """{id: expense} for a month, so one can be removed."""
        flat = self._cmd("HGETALL", f"hub:ledger:{month}") or []
        return {k: json.loads(v) for k, v in zip(flat[::2], flat[1::2])}

    def remove_expenses(self, month, ids):
        return self._cmd("HDEL", f"hub:ledger:{month}", *ids) or 0 if ids else 0

    def set_meta(self, key, value):
        self._cmd("HSET", "hub:meta", key, value)
        cache = getattr(_REQ, "meta", None)
        if cache is not None:
            cache[key] = (value, time.time())

    def get_meta_many(self, keys):
        """{key: value} in one round trip."""
        keys = list(keys)
        return dict(zip(keys, self._cmd("HMGET", "hub:meta", *keys))) if keys else {}

    def set_meta_many(self, pairs):
        if pairs:
            self._cmd("HSET", "hub:meta", *[x for kv in pairs.items() for x in kv])

    def list_chat(self, limit):
        rows = self._cmd("LRANGE", "hub:allchat", "0", str(limit - 1))
        return [json.loads(r) for r in reversed(rows)]  # oldest first

    def list_status(self):
        seen = self._cmd("HGETALL", "hub:seen") or []
        act = self._cmd("HGETALL", "hub:activity") or []
        act = dict(zip(act[::2], act[1::2]))
        return {b: {"seen": float(t), "activity": act.get(b, "")}
                for b, t in zip(seen[::2], seen[1::2])}


def get_store():
    if KV_URL and KV_TOKEN:
        return KVStore(KV_URL, KV_TOKEN)
    return MemoryStore()


# One shared store per process (local runs reuse it; on Vercel each
# invocation builds its own, which is fine because KV is the memory).
_STORE = None


META_CACHE_SECONDS = 3
_BIG_META = ("upload:", "chart:", "vision:", "snap:")  # big values: never fetched in the batch
# Values most pages read, fetched together; grows with what this process sees.
_HOT_META = {"briefs", "cards", "cards:img", "cards:short", "chat:pressed", "daily:history", "daily:items",
             "gmail:flash", "gmail:token", "hub:origin", "key:users", "lenz:feeds:at", "lenz:lib", "llm:cooldown",
             "llm:fallback", "memory", "notes", "notify:rounds", "passkeys", "pk:fails", "push:last", "push:subs",
             "reminders", "round:failures", "round:last", "search:used", "sec:fails", "sec:osv", "sessions",
             "tick:last", "claude:spend", "claude:last_error", "claude:last_ok", "claude:check", "llm:fallback"}


def store():
    global _STORE
    if _STORE is None:
        _STORE = get_store()
    return _STORE
