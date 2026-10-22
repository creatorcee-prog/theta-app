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
Agents are named personas (Theta, Mistral, Glass, ...), like James
in Garage Gym: the name is the persona, the model comes from the
agent's tier. Bots never hold the model keys; the hub does
(GROQ_API_KEY, GEMINI_API_KEY). Every agent can be chatted with from
the dashboard (POST /api/chat). The paid high-brain model isn't wired
yet, so the low brain's model stands in for Theta in chat,
`summarize()` and `master_work()`.

Local test (memory mode, no KV needed):
  BOT_KEYS="miner-1:key1,master-1:mkey" BOT_ROLES="miner-1:miner,master-1:master" \
  PORT=8770 python3 api/index.py
"""
import hashlib
import html
import json
import os
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlparse

# ---- Bot config (same env vars as the Railway build) ----
TIERS = ["miner", "manager", "low_brain", "master"]
TIER_LABELS = {"miner": "Miner", "manager": "Manager",
               "low_brain": "Low Brain", "master": "High Brain"}
# Chat APIs (all OpenAI-compatible): provider -> (endpoint, key env var)
PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "GEMINI_API_KEY"),
}
# Thinking models count their reasoning against max_tokens, so ask for
# little of it. Gemini 3 can't turn thinking off ("none" was 2.5 only);
# on Groq only the gpt-oss models take reasoning_effort. "" sends nothing.
GEMINI_REASONING_EFFORT = os.environ.get("GEMINI_REASONING_EFFORT", "low")
GROQ_REASONING_EFFORT = os.environ.get("GROQ_REASONING_EFFORT", "low")
# tier -> (provider, model id); *_MODEL env vars override the model id
TIER_LLM = {
    "miner": ("groq", os.environ.get("MINER_MODEL", "openai/gpt-oss-20b")),
    "manager": ("groq", os.environ.get("MANAGER_MODEL", "openai/gpt-oss-120b")),
    "low_brain": ("gemini", os.environ.get("LOW_BRAIN_MODEL", "gemini-3.8-flash")),
}
# The paid master model isn't wired yet; the low brain answers for it.
MASTER_MODEL = os.environ.get("MASTER_MODEL", "Opus 5.5")
MODELS = {t: f"{m} ({p.title()})" for t, (p, m) in TIER_LLM.items()}
MODELS["master"] = f"{MASTER_MODEL} (not connected; {TIER_LLM['low_brain'][1]} standing in)"
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT_SECONDS", "25"))
CHAT_HISTORY = 20  # most recent messages sent per chat request
ALLCHAT_KEEP = 200  # All Agents chat: messages kept
ALLCHAT_MENTIONS = 3  # agents that may answer one message of yours
# With no @mention, Mistral picks up to this many agents to answer
# ("off" in ALLCHAT_AUTO keeps un-mentioned messages unanswered).
ALLCHAT_AUTO = os.environ.get("ALLCHAT_AUTO", "on").lower() != "off"
ALLCHAT_AUTO_MAX = int(os.environ.get("ALLCHAT_AUTO_MAX", "2"))
# Rounds: Supabase Cron calls /api/round (Bearer CRON_SECRET) a few times a
# day; an agent's job is skipped if it ran less than ROUND_MIN_GAP_MINUTES ago.
CRON_SECRET = os.environ.get("CRON_SECRET", "")
ROUND_MIN_GAP = int(os.environ.get("ROUND_MIN_GAP_MINUTES", "120")) * 60

# ---- Agents: the hub's named personas. The name is the persona, not
# the model (like James in Garage Gym); each runs on its tier's model.
# An agent's id doubles as its bot_id in BOT_KEYS when it runs as a bot.
AGENTS = {
    "theta": {"name": "Theta", "tier": "master",
              "role": "You have the final say: escalations that reach the top, "
                      "big-picture planning and commandeer orders."},
    "mistral": {"name": "Mistral", "tier": "low_brain",
                "role": "You triage what the managers escalate, summarize the "
                        "bots' reports and decide what is worth Theta's time."},
    "glass": {"name": "Glass", "tier": "manager",
              "role": "You are the accountant and general manager: budgets, "
                      "bills and spending, and keeping the other bots on task."},
    "remi": {"name": "Remi", "tier": "manager",
             "role": "You manage family reminders and the calendar, and "
                     "auto-moderate the family Discord, firm about its rules."},
    "lenz": {"name": "Lenz", "tier": "miner",
             "role": "You cover entertainment: movies, TV, music and what is "
                     "worth watching or hearing."},
    "red": {"name": "Red", "tier": "miner",
            "role": "You search and report the news and argue the Republican / "
                    "conservative side of it. Say plainly it's a partisan take, "
                    "and never invent facts."},
    "blue": {"name": "Blue", "tier": "miner",
             "role": "You search and report the news and argue the Democratic / "
                     "progressive side of it. Say plainly it's a partisan take, "
                     "and never invent facts."},
    "gray": {"name": "Gray", "tier": "miner",
             "role": "You search and report the news from an independent view, "
                     "skeptical of both parties. Never invent facts."},
    "charter": {"name": "Charter", "tier": "miner",
                "role": "You make charts from the user's and other bots' "
                        "requests and hand them back: say the chart type, axes "
                        "and data plainly."},
    # James lives in Garage Gym: chat goes to his own prompt and your
    # training data there (see james_chat), not to a role prompt here.
    "james": {"name": "James", "tier": "manager", "home": "Garage Gym",
              "role": "You are the fitness coach from Garage Gym."},
}
# Persona keywords picked in the Crew Files artifact. They shape each
# agent's prompt (see system_prompt); "concise" asks for brevity. James's
# persona lives in Garage Gym's own prompt, so he has none here.
PERSONAS = {
    "theta": ["decisive", "strategic", "big-picture", "authoritative", "concise",
              "blunt", "stoic", "visionary"],
    "mistral": ["analytical", "prioritizing", "organized", "concise", "detail-oriented",
                "humble", "efficient", "nerdy"],
    "glass": ["meticulous", "numbers-first", "organized", "accountable", "budget-minded",
              "taskmaster", "concise", "tactful", "deadline-driven", "dry humor", "calm",
              "spreadsheet-loving"],
    "remi": ["motherly", "warm", "caring", "firm", "organized", "protective", "concise",
             "patient", "gentle", "cheerful", "family-first", "sentimental",
             "celebrates birthdays"],
    "lenz": ["pop-culture savvy", "recommender", "enthusiastic", "music nerd",
             "trend-spotting", "cinephile", "spoiler-careful", "honest critic",
             "genre-hopping"],
    "red": ["Republican view", "conservative", "news reporter", "argumentative",
            "labels it partisan", "fact-first", "concise"],
    "blue": ["Democratic view", "progressive", "news reporter", "argumentative",
             "labels it partisan", "fact-first", "concise"],
    "gray": ["independent", "skeptical of both parties", "news reporter", "fact-first",
             "concise"],
    "charter": ["precise", "visual", "clear", "data-driven", "concise", "labels everything",
                "color-savvy", "annotation-heavy", "asks clarifying questions", "storyteller"],
}
# A bot counts as online if it called the hub this recently.
AGENT_ONLINE_SECONDS = int(os.environ.get("AGENT_ONLINE_SECONDS", "600"))
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
# Many outlets, few stories each, across the spectrum.
NEWS_FEEDS = [u.strip() for u in os.environ.get(
    "NEWS_FEEDS",
    "https://feeds.npr.org/1001/rss.xml,"
    "https://www.pbs.org/newshour/feeds/rss/headlines,"
    "https://abcnews.go.com/abcnews/topstories,"
    "https://www.cbsnews.com/latest/rss/main,"
    "https://feeds.nbcnews.com/nbcnews/public/news,"
    "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml,"
    "https://thehill.com/news/feed/,"
    "https://moxie.foxnews.com/google-publisher/latest.xml,"
    "https://nypost.com/feed/,"
    "https://feeds.bbci.co.uk/news/rss.xml").split(",") if u.strip()]
# Display names for the default outlets (others use the feed's own title).
NEWS_SOURCE_NAMES = {
    "feeds.npr.org": "NPR", "www.pbs.org": "PBS NewsHour", "abcnews.go.com": "ABC News",
    "www.cbsnews.com": "CBS News", "feeds.nbcnews.com": "NBC News",
    "rss.nytimes.com": "New York Times", "thehill.com": "The Hill",
    "moxie.foxnews.com": "Fox News", "nypost.com": "New York Post",
    "feeds.bbci.co.uk": "BBC News",
}
NEWS_TOP = int(os.environ.get("NEWS_TOP", "8"))
NEWS_BREAKING_MAX = int(os.environ.get("NEWS_BREAKING_MAX", "2"))
NEWS_BREAKING_MINUTES = int(os.environ.get("NEWS_BREAKING_MINUTES", "90"))
ENTERTAINMENT_FEEDS = [u.strip() for u in os.environ.get(
    "ENTERTAINMENT_FEEDS",
    "https://rss.marketingtools.apple.com/api/v2/us/music/most-played/10/songs.json,"
    "http://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml").split(",") if u.strip()]
FITNESS_APP_URL = os.environ.get(
    "FITNESS_APP_URL", "https://fitness-tracker-snowy-seven-83.vercel.app/")
FITNESS_REPO_URL = "https://github.com/creatorcee-prog/fitness-tracker"
# Garage Gym's /api/hub (James): GARAGE_GYM_SECRET must equal its HUB_SECRET.
GARAGE_GYM_URL = (os.environ.get("GARAGE_GYM_URL") or FITNESS_APP_URL).rstrip("/")
GARAGE_GYM_SECRET = os.environ.get("GARAGE_GYM_SECRET", "")
WIDGET_CACHE_SECONDS = int(os.environ.get("WIDGET_CACHE_SECONDS", "900"))

# Vercel KV stores moved to Upstash, which may inject either naming.
KV_URL = (os.environ.get("KV_REST_API_URL")
          or os.environ.get("UPSTASH_REDIS_REST_URL", "")).rstrip("/")
KV_TOKEN = (os.environ.get("KV_REST_API_TOKEN")
            or os.environ.get("UPSTASH_REDIS_REST_TOKEN", ""))
STORAGE_MODE = "upstash-redis" if (KV_URL and KV_TOKEN) else "memory (not persistent)"


def role_of(bot_id):
    role = BOT_ROLES.get(bot_id) or AGENTS.get(bot_id, {}).get("tier", "miner")
    return role if role in TIERS else "miner"


def display_name(bot_id):
    if bot_id in BOT_NAMES:
        return BOT_NAMES[bot_id]
    return AGENTS[bot_id]["name"] if bot_id in AGENTS else "@" + bot_id


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
        self.seen, self.activity = {}, {}
        self.allchat = []  # newest first
        self.meta = {}

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

    def mark_processed(self, ids):
        self.processed.update(ids)

    def touch(self, bot_id, activity=None):
        self.seen[bot_id] = time.time()
        if activity is not None:
            self.activity[bot_id] = activity

    def add_chat(self, sender, text, kind="message"):
        item = {"id": self._next_id(), "from": sender, "text": text, "kind": kind, "at": _now()}
        self.allchat.insert(0, item)
        del self.allchat[ALLCHAT_KEEP:]
        return item

    def get_meta(self, key):
        return self.meta.get(key)

    def set_meta(self, key, value):
        self.meta[key] = value

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

    def mark_processed(self, ids):
        if ids:
            self._cmd("SADD", "hub:processed", *[str(i) for i in ids])

    def touch(self, bot_id, activity=None):
        self._cmd("HSET", "hub:seen", bot_id, str(int(time.time())))
        if activity is not None:
            self._cmd("HSET", "hub:activity", bot_id, activity)

    def add_chat(self, sender, text, kind="message"):
        item = {"id": self._next_id(), "from": sender, "text": text, "kind": kind, "at": _now()}
        self._cmd("LPUSH", "hub:allchat", json.dumps(item))
        self._cmd("LTRIM", "hub:allchat", "0", str(ALLCHAT_KEEP - 1))
        return item

    def get_meta(self, key):
        return self._cmd("HGET", "hub:meta", key)

    def set_meta(self, key, value):
        self._cmd("HSET", "hub:meta", key, value)

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


def store():
    global _STORE
    if _STORE is None:
        _STORE = get_store()
    return _STORE


# ---- Feeds (same sources as the Railway build) ----
_FEED_CACHE = {}  # url -> (fetched_at, [items]); per-process only


def _fetch_url(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "bot-hub/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_date(text):
    """RSS (RFC 822) or Atom (ISO 8601) date -> epoch seconds, or None."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _parse_rss(data):
    root = ET.fromstring(data)
    source = (root.findtext("channel/title") or "").strip()[:40]
    items = []
    for el in root.iter("item"):
        title = (el.findtext("title") or "").strip()
        link = (el.findtext("link") or "").strip()
        if link:
            items.append({"title": title or link, "url": link, "source": source,
                          "published": _parse_date(el.findtext("pubDate"))})
    if not items:  # Atom fallback
        ns = {"a": "http://www.w3.org/2005/Atom"}
        source = (root.findtext("a:title", "", ns) or "").strip()[:40]
        for el in root.findall("a:entry", ns):
            title = (el.findtext("a:title", "", ns) or "").strip()
            link_el = el.find("a:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            if link:
                items.append({"title": title or link, "url": link, "source": source,
                              "published": _parse_date(el.findtext("a:updated", "", ns)
                                                       or el.findtext("a:published", "", ns))})
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


def _fetch_feeds(urls):
    """feed_items() for each url, fetched in parallel (one slow outlet
    doesn't hold up the rest)."""
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=min(10, len(urls))) as ex:
        return list(ex.map(feed_items, urls))


