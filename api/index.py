"""Bot hub, Vercel edition (interim while Railway is down).

Same hub as ../bot-hub/hub.py — same tiers, same three functions
(report / escalate / commandeer), same dashboard widgets — reworked
for Vercel's serverless model:

  * No always-on process: this file is one Vercel Python function
    (`api/index.py`), a plain WSGI app. `vercel.json` rewrites every
    path to it, so the dashboard lives at / and the API at /api/*.
  * No local SQLite: serverless filesystems don't persist between
    requests. Storage is Upstash Redis (what Vercel KV became) over
    its REST API (urllib, no SDK needed). Add the Upstash Redis
    integration from the Vercel Marketplace and connect it to the
    project; either KV_REST_API_URL/KV_REST_API_TOKEN or
    UPSTASH_REDIS_REST_URL/UPSTASH_REDIS_REST_TOKEN are read.
  * Without KV vars the app still runs, but on an in-memory store:
    data is lost between requests. The dashboard says so in a footer
    banner. Don't rely on memory mode for real bot traffic.

Everything else is env config, same as the Railway build:
  BOT_KEYS, BOT_ROLES, BOT_NAMES, DASHBOARD_KEY,
  NEWS_FEEDS, ENTERTAINMENT_FEEDS, FITNESS_APP_URL.
Bots never hold the paid-model key; Opus 5.5 is still a stub here
(`summarize()` / `master_work()`), called only on batched work.

Local test (memory mode, no KV needed):
  BOT_KEYS="miner-1:key1,master-1:mkey" BOT_ROLES="miner-1:miner,master-1:master" \
  PORT=8770 python3 api/index.py
"""
import html
import json
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

# ---- Bot config (same env vars as the Railway build) ----
TIERS = ["miner", "manager", "low_brain", "master"]
MODELS = {
    "miner": os.environ.get("MINER_MODEL", "llama-3.1-8b-instant (Groq)"),
    "manager": os.environ.get("MANAGER_MODEL", "llama-3.3-70b-versatile (Groq)"),
    "low_brain": os.environ.get("LOW_BRAIN_MODEL", "Gemini 2.5 Flash (Google AI Studio)"),
    "master": os.environ.get("MASTER_MODEL", "Opus 5.5"),
}
BOT_KEYS = dict(
    pair.split(":", 1)
    for pair in os.environ.get("BOT_KEYS", "").split(",")
    if ":" in pair
)
BOT_ROLES = dict(
    pair.split(":", 1)
    for pair in os.environ.get("BOT_ROLES", "").split(",")
    if ":" in pair
)
BOT_NAMES = dict(
    pair.split(":", 1)
    for pair in os.environ.get("BOT_NAMES", "").split(",")
    if ":" in pair
)
DASHBOARD_KEY = os.environ.get("DASHBOARD_KEY", "")
NEWS_FEEDS = [u.strip() for u in os.environ.get(
    "NEWS_FEEDS", "https://feeds.bbci.co.uk/news/rss.xml").split(",") if u.strip()]
ENTERTAINMENT_FEEDS = [u.strip() for u in os.environ.get(
    "ENTERTAINMENT_FEEDS",
    "https://rss.marketingtools.apple.com/api/v2/us/music/most-played/10/songs.json,"
    "http://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml").split(",") if u.strip()]
FITNESS_APP_URL = os.environ.get(
    "FITNESS_APP_URL", "https://fitness-tracker-snowy-seven-83.vercel.app/")
FITNESS_REPO_URL = "https://github.com/creatorcee-prog/fitness-tracker"
WIDGET_CACHE_SECONDS = int(os.environ.get("WIDGET_CACHE_SECONDS", "900"))

# Vercel KV stores moved to Upstash, which may inject either naming.
KV_URL = (os.environ.get("KV_REST_API_URL")
          or os.environ.get("UPSTASH_REDIS_REST_URL", "")).rstrip("/")
KV_TOKEN = (os.environ.get("KV_REST_API_TOKEN")
            or os.environ.get("UPSTASH_REDIS_REST_TOKEN", ""))