def widget_items(feeds):
    out = []
    for url, items in zip(feeds, _fetch_feeds(feeds)):
        for it in items:
            out.append({"source": it.get("source") or urlparse(url).netloc,
                        "title": it["title"], "url": it["url"]})
    return out[:20]


_BREAKING_WORDS = ("breaking", "live:", "live updates", "just in", "developing")
_STOP = {"after", "about", "says", "said", "with", "from", "that", "this", "will",
         "have", "over", "into", "amid", "more", "than", "what", "when", "their",
         "news", "live", "updates", "first", "could", "would", "they", "were"}


def _keywords(title):
    words = "".join(c.lower() if c.isalnum() else " " for c in title).split()
    return {w for w in words if len(w) >= 4 and w not in _STOP}


def _names(title):
    """Capitalized words past the first (roughly: the proper nouns)."""
    words = "".join(c if c.isalnum() else " " for c in title).split()[1:]
    return {w.lower() for w in words if w[:1].isupper() and len(w) >= 3} - _STOP


def news_items(now=None):
    """(breaking, top) from NEWS_FEEDS.

    top: NEWS_TOP stories, each outlet's top stories taken in turn so
    no outlet dominates, skipping stories already listed. breaking: at most NEWS_BREAKING_MAX stories from
    the last NEWS_BREAKING_MINUTES that the outlet flags breaking/live or
    that 3+ outlets carry (titles sharing 3+ keywords, 2 of them names),
    newest first, one per outlet and one per story."""
    now = now or time.time()
    feeds = []
    for url, items in zip(NEWS_FEEDS, _fetch_feeds(NEWS_FEEDS)):
        host = urlparse(url).netloc
        src = NEWS_SOURCE_NAMES.get(host)
        feeds.append([dict(it, source=src or it.get("source") or host) for it in items])
    keyed = [(it, (_keywords(it["title"]), _names(it["title"])))
             for items in feeds for it in items]

    def same_story(a, b):
        return len(a[0] & b[0]) >= 3 and len(a[1] & b[1]) >= 2

    def outlets_carrying(kw):
        return {o["source"] for o, okw in keyed if same_story(kw, okw)}

    breaking, used, used_src, stories = [], set(), set(), []
    fresh = sorted(((it, kw) for it, kw in keyed if it.get("published")
                    and 0 <= now - it["published"] <= NEWS_BREAKING_MINUTES * 60),
                   key=lambda x: -x[0]["published"])
    for it, kw in fresh:
        if len(breaking) >= NEWS_BREAKING_MAX:
            break
        if (it["source"] in used_src or it["url"] in used
                or any(same_story(kw, k) for k in stories)):
            continue
        flagged = any(w in it["title"].lower() for w in _BREAKING_WORDS)
        if flagged or len(outlets_carrying(kw) | {it["source"]}) >= 3:
            breaking.append(dict(it, breaking=True))
            used.add(it["url"])
            used_src.add(it["source"])
            stories.append(kw)
    kw_of = {id(it): kw for it, kw in keyed}
    top = []
    for rank in range(10):
        for items in feeds:
            if len(top) >= NEWS_TOP or rank >= len(items):
                continue
            it, kw = items[rank], kw_of[id(items[rank])]
            if it["url"] in used or any(same_story(kw, k) for k in stories):
                continue
            top.append(it)
            used.add(it["url"])
            stories.append(kw)
    return breaking, top


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


# ---- Models ----
class LLMError(Exception):
    """A model call failed: missing key, API error or timeout."""


def agent_model(agent_id):
    """What answers for an agent: its tier's model, or the app it lives in."""
    a = AGENTS[agent_id]
    return f"{a['home']}'s coach model" if a.get("home") else MODELS[a["tier"]]


def _garage_gym(method, body=None, timeout=None):
    """Call Garage Gym's /api/hub; marks James as seen when it answers."""
    if not (GARAGE_GYM_URL and GARAGE_GYM_SECRET):
        raise LLMError("Garage Gym isn't linked: set GARAGE_GYM_URL and GARAGE_GYM_SECRET")
    req = urllib.request.Request(
        GARAGE_GYM_URL + "/api/hub",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {GARAGE_GYM_SECRET}",
                 "Content-Type": "application/json", "User-Agent": "bot-hub/1.0"},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout or LLM_TIMEOUT) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read()[:200].decode("utf-8", "replace")
        raise LLMError(f"Garage Gym returned {e.code}: {detail}")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise LLMError(f"Garage Gym unreachable: {e!r}")
    store().touch("james")
    return out


def james_chat(history):
    """Ask James in Garage Gym. Hub messages become his {question, history}
    pairs; changes he proposes need the app's Apply button."""
    turns, asked = [], None
    for m in history[:-1]:
        if m["role"] == "user":
            asked = m["content"]
        elif asked is not None:
            turns.append({"question": asked, "answer": m["content"]})
            asked = None
    out = _garage_gym("POST", {"question": history[-1]["content"], "history": turns})
    reply = out.get("answer") or "James didn't answer. Try again in a bit."
    n = out.get("proposedChanges") or 0
    if n:
        reply += (f"\n\n(James suggested {n} change{'s' if n != 1 else ''}. "
                  "Open Garage Gym to review and apply them.)")
    return reply


_JAMES_CACHE = {"at": 0.0, "ttl": 0, "value": None}


def james_summary(now=None):
    """James's training summary for the Fitness card, or None when Garage
    Gym isn't linked or didn't answer. Cached 5 min (1 min after a failure)."""
    now = now or time.time()
    if not (GARAGE_GYM_URL and GARAGE_GYM_SECRET):
        return None
    c = _JAMES_CACHE
    if now - c["at"] < c["ttl"]:
        return c["value"]
    try:
        value, ttl = _garage_gym("GET", timeout=8), 300
    except LLMError:
        value, ttl = None, 60
    c.update(at=now, ttl=ttl, value=value)
    return value


def system_prompt(agent_id):
    a = AGENTS[agent_id]
    team = ", ".join(f"{x['name']} ({TIER_LABELS[x['tier']]})" for x in AGENTS.values())
    stand_in = (f" The paid {MASTER_MODEL} model isn't connected yet, so you "
                "run on the low brain's model for now." if a["tier"] == "master" else "")
    persona = PERSONAS.get(agent_id, [])
    traits = [k for k in persona if k != "concise"]
    personality = f" Your personality: {', '.join(traits)}." if traits else ""
    brevity = " and be concise" if "concise" in persona else ""
    return (f"You are {a['name']}, the {TIER_LABELS[a['tier']]} of a personal bot "
            f"hub. {a['role']}{stand_in}{personality} The team: {team}. "
            f"Stay in character{brevity}.")