STORAGE_MODE = "upstash-redis" if (KV_URL and KV_TOKEN) else "memory (not persistent)"


def role_of(bot_id):
    role = BOT_ROLES.get(bot_id, "miner")
    return role if role in TIERS else "miner"


def display_name(bot_id):
    return BOT_NAMES.get(bot_id, "@" + bot_id)


def next_role(role):
    i = TIERS.index(role) if role in TIERS else 0
    return TIERS[min(i + 1, len(TIERS) - 1)]


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---- Storage: one interface, two backends ----
class MemoryStore:
    """Fallback: lives only as long as this process. Fine for local
    tests; on Vercel it resets between requests, so never rely on it
    for real bot traffic."""

    def __init__(self):
        self.reports, self.escalations, self.orders = [], [], {}
        self.order_ids, self.fitness, self.processed, self.seq = [], [], set(), 0

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

    def add_order(self, request, issued_by):
        oid = self._next_id()
        self.orders[oid] = {"id": oid, "request": request, "issued_by": issued_by,
                            "status": "active", "acked_by": [], "created_at": _now()}
        self.order_ids.insert(0, oid)
        return oid

    def list_active_orders(self):
        return [self.orders[i] for i in self.order_ids
                if self.orders[i]["status"] == "active"]

    def ack_order(self, order_id, bot_id):
        order = self.orders.get(order_id)
        if not order:
            return None
        if bot_id not in order["acked_by"]:
            order["acked_by"].append(bot_id)
        return order["acked_by"]

    def add_fitness(self, bot_id, summary):
        self.fitness.insert(0, {"id": self._next_id(), "bot_id": bot_id,
                                "summary": summary, "created_at": _now()})

    def list_fitness(self, limit):
        return self.fitness[:limit]

    def unprocessed_reports(self, limit):
        return [r for r in self.reports if r["id"] not in self.processed][:limit]


class KVStore:
    """Vercel KV over its REST API (Upstash-compatible). One POST per
    command, body is a JSON array: ["LPUSH", key, value]."""

    def __init__(self, url, token):
        self.url, self.token = url, token

    def _cmd(self, *args):
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

    def add_order(self, request, issued_by):
        oid = self._next_id()
        self._cmd("HSET", f"hub:order:{oid}",
                  "request", request, "issued_by", issued_by,
                  "status", "active", "acked_by", "[]", "created_at", _now())
        self._cmd("LPUSH", "hub:order_ids", str(oid))
        return oid

    def list_active_orders(self):
        out = []
        for oid in self._cmd("LRANGE", "hub:order_ids", "0", "99"):
            flat = self._cmd("HGETALL", f"hub:order:{oid}")
            order = dict(zip(flat[::2], flat[1::2]))
            if order.get("status") == "active":
                order["id"] = int(oid)
                order["acked_by"] = json.loads(order.get("acked_by", "[]"))
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


def get_store():
    if KV_URL and KV_TOKEN:
        return KVStore(KV_URL, KV_TOKEN)
    return MemoryStore()


# One shared store per process (local runs reuse it; on Vercel each
# invocation builds its own, which is fine because KV is the memory).
_STORE = None


def store():
    global _STORE
    if _STORE is None:
        _STORE = get_store()
    return _STORE


# ---- Feeds (same sources as the Railway build) ----
_FEED_CACHE = {}  # url -> (fetched_at, [items]); per-process only