def provider_extra(provider, model):
    """Extra request fields for this provider and model (see *_REASONING_EFFORT)."""
    if provider == "gemini" and GEMINI_REASONING_EFFORT:
        return {"reasoning_effort": GEMINI_REASONING_EFFORT}
    if provider == "groq" and GROQ_REASONING_EFFORT and model.startswith("openai/gpt-oss"):
        return {"reasoning_effort": GROQ_REASONING_EFFORT}
    return {}


def list_models(provider):
    """Model ids this provider's key can use, or {"error": ...}. Providers
    retire models, so /api/models shows what to put in *_MODEL."""
    url, key_var = PROVIDERS[provider]
    key = os.environ.get(key_var, "")
    if not key:
        return {"error": f"{key_var} is not set"}
    req = urllib.request.Request(
        url.rsplit("/chat/completions", 1)[0] + "/models",
        headers={"Authorization": f"Bearer {key}", "User-Agent": "bot-hub/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read()).get("data", [])
    except urllib.error.HTTPError as e:
        return {"error": f"{provider} returned {e.code}"}
    except (urllib.error.URLError, TimeoutError, ValueError, AttributeError) as e:
        return {"error": f"{provider} call failed: {e!r}"}
    ids = (m.get("id", "") for m in data if isinstance(m, dict))
    return {"models": sorted(i.removeprefix("models/") for i in ids if i)}


def llm_chat(tier, messages, max_tokens=800):
    """One chat-completion call for `tier`; returns the reply text.
    Master is answered by the low brain until the paid model is wired."""
    provider, model = TIER_LLM["low_brain" if tier == "master" else tier]
    url, key_var = PROVIDERS[provider]
    key = os.environ.get(key_var, "")
    if not key:
        raise LLMError(f"{key_var} is not set in the project's env vars")
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens,
               **provider_extra(provider, model)}
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "User-Agent": "bot-hub/1.0"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
            out = json.loads(resp.read())
        text = out["choices"][0]["message"].get("content") or ""
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise LLMError(f"{provider} returned {e.code}: {detail}")
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, AttributeError) as e:
        raise LLMError(f"{provider} call failed: {e!r}")
    if not text.strip():
        raise LLMError(f"{model} returned an empty reply (it may have spent its "
                       "token budget thinking)")
    return text


def summarize(unprocessed):
    """One batched master-tier call over `unprocessed` (the low brain
    stands in for now). The batch is marked processed only on success."""
    if not unprocessed:
        return {"ok": True, "summary": "No new reports.", "unprocessed_count": 0}
    lines = "\n".join(
        f"- {display_name(r['bot_id'])} {r['event_type']}: {json.dumps(r['payload'])[:500]}"
        for r in unprocessed)
    try:
        text = llm_chat("master", [
            {"role": "system", "content": system_prompt("theta")},
            {"role": "user", "content": "Summarize these bot reports; flag anything "
             "that needs action:\n" + lines}])
    except LLMError as e:
        return {"ok": False, "error": str(e), "unprocessed_count": len(unprocessed)}
    store().mark_processed([r["id"] for r in unprocessed])
    n = len(unprocessed)
    store().add_chat("theta", f"Summary of {n} new report{'s' if n != 1 else ''}:\n{text}")
    return {"ok": True, "summary": text, "model": MODELS["master"],
            "unprocessed_count": len(unprocessed)}


def master_work(escalation):
    """The Master's work queue hook: work an escalation that reached
    master (the low brain stands in until the paid model is wired)."""
    try:
        text = llm_chat("master", [
            {"role": "system", "content": system_prompt("theta")},
            {"role": "user", "content": "Work this escalation and say what to do:\n"
             + json.dumps(escalation)}])
    except LLMError as e:
        return {"ok": False, "error": str(e), "escalation": escalation}
    return {"ok": True, "result": text, "model": MODELS["master"],
            "escalation": escalation}


# ---- All Agents chat: one shared thread for you and the bots. Bots post
# with their own key; your @mentions get one reply from each agent named
# (up to ALLCHAT_MENTIONS). Replies never trigger further replies, so
# agents can't run up each other's API limits in a loop.
def chat_name(sender):
    return {"you": "You", "hub": "Hub"}.get(sender) or display_name(sender)


def chat_line(m):
    """One thread entry as plain text, for model context."""
    if m.get("kind") == "event":
        return f"[event] {m['text']}"
    return f"{chat_name(m['from'])}: {m['text']}"


def post_event(sender, text):
    """A templated All Agents line for something an agent did. No tokens."""
    store().add_chat(sender, text[:500], kind="event")


def _gist(payload):
    if isinstance(payload, dict) and payload.get("title"):
        return str(payload["title"])[:120]
    text = json.dumps(payload)
    return text if len(text) <= 120 else text[:117] + "..."


def mentioned_agents(text):
    """Agent ids @mentioned in `text` (by id or name), in order, deduped."""
    names = {a: a for a in AGENTS} | {v["name"].lower(): a for a, v in AGENTS.items()}
    out = []
    for word in text.split():
        if word.startswith("@"):
            a = names.get(word[1:].strip(".,!?:;").lower())
            if a and a not in out:
                out.append(a)
    return out[:ALLCHAT_MENTIONS]


def allchat_reply(agent, thread):
    """One agent's reply to the latest message, with the thread as context."""
    if agent == "james":  # Garage Gym takes a single question
        return james_chat([{"role": "user", "content": thread[-1]["text"]}])
    transcript = "\n".join(chat_line(m) for m in thread[-CHAT_HISTORY:])
    name = AGENTS[agent]["name"]
    return llm_chat(AGENTS[agent]["tier"], [
        {"role": "system", "content": system_prompt(agent) + " You're in the All Agents "
         "group chat with the user and the other agents."},
        {"role": "user", "content": f"The chat so far:\n{transcript}\n\nReply to the latest "
         f"message as {name}. Write only your message, without your name in front."}])


def pick_responders(thread):
    """Mistral triages a message nobody was @mentioned in: which agents
    should answer it. Always at least one (Mistral herself when nothing
    fits), at most ALLCHAT_AUTO_MAX."""
    candidates = list(AGENTS)
    roster = "\n".join(f"- {a}: {AGENTS[a]['name']} ({TIER_LABELS[AGENTS[a]['tier']]}). "
                       f"{AGENTS[a]['role']}" for a in candidates)
    transcript = "\n".join(chat_line(m) for m in thread[-10:])
    reply = llm_chat("low_brain", [
        {"role": "system", "content": system_prompt("mistral")},
        {"role": "user", "content": "You route messages in the All Agents chat. Agents:\n"
         f"{roster}\n\nThe chat so far:\n{transcript}\n\nWhich agents should answer the "
         f"latest message? Pick 1 to {ALLCHAT_AUTO_MAX} whose job fits it best; for small "
         "talk pick just yourself (mistral). Answer with agent ids separated by commas, "
         "nothing else."}], max_tokens=300)
    words = "".join(c if c.isalpha() else " " for c in reply.lower()).split()
    picks = []
    for w in words:
        if w in candidates and w not in picks:
            picks.append(w)
    return picks[:ALLCHAT_AUTO_MAX] or ["mistral"]


def allchat_view(limit=50):
    return [dict(m, name=chat_name(m["from"])) for m in store().list_chat(limit)]


# ---- Rounds: each agent's own job, run on a schedule (Supabase Cron ->
# /api/round). Jobs post real results to All Agents; agents without a data
# source yet say so instead of inventing work.
def _seen(key):
    return json.loads(store().get_meta(key) or "[]")


def _mark_seen(key, url):
    store().set_meta(key, json.dumps(([url] + [u for u in _seen(key) if u != url])[:50]))


def _round_theta(ctx):
    unprocessed = store().unprocessed_reports(50)
    if not unprocessed:
        return "nothing new to summarize"
    r = summarize(unprocessed)
    if not r["ok"]:
        raise LLMError(r["error"])
    n = r["unprocessed_count"]
    return f"summarized {n} report{'s' if n != 1 else ''}"


def _round_mistral(ctx):
    problems = sorted(f"{r['name']}: {r['note']}" for r in wiring() if r["state"] != "ok")
    sig = "|".join(problems)
    if sig == store().get_meta("round:mistral:wiring"):  # None on the first check: report it
        return "wiring unchanged"
    store().set_meta("round:mistral:wiring", sig)
    store().add_chat("mistral", "Wiring check: everyone is wired." if not problems else
                     "Wiring check found problems:\n" + "\n".join(f"- {x}" for x in problems))
    return "posted a wiring check"


def _round_news(agent):
    def job(ctx):
        story = ctx.get("story")
        if not story:
            return "no new headlines"
        take = llm_chat(AGENTS[agent]["tier"], [
            {"role": "system", "content": system_prompt(agent) + " You're posting in the All "
             "Agents group chat."},
            {"role": "user", "content": f"Today's top story ({story['source']}): {story['title']}\n"
             "Give your take in 2-3 sentences. You only have the headline: say so instead of "
             "guessing details."}])
        store().add_chat(agent, f"{take.strip()}\n{story['url']}")
        return f"posted a take on \"{story['title'][:60]}\""
    return job


def _round_lenz(ctx):
    item = next((i for i in widget_items(ENTERTAINMENT_FEEDS)
                 if i["url"] not in _seen("round:lenz:seen")), None)
    if not item:
        return "nothing new in the feeds"
    pitch = llm_chat("miner", [
        {"role": "system", "content": system_prompt("lenz") + " You're posting in the All "
         "Agents group chat."},
        {"role": "user", "content": f"New in the feeds ({item['source']}): {item['title']}\n"
         "In 1-2 sentences, say why it might be worth a look. You only have the title: "
         "don't invent details."}])
    store().add_chat("lenz", f"{pitch.strip()}\n{item['url']}")
    _mark_seen("round:lenz:seen", item["url"])
    return f"pitched \"{item['title'][:60]}\""


def _round_james(ctx):
    if not GARAGE_GYM_SECRET:
        return "not linked to Garage Gym"
    _JAMES_CACHE.update(ttl=0)  # a round always asks for fresh numbers
    summary = james_summary()
    if not summary:
        raise LLMError("Garage Gym didn't answer")
    digest = hashlib.sha256((summary.get("summary") or "").encode()).hexdigest()
    if digest == store().get_meta("round:james:summary"):
        return "training unchanged"
    store().set_meta("round:james:summary", digest)
    post_event("james", "James checked your training: new numbers on the Fitness card.")
    return "updated your training summary"


ROUND_JOBS = {
    "theta": _round_theta, "mistral": _round_mistral, "james": _round_james,
    "lenz": _round_lenz, "red": _round_news("red"), "blue": _round_news("blue"),
    "gray": _round_news("gray"),
}
_NEWS_AGENTS = {"red", "blue", "gray"}


def run_round(force=False, now=None):
    """Run every agent's job that is due (or all, with force), in parallel,
    and post one Hub line saying what each did."""
    now = now or time.time()
    st = store()
    last = json.loads(st.get_meta("round:last") or "{}")
    due = [a for a in ROUND_JOBS if force or now - last.get(a, 0) >= ROUND_MIN_GAP]
    ctx = {}
    if _NEWS_AGENTS & set(due):  # the news miners all take the same new story
        breaking, top = news_items()
        ctx["story"] = next((i for i in breaking + top if i["url"] not in _seen("round:news:seen")), None)

    def run(a):
        try:
            return a, ROUND_JOBS[a](ctx), None
        except (LLMError, ValueError, KeyError) as e:
            return a, None, str(e)[:160]
    results = {}
    with ThreadPoolExecutor(max_workers=max(1, len(due))) as ex:
        for a, done, err in ex.map(run, due):
            results[a] = {"ok": err is None, "did": done or err}
            if err is None:
                last[a] = now
                st.touch(a, done[:80])
    st.set_meta("round:last", json.dumps(last))
    if ctx.get("story") and any(results.get(a, {}).get("ok") for a in _NEWS_AGENTS):
        _mark_seen("round:news:seen", ctx["story"]["url"])
    parts = [f"{AGENTS[a]['name']}: {r['did']}" if r["ok"] else f"{AGENTS[a]['name']}: failed ({r['did']})"
             for a, r in results.items()]
    idle = [AGENTS[a]["name"] for a in AGENTS if a not in ROUND_JOBS]
    if idle:
        parts.append(f"{', '.join(idle)}: no job yet")
    if results:
        post_event("hub", "Round: " + "; ".join(parts) + ".")
    return {"ok": True, "ran": results,
            "skipped": [a for a in ROUND_JOBS if a not in due], "no_job": idle}