def _fetch_url(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "bot-hub/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_rss(data):
    root = ET.fromstring(data)
    items = []
    for el in root.iter("item"):
        title = (el.findtext("title") or "").strip()
        link = (el.findtext("link") or "").strip()
        if link:
            items.append({"title": title or link, "url": link})
    if not items:  # Atom fallback
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for el in root.findall("a:entry", ns):
            title = (el.findtext("a:title", "", ns) or "").strip()
            link_el = el.find("a:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            if link:
                items.append({"title": title or link, "url": link})
    return items[:10]


def _parse_apple_json(data):
    feed = json.loads(data).get("feed", {})
    out = []
    for r in feed.get("results", [])[:10]:
        name, artist, url = r.get("name", ""), r.get("artistName", ""), r.get("url", "")
        if url:
            out.append({"title": f"{name} — {artist}" if artist else name, "url": url})
    return out


def feed_items(url):
    now = time.time()
    hit = _FEED_CACHE.get(url)
    if hit and now - hit[0] < WIDGET_CACHE_SECONDS:
        return hit[1]
    try:
        raw = _fetch_url(url)
        items = _parse_apple_json(raw) if url.endswith(".json") else _parse_rss(raw)
    except Exception:
        items = []  # a dead feed never breaks the dashboard
    _FEED_CACHE[url] = (now, items)
    return items


def widget_items(feeds):
    out = []
    for url in feeds:
        for it in feed_items(url):
            out.append({"source": urlparse(url).netloc, "title": it["title"], "url": it["url"]})
    return out[:20]


def pushed_items(event_type, limit=10):
    """Items bots pushed via /api/report (e.g. miners checking IMDB)."""
    out = []
    for r in store().list_reports(limit * 5, event_type=event_type):
        p = r["payload"]
        if not isinstance(p, dict) or not p.get("title"):
            continue
        out.append({"source": p.get("source") or display_name(r["bot_id"]),
                    "title": p["title"], "url": p.get("url", "")})
        if len(out) >= limit:
            break
    return out


def summarize(unprocessed):
    """TODO: one batched paid-model call over `unprocessed`. Until then
    this returns the batch itself, so the dashboard works with no key."""
    return {
        "note": "Stub summary — no model call made yet. "
        "Wire the paid-model API call in summarize() in api/index.py.",
        "unprocessed_count": len(unprocessed),
        "reports": unprocessed,
    }


def master_work(escalation):
    """TODO: the Master's work queue hook — where the low brain
    requests Opus 5.5 to work on an escalation that reached master."""
    return {
        "note": "Awaiting Master — no model call made yet. "
        "Wire the paid-model API call in master_work() in api/index.py.",
        "escalation": escalation,
    }


# ---- Core request handling (framework-free, so Vercel and the local
# test server both just call handle()) ----
def _json(status, obj):
    return status, "application/json", json.dumps(obj).encode()


def _auth_bot(bot_id, headers):
    return bool(bot_id and BOT_KEYS.get(bot_id)
                 and headers.get("x-bot-key") == BOT_KEYS[bot_id])


def _auth_dashboard(query, headers):
    if not DASHBOARD_KEY:
        return True
    return (headers.get("x-dashboard-key") == DASHBOARD_KEY
            or query.get("key", [None])[0] == DASHBOARD_KEY)


def _limit(query, default):
    """Parse ?limit=; None means invalid (not an int in 1..100)."""
    try:
        n = int(query.get("limit", [str(default)])[0])
    except ValueError:
        return None
    return n if 1 <= n <= 100 else None


def handle(method, path, query, headers, body):
    """Returns (status, content_type, body_bytes). `query` maps names
    to lists of values; `headers` maps lowercased names to values."""
    if method == "POST":
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            return _json(400, {"ok": False, "error": "bad json"})

        if path == "/api/report":
            bot_id, event_type = data.get("bot_id"), data.get("event_type")
            if not bot_id or not event_type or not _auth_bot(bot_id, headers):
                return _json(401, {"ok": False, "error": "bad bot_id or key"})
            store().add_report(bot_id, event_type, data.get("payload", {}))
            return _json(200, {"ok": True})

        if path == "/api/escalate":
            bot_id, issue = data.get("bot_id"), data.get("issue")
            if not bot_id or not issue or not _auth_bot(bot_id, headers):
                return _json(401, {"ok": False, "error": "bad bot_id or key"})
            from_role = role_of(bot_id)
            to_role = data.get("target") or next_role(from_role)
            if to_role not in TIERS:
                return _json(400, {"ok": False, "error": "unknown target tier"})
            status = "awaiting_master" if to_role == "master" else "open"
            esc_id = store().add_escalation(
                bot_id, from_role, to_role, issue, data.get("context", {}), status)
            return _json(200, {"ok": True, "escalation_id": esc_id,
                               "from_role": from_role, "to_role": to_role,
                               "status": status})

        if path == "/api/commandeer":
            bot_id, request = data.get("bot_id"), data.get("request")
            if not bot_id or not request or not _auth_bot(bot_id, headers):
                return _json(401, {"ok": False, "error": "bad bot_id or key"})
            if role_of(bot_id) != "master":
                return _json(403, {"ok": False, "error": "only master may commandeer"})
            order_id = store().add_order(request, bot_id)
            return _json(200, {"ok": True, "order_id": order_id, "status": "active"})

        if path.startswith("/api/orders/") and path.endswith("/ack"):
            bot_id = data.get("bot_id")
            if not bot_id or not _auth_bot(bot_id, headers):
                return _json(401, {"ok": False, "error": "bad bot_id or key"})
            try:
                order_id = int(path.split("/")[3])
            except (IndexError, ValueError):
                return _json(400, {"ok": False, "error": "bad order id"})
            acked = store().ack_order(order_id, bot_id)
            if acked is None:
                return _json(404, {"ok": False, "error": "no such order"})
            return _json(200, {"ok": True, "order_id": order_id, "acked_by": acked})

        if path == "/api/fitness":
            bot_id, summary = data.get("bot_id"), data.get("summary")
            if not bot_id or not isinstance(summary, dict) or not _auth_bot(bot_id, headers):
                return _json(401, {"ok": False, "error": "bad bot_id, key or summary"})
            store().add_fitness(bot_id, summary)
            return _json(200, {"ok": True})

        if path == "/api/summary":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            return _json(200, summarize(store().unprocessed_reports(50)))

        return _json(404, {"ok": False, "error": "unknown route"})

    # GET
    if path == "/":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        st = store()
        reports = st.list_reports(20)
        escs = st.list_escalations(20, open_only=True)
        orders = st.list_active_orders()
        fit_rows = st.list_fitness(1)
        fit = fit_rows[0] if fit_rows else None

        def _render_list(items):
            parts = []
            for w in items[:20]:
                title, src = html.escape(w["title"]), html.escape(w["source"])
                if w.get("url"):
                    parts.append(f"<li><a href=\"{html.escape(w['url'])}\">{title}</a> <i>({src})</i></li>")
                else:
                    parts.append(f"<li>{title} <i>({src})</i></li>")
            return "".join(parts)

        items = "".join(
            f"<li><b>{html.escape(display_name(r['bot_id']))}</b> {html.escape(r['event_type'])} — "
            f"{html.escape(json.dumps(r['payload']))} <i>({html.escape(r['created_at'])})</i></li>"
            for r in reports
        ) or "<li>No reports yet.</li>"
        esc_items = "".join(
            f"<li>#{e['id']} {html.escape(display_name(e['from_bot']))} -&gt; {e['to_role']}: "
            f"{html.escape(e['issue'])} [{e['status']}]</li>"
            for e in escs
        ) or "<li>No open escalations.</li>"
        ord_items = "".join(
            f"<li>#{o['id']} commandeer by {html.escape(display_name(o['issued_by']))}: "
            f"{html.escape(o['request'])}</li>"
            for o in orders
        ) or "<li>No active commandeer orders.</li>"
        ent_items = _render_list(
            pushed_items("entertainment") + widget_items(ENTERTAINMENT_FEEDS)
        ) or "<li>No entertainment items right now.</li>"
        news_items = _render_list(
            pushed_items("news") + widget_items(NEWS_FEEDS)
        ) or "<li>No headlines right now.</li>"
        if fit:
            fit_html = "<ul>" + "".join(
                f"<li><b>{html.escape(str(k))}:</b> {html.escape(str(v))}</li>"
                for k, v in fit["summary"].items()
            ) + f"</ul><i>from {html.escape(display_name(fit['bot_id']))} at {html.escape(fit['created_at'])}</i>"
        else:
            fit_html = ("<p>No health summary yet. The fitness app pushes one to "
                        "POST /api/fitness after each day/session.</p>")
        app_link = (
            f"<p><a href=\"{html.escape(FITNESS_APP_URL)}\">Open fitness app</a></p>"
            if FITNESS_APP_URL else
            f"<p><a href=\"{FITNESS_REPO_URL}\">Fitness app repo</a></p>"
        )
        if STORAGE_MODE.startswith("memory"):
            storage_note = ("<p><i>Storage: memory (not persistent) — data will not "
                            "persist between requests. Connect Upstash Redis to the "
                            "project in Vercel and redeploy to fix this.</i></p>")
        else:
            storage_note = f"<p><i>Storage: {html.escape(STORAGE_MODE)}.</i></p>"
        body = (
            f"<h1>Bot hub</h1>"
            f"<h2>Entertainment</h2><ul>{ent_items}</ul>"
            f"<h2>News</h2><ul>{news_items}</ul>"
            f"<h2>Fitness — overall health</h2>{fit_html}{app_link}"
            f"<h2>Reports</h2><ul>{items}</ul>"
            f"<h2>Escalations</h2><ul>{esc_items}</ul>"
            f"<h2>Commandeer orders</h2><ul>{ord_items}</ul>"
            f"{storage_note}"
        ).encode()
        return 200, "text/html; charset=utf-8", body

    if path == "/api/feed":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        limit = _limit(query, 20)
        if limit is None:
            return _json(400, {"ok": False, "error": "limit must be 1-100"})
        return _json(200, store().list_reports(limit))

    if path == "/api/orders":
        bot_id = query.get("bot_id", [None])[0]
        if not bot_id or not _auth_bot(bot_id, headers):
            return _json(401, {"ok": False, "error": "bad bot_id or key"})
        return _json(200, store().list_active_orders())

    if path == "/api/escalations":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, store().list_escalations(50))

    if path == "/api/widgets":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        fit_rows = store().list_fitness(1)
        return _json(200, {
            "entertainment": (pushed_items("entertainment") + widget_items(ENTERTAINMENT_FEEDS))[:20],
            "news": (pushed_items("news") + widget_items(NEWS_FEEDS))[:20],
            "fitness": fit_rows[0] if fit_rows else None,
        })

    if path == "/api/fitness":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        limit = _limit(query, 10)
        if limit is None:
            return _json(400, {"ok": False, "error": "limit must be 1-100"})
        return _json(200, store().list_fitness(limit))

    if path == "/api/bots":
        bots = []
        for bot_id in sorted(set(BOT_KEYS) | set(BOT_ROLES)):
            bots.append({"bot_id": bot_id, "name": display_name(bot_id),
                         "role": role_of(bot_id), "model": MODELS[role_of(bot_id)]})
        return _json(200, bots)

    if path == "/api/tiers":
        return _json(200, {
            "tiers": TIERS,
            "models": {t: (MODELS[t] or "unset") for t in TIERS},
        })

    return _json(404, {"ok": False, "error": "unknown route"})


# ---- WSGI entry point (what Vercel calls) ----
_REASONS = {200: "OK", 400: "Bad Request", 401: "Unauthorized",
            403: "Forbidden", 404: "Not Found", 500: "Internal Server Error"}


def app(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/") or "/"
    query = parse_qs(environ.get("QUERY_STRING", ""))
    headers = {k[5:].lower().replace("_", "-"): v
               for k, v in environ.items() if k.startswith("HTTP_")}
    try:
        length = int(environ.get("CONTENT_LENGTH", "0") or 0)
    except ValueError:
        length = 0
    body = environ["wsgi.input"].read(length) if length > 0 else b""
    try:
        status, ctype, out = handle(method, path, query, headers, body)
    except Exception as exc:  # e.g. storage down: answer, don't crash
        print(f"handle error on {method} {path}: {exc!r}")
        status, ctype, out = _json(500, {"ok": False, "error": "internal error"})
    start_response(f"{status} {_REASONS.get(status, '')}",
                   [("Content-Type", ctype), ("Content-Length", str(len(out)))])
    return [out]


if __name__ == "__main__":
    # Local test server (memory store unless KV vars are set).
    from wsgiref.simple_server import make_server
    port = int(os.environ.get("PORT", "8770"))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"Bot hub (Vercel edition) on http://{host}:{port} — storage: {STORAGE_MODE}")
    make_server(host, port, app).serve_forever()