# ---- Wiring: is each agent's model actually reachable?
def wiring():
    """Per agent: what answers for it and whether it's wired in. Checks the
    key and that the key can use the model; costs no tokens."""
    models = {p: list_models(p) for p in {p for p, _ in TIER_LLM.values()}}
    rows = []
    for aid, a in AGENTS.items():
        row = {"agent": aid, "name": a["name"], "tier": TIER_LABELS[a["tier"]],
               "model": agent_model(aid)}
        if a.get("home"):
            if not GARAGE_GYM_SECRET:
                row.update(state="off", note="Not linked: set GARAGE_GYM_SECRET")
            elif james_summary():
                row.update(state="ok", note="Garage Gym answered")
            else:
                row.update(state="bad", note="Garage Gym didn't answer: check GARAGE_GYM_URL "
                           "and that HUB_SECRET there matches GARAGE_GYM_SECRET here")
        else:
            provider, model = TIER_LLM["low_brain" if a["tier"] == "master" else a["tier"]]
            found = models[provider]
            if "error" in found:
                missing = found["error"].endswith("is not set")
                row.update(state="off" if missing else "bad", note=found["error"])
            elif model not in found["models"]:
                row.update(state="bad", note=f"{model} isn't available to this key; "
                           "pick one from /api/models")
            else:
                row.update(state="ok", note="Key set and model available"
                           + (f" ({MASTER_MODEL} not connected; standing in)" if a["tier"] == "master" else ""))
        rows.append(row)
    return rows


# ---- Core request handling (framework-free, so Vercel and the local
# test server both just call handle()) ----
def _json(status, obj):
    return status, "application/json", json.dumps(obj).encode()


def _auth_bot(bot_id, headers):
    """True if the bot's key matches; also marks the bot as seen (online)."""
    ok = bool(bot_id and BOT_KEYS.get(bot_id)
              and headers.get("x-bot-key") == BOT_KEYS[bot_id])
    if ok:
        store().touch(bot_id)
    return ok


def agent_statuses(now=None):
    """Every agent and configured bot: tier, model, online and activity.
    Online means it called the hub in the last AGENT_ONLINE_SECONDS."""
    now = now or time.time()
    status = store().list_status()
    extra = sorted((set(BOT_KEYS) | set(BOT_ROLES) | set(status)) - set(AGENTS))
    out = []
    for bot_id in list(AGENTS) + extra:
        tier = role_of(bot_id)
        st = status.get(bot_id)
        online = bool(st and now - st["seen"] <= AGENT_ONLINE_SECONDS)
        out.append({
            "bot_id": bot_id, "name": display_name(bot_id), "role": tier,
            "tier": TIER_LABELS[tier], "online": online,
            "model": agent_model(bot_id) if bot_id in AGENTS else MODELS[tier],
            "activity": ((st["activity"] or "online") if online else
                         f"idle, last active {datetime.fromtimestamp(st['seen'], timezone.utc):%b %d %H:%M} UTC"
                         if st else "offline"),
            "last_seen": (datetime.fromtimestamp(st["seen"], timezone.utc)
                          .strftime("%Y-%m-%d %H:%M:%S") if st else None),
        })
    out.sort(key=lambda a: -TIERS.index(a["role"]))
    return out


def _auth_dashboard(query, headers):
    if not DASHBOARD_KEY:
        return True
    return (headers.get("x-dashboard-key") == DASHBOARD_KEY
            or query.get("key", [None])[0] == DASHBOARD_KEY)


# Dashboard chat box. One-on-one history lives in the page only (one per
# agent) and posts to /api/chat; "All Agents" is the shared thread at
# /api/allchat, refreshed every 8 s while open. The Wiring panel below it
# reads /api/wiring and can send each agent a tiny test message.
_CHAT_JS = """
const key = new URLSearchParams(location.search).get("key") || "";
const H = {"Content-Type": "application/json", "x-dashboard-key": key};
const ALL = "__all";
const hist = {};
let thread = [], poll = null;
const agentSel = document.getElementById("chat-agent"), log = document.getElementById("chat-log");
const msg = document.getElementById("chat-msg"), btn = document.getElementById("chat-send");
const status = document.getElementById("chat-status");
function line(who, text) {
  const p = document.createElement("p"), b = document.createElement("b");
  b.textContent = who + ": ";
  p.style.whiteSpace = "pre-wrap";
  p.append(b, text);
  return p;
}
function eventLine(text) {
  const p = document.createElement("p");
  p.style.cssText = "white-space:pre-wrap;color:#666;font-style:italic;font-size:0.9em";
  p.textContent = "\u2022 " + text;
  return p;
}
function show() {
  if (agentSel.value === ALL) {
    log.replaceChildren(...thread.map(m => m.kind === "event" ? eventLine(m.text) : line(m.name, m.text)));
    return;
  }
  const name = agentSel.selectedOptions[0].dataset.name;
  log.replaceChildren(...(hist[agentSel.value] || []).map(m => line(m.role === "user" ? "You" : name, m.content)));
}
async function loadThread() {
  try {
    const d = await (await fetch("/api/allchat", {headers: H})).json();
    if (d.ok) { thread = d.messages; if (agentSel.value === ALL) show(); }
  } catch (err) {}
}
function onAgent() {
  status.textContent = "";
  clearInterval(poll); poll = null;
  if (agentSel.value === ALL) {
    msg.placeholder = "Message everyone. @mention agents (like @remi or @james) for a reply.";
    loadThread();
    poll = setInterval(() => { if (!document.hidden) loadThread(); }, 8000);
  } else {
    msg.placeholder = "";
  }
  show();
}
agentSel.onchange = onAgent;
document.getElementById("chat-form").onsubmit = async e => {
  e.preventDefault();
  const text = msg.value.trim(), agent = agentSel.value;
  if (!text) return;
  msg.value = ""; btn.disabled = true;
  if (agent === ALL) {
    status.textContent = "Waiting for replies...";
    thread = [...thread, {name: "You", text}];
    show();
    try {
      const d = await (await fetch("/api/allchat", {method: "POST", headers: H, body: JSON.stringify({text})})).json();
      if (!d.ok) throw new Error(d.error);
      thread = d.messages;
      const errs = Object.entries(d.errors || {}).map(([n, m]) => n + " couldn't reply: " + m);
      const routed = (d.routed || []).length ? "Mistral passed this to " + d.routed.join(" and ") + "." : "";
      status.textContent = [routed, ...errs].filter(Boolean).join(" | ");
    } catch (err) {
      thread = thread.slice(0, -1); msg.value = text;
      status.textContent = "Error: " + err.message;
    }
    btn.disabled = false;
    show();
    return;
  }
  const h = hist[agent] = hist[agent] || [];
  h.push({role: "user", content: text});
  status.textContent = "Thinking...";
  show();
  try {
    const r = await fetch("/api/chat", {method: "POST", headers: H, body: JSON.stringify({agent, messages: h})});
    const d = await r.json();
    if (!d.ok) throw new Error(d.error);
    h.push({role: "assistant", content: d.reply});
    status.textContent = "";
  } catch (err) {
    h.pop(); msg.value = text;
    status.textContent = "Error: " + err.message;
  }
  btn.disabled = false;
  show();
};
onAgent();

const wiringBody = document.getElementById("wiring-rows");
const MARK = {ok: ["Wired", "#1a7f37"], bad: ["Not wired", "#b3261e"], off: ["Not set up", "#8a6d00"]};
function cell(text, style) {
  const td = document.createElement("td");
  td.textContent = text;
  if (style) td.style.cssText = style;
  return td;
}
async function loadWiring() {
  const note = document.getElementById("wiring-note");
  note.textContent = "Checking...";
  try {
    const d = await (await fetch("/api/wiring", {headers: H})).json();
    if (!d.ok) throw new Error(d.error);
    wiringBody.replaceChildren(...d.agents.map(a => {
      const tr = document.createElement("tr");
      const [label, color] = MARK[a.state] || ["Unknown", "#888"];
      const result = cell(a.note, "color:#666");
      const test = document.createElement("td");
      const b = document.createElement("button");
      b.type = "button"; b.textContent = "Test";
      b.onclick = () => testAgent(a.agent, result, b);
      test.append(b);
      tr.append(cell(a.name), cell(a.model, "font-family:monospace;font-size:0.85em"),
                cell(label, "font-weight:bold;color:" + color), result, test);
      return tr;
    }));
    note.textContent = "Checked " + new Date().toLocaleTimeString() + ". Test sends a tiny message and uses a few tokens.";
  } catch (err) {
    note.textContent = "Couldn't check wiring: " + err.message;
  }
}
async function testAgent(agent, out, b) {
  b.disabled = true; out.textContent = "Testing...";
  const t0 = performance.now();
  try {
    const d = await (await fetch("/api/chat", {method: "POST", headers: H, body: JSON.stringify(
      {agent, messages: [{role: "user", content: "Wiring test: reply with just OK."}]})})).json();
    const secs = ((performance.now() - t0) / 1000).toFixed(1);
    if (!d.ok) throw new Error(d.error);
    out.textContent = "Replied in " + secs + " s: " + d.reply.slice(0, 80);
    out.style.color = "#1a7f37";
  } catch (err) {
    out.textContent = "Failed: " + err.message;
    out.style.color = "#b3261e";
  }
  b.disabled = false;
}
document.getElementById("wiring-recheck").onclick = loadWiring;
const roundBtn = document.getElementById("run-round");
if (roundBtn) roundBtn.onclick = async () => {
  const out = document.getElementById("round-status");
  roundBtn.disabled = true; out.textContent = "Running every agent's job...";
  try {
    const d = await (await fetch("/api/round", {method: "POST", headers: H, body: JSON.stringify({force: true})})).json();
    if (!d.ok) throw new Error(d.error);
    out.textContent = "Done. See All Agents for what each did.";
    loadThread();
  } catch (err) {
    out.textContent = "Round failed: " + err.message;
  }
  roundBtn.disabled = false;
};
loadWiring();
"""


def _chat_html():
    groups = ['<option value="__all" data-name="All Agents">All Agents (shared chat)</option>']
    for tier in reversed(TIERS):  # High Brain first
        opts = "".join(
            f"<option value=\"{a}\" data-name=\"{html.escape(v['name'])}\">"
            f"{html.escape(v['name'])}{' (' + html.escape(v['home']) + ')' if v.get('home') else ''}</option>"
            for a, v in AGENTS.items() if v["tier"] == tier)
        if opts:
            groups.append(f"<optgroup label=\"{TIER_LABELS[tier]} — "
                          f"{html.escape(MODELS[tier])}\">{opts}</optgroup>")
    return (f"<p><select id=\"chat-agent\" style=\"max-width:100%\">{''.join(groups)}</select></p>"
            "<div id=\"chat-log\"></div>"
            "<form id=\"chat-form\"><textarea id=\"chat-msg\" rows=\"3\" "
            "style=\"width:100%\"></textarea><br><button id=\"chat-send\">Send</button> "
            "<i id=\"chat-status\"></i></form>"
            "<h3>Wiring</h3><div style=\"overflow-x:auto\"><table style=\"border-collapse:collapse\" "
            "cellpadding=\"4\"><thead><tr><th align=\"left\">Agent</th><th align=\"left\">Model</th>"
            "<th align=\"left\">Status</th><th align=\"left\">Details</th><th></th></tr></thead>"
            "<tbody id=\"wiring-rows\"></tbody></table></div>"
            "<p><button id=\"wiring-recheck\" type=\"button\">Recheck</button> "
            "<i id=\"wiring-note\"></i></p>"
            f"<script>{_CHAT_JS}</script>")


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
            post_event(bot_id, f"{display_name(bot_id)} reported {event_type}: "
                               f"{_gist(data.get('payload', {}))}")
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
            post_event(bot_id, f"{display_name(bot_id)} escalated #{esc_id} to the "
                               f"{TIER_LABELS[to_role]}: {str(issue)[:200]}")
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
            post_event(bot_id, f"{display_name(bot_id)} issued order #{order_id}: {str(request)[:200]}")
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
            post_event(bot_id, f"{display_name(bot_id)} acknowledged order #{order_id}")
            return _json(200, {"ok": True, "order_id": order_id, "acked_by": acked})

        if path == "/api/fitness":
            bot_id, summary = data.get("bot_id"), data.get("summary")
            if not bot_id or not isinstance(summary, dict) or not _auth_bot(bot_id, headers):
                return _json(401, {"ok": False, "error": "bad bot_id, key or summary"})
            store().add_fitness(bot_id, summary)
            post_event(bot_id, f"{display_name(bot_id)} posted a fitness summary")
            return _json(200, {"ok": True})

        if path == "/api/summary":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            result = summarize(store().unprocessed_reports(50))
            return _json(200 if result["ok"] else 502, result)

        if path == "/api/chat":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            agent, msgs = data.get("agent"), data.get("messages")
            if agent not in AGENTS:
                return _json(400, {"ok": False, "error": "unknown agent"})
            if not isinstance(msgs, list) or not msgs:
                return _json(400, {"ok": False, "error": "messages must be a non-empty list"})
            history = []
            for m in msgs[-CHAT_HISTORY:]:
                if (not isinstance(m, dict) or m.get("role") not in ("user", "assistant")
                        or not isinstance(m.get("content"), str)):
                    return _json(400, {"ok": False, "error": "bad message"})
                history.append({"role": m["role"], "content": m["content"][:4000]})
            if history[-1]["role"] != "user":
                return _json(400, {"ok": False, "error": "last message must be from user"})
            try:
                if agent == "james":
                    reply = james_chat(history)
                else:
                    reply = llm_chat(AGENTS[agent]["tier"],
                                     [{"role": "system", "content": system_prompt(agent)}] + history)
            except LLMError as e:
                return _json(502, {"ok": False, "error": str(e)})
            return _json(200, {"ok": True, "agent": agent, "name": AGENTS[agent]["name"],
                               "model": agent_model(agent), "reply": reply})

        if path == "/api/allchat":
            text, bot_id = data.get("text"), data.get("bot_id")
            if not isinstance(text, str) or not text.strip():
                return _json(400, {"ok": False, "error": "text required"})
            if bot_id:  # a bot posting: no replies, so agents can't loop
                if not _auth_bot(bot_id, headers):
                    return _json(401, {"ok": False, "error": "bad bot_id or key"})
                store().add_chat(bot_id, text.strip()[:2000])
                return _json(200, {"ok": True, "messages": allchat_view()})
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            st = store()
            st.add_chat("you", text.strip()[:2000])
            thread = st.list_chat(CHAT_HISTORY)
            agents = mentioned_agents(text)
            errors, routed = {}, []
            if not agents and ALLCHAT_AUTO:
                try:
                    agents = routed = pick_responders(thread)
                except LLMError as e:
                    errors["Mistral (picking who answers)"] = str(e)

            def answer(a):
                try:
                    return a, allchat_reply(a, thread), None
                except LLMError as e:
                    return a, None, str(e)
            if agents:
                with ThreadPoolExecutor(max_workers=len(agents)) as ex:
                    for a, reply, err in ex.map(answer, agents):
                        if reply:
                            st.add_chat(a, reply.strip()[:4000])
                        else:
                            errors[AGENTS[a]["name"]] = err
            return _json(200, {"ok": True, "messages": allchat_view(), "errors": errors,
                               "routed": [AGENTS[a]["name"] for a in routed]})

        if path == "/api/status":
            bot_id, activity = data.get("bot_id"), data.get("activity")
            if not isinstance(activity, str) or not activity.strip():
                return _json(400, {"ok": False, "error": "activity required, e.g. \"researching\""})
            if not bot_id or not _auth_bot(bot_id, headers):
                return _json(401, {"ok": False, "error": "bad bot_id or key"})
            st = store()
            before = st.list_status().get(bot_id, {}).get("activity")
            st.touch(bot_id, activity.strip()[:80])
            if before != activity.strip()[:80]:
                post_event(bot_id, f"{display_name(bot_id)} is now {activity.strip()[:80]}")
            return _json(200, {"ok": True})

        if path == "/api/round":
            cron = bool(CRON_SECRET) and headers.get("authorization") == f"Bearer {CRON_SECRET}"
            if not (cron or (DASHBOARD_KEY and _auth_dashboard(query, headers))):
                return _json(401, {"ok": False, "error": "CRON_SECRET or dashboard key required"})
            return _json(200, run_round(force=bool(data.get("force"))))

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
        james = james_summary()  # before agent_statuses: an answer marks James online

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
        breaking, top = news_items()
        news_html = (f"<h3>Breaking</h3><ul>{_render_list(breaking)}</ul>" if breaking else "")
        news_html += ("<h3>Top stories</h3>" if breaking else "") + (
            f"<ul>{_render_list(top) or '<li>No headlines right now.</li>'}</ul>")
        from_bots = _render_list(pushed_items("news"))
        if from_bots:
            news_html += f"<h3>From your bots</h3><ul>{from_bots}</ul>"
        round_btn = ("<p><button id=\"run-round\" type=\"button\">Run a round now</button> "
                     "<i id=\"round-status\"></i></p>")
        agent_items = "".join(
            f"<li><span style=\"color:{'#1a7f37' if a['online'] else '#888'}\">●</span> "
            f"<b>{html.escape(a['name'])}</b> — {a['tier']} · {html.escape(a['activity'])}</li>"
            for a in agent_statuses())
        if james:
            james_html = (f"<p><b>{html.escape(james.get('coach') or 'James')}</b>'s summary</p>"
                          f"<div style=\"white-space:pre-wrap\">{html.escape(james.get('summary') or '')}</div>")
        elif GARAGE_GYM_SECRET:
            james_html = ("<p>Garage Gym didn't answer. Check GARAGE_GYM_URL, and that "
                          "HUB_SECRET there matches GARAGE_GYM_SECRET here.</p>")
        else:
            james_html = ""
        if fit:
            fit_html = james_html + "<ul>" + "".join(
                f"<li><b>{html.escape(str(k))}:</b> {html.escape(str(v))}</li>"
                for k, v in fit["summary"].items()
            ) + f"</ul><i>from {html.escape(display_name(fit['bot_id']))} at {html.escape(fit['created_at'])}</i>"
        elif james_html:
            fit_html = james_html
        else:
            fit_html = ("<p>No health summary yet. Link Garage Gym (GARAGE_GYM_URL and "
                        "GARAGE_GYM_SECRET) to show James's summary here.</p>")
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
            f"<h2>Agents</h2><ul style=\"list-style:none;padding-left:0\">{agent_items}</ul>{round_btn}"
            f"<h2>Chat</h2>{_chat_html()}"
            f"<h2>News</h2>{news_html}"
            f"<h2>Entertainment</h2><ul>{ent_items}</ul>"
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
        breaking, top = news_items()
        return _json(200, {
            "entertainment": (pushed_items("entertainment") + widget_items(ENTERTAINMENT_FEEDS))[:20],
            "news": breaking + top + pushed_items("news"),
            "fitness": fit_rows[0] if fit_rows else None,
            "james": james_summary(),
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
        for bot_id in list(AGENTS) + sorted((set(BOT_KEYS) | set(BOT_ROLES)) - set(AGENTS)):
            bots.append({"bot_id": bot_id, "name": display_name(bot_id), "role": role_of(bot_id),
                         "model": agent_model(bot_id) if bot_id in AGENTS else MODELS[role_of(bot_id)]})
        return _json(200, bots)

    if path == "/api/agents":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, agent_statuses())

    if path == "/api/allchat":
        bot_id = query.get("bot_id", [None])[0]
        if not (_auth_dashboard(query, headers) if not bot_id else _auth_bot(bot_id, headers)):
            return _json(401, {"ok": False, "error": "dashboard key or bot key required"})
        return _json(200, {"ok": True, "messages": allchat_view()})

    if path == "/api/wiring":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, {"ok": True, "agents": wiring()})

    if path == "/api/models":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, {
            "in_use": {t: f"{p}: {m}" for t, (p, m) in TIER_LLM.items()},
            **{p: list_models(p) for p in PROVIDERS},
        })

    if path == "/api/tiers":
        return _json(200, {
            "tiers": TIERS,
            "models": {t: (MODELS[t] or "unset") for t in TIERS},
        })

    return _json(404, {"ok": False, "error": "unknown route"})


# ---- WSGI entry point (what Vercel calls) ----
_REASONS = {200: "OK", 400: "Bad Request", 401: "Unauthorized",
            403: "Forbidden", 404: "Not Found", 500: "Internal Server Error",
            502: "Bad Gateway"}


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
