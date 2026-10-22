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
import csv
import hashlib
import html
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
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

# What each agent can actually do. Goes in every prompt, so agents
# acknowledge orders (and answer questions) honestly.
ABILITIES = {
    "theta": "summarize the bots' reports, decide escalations that reach you, issue commandeer "
             "orders, and write the weekly review",
    "mistral": "post the morning digest, flag breaking news, send phone notifications, triage "
               "escalations, check what's wired, and decide who answers in All Agents",
    "glass": "log expenses, report budgets and send budget alerts, review weekly spending, and "
             "import Rocket Money CSVs. You can't see bank accounts or block spending",
    "remi": "read the family calendar (read-only), post agendas, and remind people of birthdays. "
            "You can't add or change calendar events or text anyone, and Discord moderation "
            "isn't built yet",
    "lenz": "recommend from TMDB's trending list and the entertainment feeds",
    "red": "read your outlets' headlines and give your take on the top story. You can't search "
           "beyond those feeds", "blue": "read your outlets' headlines and give your take on the "
           "top story. You can't search beyond those feeds", "gray": "read your outlets' "
           "headlines and give your take on the top story. You can't search beyond those feeds",
    "charter": "draw charts of spending, daily spending, calendar busyness, news coverage and "
               "All Agents activity, and nothing else yet",
}


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
    "www.dailywire.com": "Daily Wire", "www.washingtonexaminer.com": "Washington Examiner",
    "www.nationalreview.com": "National Review", "www.theguardian.com": "Guardian US",
    "www.vox.com": "Vox", "www.motherjones.com": "Mother Jones",
    "www.newsnationnow.com": "NewsNation", "reason.com": "Reason",
}
# Each news miner's own outlets ({RED,BLUE,GRAY}_FEEDS override), so the
# three takes come from three different slices of the press.
SIDE_FEEDS = {
    "red": os.environ.get("RED_FEEDS", "https://moxie.foxnews.com/google-publisher/politics.xml,"
                          "https://nypost.com/news/feed/,https://www.dailywire.com/feeds/rss.xml,"
                          "https://www.washingtonexaminer.com/feed,https://www.nationalreview.com/feed/"),
    "blue": os.environ.get("BLUE_FEEDS", "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml,"
                           "https://feeds.npr.org/1014/rss.xml,https://www.theguardian.com/us-news/rss,"
                           "https://www.vox.com/rss/index.xml,https://www.motherjones.com/feed/"),
    "gray": os.environ.get("GRAY_FEEDS", "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml,"
                           "https://thehill.com/homenews/feed/,https://www.pbs.org/newshour/feeds/rss/politics,"
                           "https://www.newsnationnow.com/feed/,https://reason.com/feed/"),
}
SIDE_FEEDS = {k: [u.strip() for u in v.split(",") if u.strip()] for k, v in SIDE_FEEDS.items()}
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
TMDB_BASE = "https://api.themoviedb.org/3"
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
    if bot_id == "you":
        return "You"
    if bot_id in BOT_NAMES:
        return BOT_NAMES[bot_id]
    return AGENTS[bot_id]["name"] if bot_id in AGENTS else "@" + bot_id


def next_role(role):
    i = TIERS.index(role) if role in TIERS else 0
    return TIERS[min(i + 1, len(TIERS) - 1)]


ORDER_DAYS = int(os.environ.get("ORDER_DAYS", "7"))
_ORDERS_CACHE = {"at": 0.0, "items": []}


def order_live(order, now=None):
    """Active orders expire ORDER_DAYS after they're issued (older orders,
    saved before expiry existed, count from their created_at)."""
    exp = order.get("expires_at")
    if not exp:
        try:
            exp = datetime.strptime(order["created_at"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc).timestamp() + ORDER_DAYS * 86400
        except (KeyError, ValueError):
            return True
    return (now or time.time()) < float(exp)


def active_orders():
    """Active orders, cached briefly: every agent prompt reads them."""
    if time.time() - _ORDERS_CACHE["at"] > 10:
        _ORDERS_CACHE.update(at=time.time(), items=store().list_active_orders())
    return _ORDERS_CACHE["items"]


def orders_for(agent_id):
    return [o for o in active_orders() if not o.get("targets") or agent_id in o["targets"]]


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

    def add_chat(self, sender, text, kind="message", image=None):
        item = {"id": self._next_id(), "from": sender, "text": text, "kind": kind, "at": _now()}
        if image:
            item["image"] = image
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

    def add_chat(self, sender, text, kind="message", image=None):
        item = {"id": self._next_id(), "from": sender, "text": text, "kind": kind, "at": _now()}
        if image:
            item["image"] = image
        self._cmd("LPUSH", "hub:allchat", json.dumps(item))
        self._cmd("LTRIM", "hub:allchat", "0", str(ALLCHAT_KEEP - 1))
        return item

    def get_meta(self, key):
        return self._cmd("HGET", "hub:meta", key)

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


def _fetch_feeds_with(fn, urls):
    """fn(url) for each url, in parallel (one slow source doesn't hold up the rest)."""
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=min(10, len(urls))) as ex:
        return list(ex.map(fn, urls))


def _fetch_feeds(urls):
    return _fetch_feeds_with(feed_items, urls)


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


# ---- Lenz's TMDB link: trending movies and shows with real facts.
# TMDB_API_KEY takes either the v3 "API key" or the v4 "read access token".
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_NOTICE = "This product uses the TMDB API but is not endorsed or certified by TMDB."
_TMDB_CACHE = {"at": 0.0, "items": None}


def tmdb_trending():
    """This week's trending movies and shows ({title, kind, overview, date,
    rating, url}), cached 30 min. Raises LLMError when TMDB refuses."""
    if not TMDB_API_KEY:
        return []
    if _TMDB_CACHE["items"] is not None and time.time() - _TMDB_CACHE["at"] < 1800:
        return _TMDB_CACHE["items"]
    bearer = TMDB_API_KEY.startswith("eyJ")  # v4 tokens are JWTs
    url = TMDB_BASE + "/trending/all/week" + ("" if bearer else f"?api_key={TMDB_API_KEY}")
    headers = {"User-Agent": "bot-hub/1.0", "Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {TMDB_API_KEY}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=8) as resp:
            results = json.loads(resp.read()).get("results", [])
    except urllib.error.HTTPError as e:
        raise LLMError(f"TMDB returned {e.code}")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise LLMError(f"TMDB unreachable: {e!r}")
    items = []
    for r in results:
        kind = r.get("media_type")
        if kind not in ("movie", "tv") or not r.get("id"):
            continue
        items.append({
            "title": r.get("title") or r.get("name") or "?", "kind": "movie" if kind == "movie" else "TV show",
            "overview": (r.get("overview") or "")[:400], "date": r.get("release_date") or r.get("first_air_date") or "",
            "rating": round(float(r.get("vote_average") or 0), 1),
            "url": f"https://www.themoviedb.org/{kind}/{r['id']}"})
    _TMDB_CACHE.update(at=time.time(), items=items)
    return items


def tmdb_fact_line(it):
    bits = [it["kind"]] + ([f"released {it['date']}"] if it["date"] else []) \
        + ([f"rated {it['rating']}/10 on TMDB"] if it["rating"] else [])
    return f"{it['title']} ({', '.join(bits)})"


def story_key(title):
    return _keywords(title), _names(title)


def _same_story(a, b):
    """Two story_key()s describe the same story: 3+ shared keywords, 2 of them names."""
    return len(a[0] & b[0]) >= 3 and len(a[1] & b[1]) >= 2


def outlet_items(urls):
    """Every item from these feeds, each with a readable outlet name."""
    out = []
    for url, items in zip(urls, _fetch_feeds(urls)):
        host = urlparse(url).netloc
        out += [dict(it, source=NEWS_SOURCE_NAMES.get(host) or it.get("source") or host) for it in items]
    return out


def side_coverage(agent, title, limit=3):
    """How this news miner's own outlets covered a story (matching headlines)."""
    key = story_key(title)
    return [it for it in outlet_items(SIDE_FEEDS.get(agent, []))
            if _same_story(key, story_key(it["title"]))][:limit]


def side_headlines(agent, limit=8):
    """Each of the miner's outlets' latest headlines, in turn."""
    by_outlet = {}
    for it in outlet_items(SIDE_FEEDS.get(agent, [])):
        by_outlet.setdefault(it["source"], []).append(it)
    out = []
    for rank in range(10):
        for items in by_outlet.values():
            if len(out) < limit and rank < len(items):
                out.append(items[rank])
    return out


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

    same_story = _same_story

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
    extra = {"remi": remi_context, "glass": glass_context, "charter": charter_context}.get(agent_id, str)()
    if agent_id == "lenz":
        try:
            trending = tmdb_trending()[:10]
        except LLMError:
            trending = []
        charts = [i["title"] for i in widget_items(ENTERTAINMENT_FEEDS)[:8]]
        if trending or charts:
            extra = ("\n\nWhat's current (only these facts; say so rather than guess):"
                     + "".join(f"\n- Trending: {tmdb_fact_line(i)}" for i in trending)
                     + "".join(f"\n- In the feeds: {t}" for t in charts))
    if agent_id in SIDE_FEEDS:
        latest = side_headlines(agent_id)
        if latest:
            extra = ("\n\nLatest headlines from your outlets (you only know these headlines; "
                     "say so rather than guess details):\n"
                     + "\n".join(f"- {it['source']}: {it['title']}" for it in latest))
    can = f" What you can actually do: {ABILITIES[agent_id]}." if agent_id in ABILITIES else ""
    mine = orders_for(agent_id)
    if mine:
        extra += ("\n\nStanding orders from the user (follow them; if one asks for something "
                  "you can't do, say so plainly):\n" + "\n".join(
                      f"- #{o['id']}: {o['request']}" for o in mine))
    return (f"You are {a['name']}, the {TIER_LABELS[a['tier']]} of a personal bot "
            f"hub. {a['role']}{stand_in}{personality}{can} The team: {team}. "
            f"Stay in character{brevity}.{extra}")


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
    if agent == "glass" and thread[-1]["from"] == "you":
        parsed = parse_expense(thread[-1]["text"])
        if parsed:
            return glass_log_reply(parsed)
    text = thread[-1]["text"].lower()
    if agent == "charter" and ("@charter" in text or any(w in text for w in ("chart", "graph", "plot", "visual"))):
        chart = charter_reply(thread[-1]["text"])
        if chart:
            return chart  # (caption, image url): the caller posts it with the image
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


# ---- Remi's calendar: Google Calendar "secret address in iCal format"
# links (read-only), plus BIRTHDAYS. Times are shown in HUB_TIMEZONE.
HUB_TIMEZONE = os.environ.get("HUB_TIMEZONE", "America/Denver")
REMI_CALENDAR_URLS = [u.strip() for u in os.environ.get("REMI_CALENDAR_URLS", "").split(",") if u.strip()]
BIRTHDAYS = [p.split(":", 1) for p in os.environ.get("BIRTHDAYS", "").split(",") if ":" in p]
CALENDAR_CACHE_SECONDS = 600
_CAL_CACHE = {}  # url -> (fetched_at, events or None)
_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def hub_tz():
    try:
        return ZoneInfo(HUB_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def _ics_unescape(text):
    return (text.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\"))


def parse_ics(text):
    """VEVENTs as {NAME: (params, value)}; EXDATE collects every value."""
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]  # folded line
        else:
            lines.append(raw)
    events, cur = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = {"EXDATE": []}
        elif line == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, value = line.split(":", 1)
            name, *params = head.split(";")
            params = dict(x.split("=", 1) for x in params if "=" in x)
            if name == "EXDATE":
                cur["EXDATE"] += [(params, v) for v in value.split(",")]
            elif name not in cur:
                cur[name] = (params, value)
    return events


def _ics_time(params, value, tz):
    """(date or aware datetime in tz, all_day)."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or (len(value) == 8 and value.isdigit()):
        return date(int(value[:4]), int(value[4:6]), int(value[6:8])), True
    dt = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        zone = tz
        if params.get("TZID"):
            try:
                zone = ZoneInfo(params["TZID"].strip('"'))
            except (ZoneInfoNotFoundError, ValueError):
                pass  # e.g. a Windows zone name: assume the hub's
        dt = dt.replace(tzinfo=zone)
    return dt.astimezone(tz), False


def _nth_weekday(year, month, weekday, n):
    """The nth (1-based; negative counts from the end) weekday of a month, or None."""
    first = date(year, month, 1)
    days = [first + timedelta(d) for d in range(31)
            if (first + timedelta(d)).month == month and (first + timedelta(d)).weekday() == weekday]
    try:
        return days[n - 1] if n > 0 else days[n]
    except IndexError:
        return None


def _rrule_dates(first, rule, last_day):
    """Dates a recurring event starts on, from its first date up to last_day."""
    r = dict(x.split("=", 1) for x in rule.split(";") if "=" in x)
    freq, step = r.get("FREQ"), max(1, int(r.get("INTERVAL", "1") or 1))
    count = int(r["COUNT"]) if r.get("COUNT", "").isdigit() else None
    until = date(int(r["UNTIL"][:4]), int(r["UNTIL"][4:6]), int(r["UNTIL"][6:8])) if r.get("UNTIL") else None
    byday = [d.strip() for d in r.get("BYDAY", "").split(",") if d.strip()]
    stop = min(last_day, until) if until else last_day

    def candidates():
        if freq == "DAILY":
            d = first
            while True:
                yield d
                d += timedelta(days=step)
        elif freq == "WEEKLY":
            days = sorted({_WEEKDAYS[b[-2:]] for b in byday if b[-2:] in _WEEKDAYS} or {first.weekday()})
            week = first - timedelta(days=first.weekday())
            while True:
                for wd in days:
                    yield week + timedelta(days=wd)
                week += timedelta(weeks=step)
        elif freq == "MONTHLY":
            y, m = first.year, first.month
            while True:
                if byday and byday[0][-2:] in _WEEKDAYS and byday[0][:-2].lstrip("+-").isdigit():
                    d = _nth_weekday(y, m, _WEEKDAYS[byday[0][-2:]], int(byday[0][:-2]))
                else:
                    day = int(r.get("BYMONTHDAY", first.day))
                    try:
                        d = date(y, m, day)
                    except ValueError:
                        d = None
                if d:
                    yield d
                m += step
                y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
        elif freq == "YEARLY":
            y = first.year
            while True:
                try:
                    yield date(y, first.month, first.day)
                except ValueError:
                    pass  # Feb 29 in a non-leap year
                y += step
        else:
            yield first

    out, n = [], 0
    for d in candidates():
        if d < first:
            continue
        if d > stop or (count is not None and n >= count) or n > 3000:
            break
        n += 1
        out.append(d)
    return out


def _calendar_source(url):
    """Parsed events for one calendar, cached; None if it couldn't be read."""
    hit = _CAL_CACHE.get(url)
    if hit and time.time() - hit[0] < CALENDAR_CACHE_SECONDS:
        return hit[1]
    try:
        events = parse_ics(_fetch_url(url, timeout=8).decode("utf-8", "replace"))
    except Exception as e:  # a bad link shouldn't break the dashboard
        print(f"calendar fetch failed: {e!r}")
        events = None
    _CAL_CACHE[url] = (time.time(), events)
    return events


def calendar_events(first_day, last_day):
    """Every occurrence overlapping first_day..last_day (local dates), sorted:
    {title, location, start, end, all_day, birthday}. Timed starts/ends are
    aware datetimes in hub_tz(); all-day ones are dates (end exclusive)."""
    tz = hub_tz()
    occ = []
    sources = _fetch_feeds_with(_calendar_source, REMI_CALENDAR_URLS)
    for events in sources:
        if not events:
            continue
        overridden = set()
        for ev in events:
            if "RECURRENCE-ID" in ev and "UID" in ev:
                overridden.add((ev["UID"][1], _ics_time(*ev["RECURRENCE-ID"], tz)[0]))
        for ev in events:
            if "DTSTART" not in ev or ev.get("STATUS", ({}, ""))[1].upper() == "CANCELLED":
                continue
            start, all_day = _ics_time(*ev["DTSTART"], tz)
            if "DTEND" in ev:
                end = _ics_time(*ev["DTEND"], tz)[0]
            elif "DURATION" in ev and not all_day:
                dur = ev["DURATION"][1]
                h = int(dur.split("T")[1].split("H")[0]) if "H" in dur else 0
                mins = int(dur.split("H")[-1].split("M")[0].lstrip("PT")) if "M" in dur.split("T")[-1] else 0
                end = start + timedelta(hours=h, minutes=mins)
            else:
                end = start + timedelta(days=1) if all_day else start
            length = end - start
            title = _ics_unescape(ev.get("SUMMARY", ({}, "(no title)"))[1]).strip() or "(no title)"
            where = _ics_unescape(ev.get("LOCATION", ({}, ""))[1]).strip()
            first = start if all_day else start.date()
            if "RRULE" in ev and "RECURRENCE-ID" not in ev:
                skip = {_ics_time(p, v, tz)[0] for p, v in ev["EXDATE"]}
                starts = []
                for d in _rrule_dates(first, ev["RRULE"][1], last_day):
                    st = d if all_day else datetime.combine(d, start.time(), tzinfo=tz)
                    if st in skip or (ev.get("UID", ({}, ""))[1], st) in overridden:
                        continue
                    starts.append(st)
            else:
                starts = [start]
            for st in starts:
                en = st + length
                s_day = st if all_day else st.date()
                e_day = en if all_day else (en - timedelta(microseconds=1)).date() + timedelta(days=1)
                if s_day <= last_day and max(e_day, s_day + timedelta(days=1)) > first_day:
                    occ.append({"title": title, "location": where, "start": st, "end": en,
                                "all_day": all_day, "birthday": "birthday" in title.lower()})
    for name, md in BIRTHDAYS:
        try:
            month, day = (int(x) for x in md.strip().split("-"))
        except ValueError:
            continue
        for year in range(first_day.year, last_day.year + 1):
            try:
                d = date(year, month, day)
            except ValueError:
                continue
            if first_day <= d <= last_day:
                occ.append({"title": f"{name.strip()}'s birthday", "location": "", "start": d,
                            "end": d + timedelta(days=1), "all_day": True, "birthday": True})
    occ.sort(key=lambda o: (o["start"] if o["all_day"] else o["start"].date(),
                            0 if o["all_day"] else 1,
                            "" if o["all_day"] else o["start"].strftime("%H%M"), o["title"]))
    return occ


def calendar_linked():
    return bool(REMI_CALENDAR_URLS or BIRTHDAYS)


def calendar_problems():
    """Calendar links that couldn't be read last time (for wiring)."""
    return [i + 1 for i, u in enumerate(REMI_CALENDAR_URLS) if _calendar_source(u) is None]


def _clock(dt):
    return dt.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")


def occurrence_text(o, with_day=False):
    day = (o["start"] if o["all_day"] else o["start"].date()).strftime("%a %b %d ") if with_day else ""
    when = "All day" if o["all_day"] else f"{_clock(o['start'])}–{_clock(o['end'])}"
    return f"{day}{when}: {o['title']}" + (f" ({o['location']})" if o["location"] else "")


def remi_context():
    """The next 14 days, for Remi's prompt, so she answers from the real calendar."""
    if not calendar_linked():
        return ""
    today = datetime.now(hub_tz()).date()
    items = calendar_events(today, today + timedelta(days=13))
    listing = "\n".join(f"- {occurrence_text(o, with_day=True)}" for o in items[:60]) or "- nothing scheduled"
    return (f"\n\nToday is {today:%A %B %d}. The family calendar for the next 14 days "
            f"(exact; never change times or add events):\n{listing}")


# ---- Glass's ledger: expenses from chat ("@glass $42 groceries"), bots, or
# Rocket Money CSV exports, against monthly budgets (GLASS_BUDGETS
# "Groceries:600,Dining:200"). GLASS_CATEGORY_MAP renames categories
# ("Restaurants:Dining,Coffee:Dining"). Rocket Money has no public API.
def _pairs(env):
    return [(k.strip(), v.strip()) for k, v in (p.split(":", 1) for p in os.environ.get(env, "").split(",") if ":" in p)]


GLASS_BUDGETS = {}
for _k, _v in _pairs("GLASS_BUDGETS"):
    try:
        GLASS_BUDGETS[_k] = float(_v)
    except ValueError:
        pass
GLASS_CATEGORY_MAP = {k.lower(): v for k, v in _pairs("GLASS_CATEGORY_MAP")}
_SKIP_CATEGORIES = ("income", "paycheck", "transfer", "credit card payment", "loan payment", "refund")


def ledger_category(raw):
    """A budget category for a raw category name (map, then case-insensitive match)."""
    raw = (raw or "").strip()
    mapped = GLASS_CATEGORY_MAP.get(raw.lower(), raw)
    for name in GLASS_BUDGETS:
        if name.lower() == mapped.lower():
            return name
    return mapped or "Other"


def _expense(day, amount, category, note, source, salt=""):
    key = hashlib.sha1(f"{day}|{note.lower()}|{amount:.2f}|{source}|{salt}".encode()).hexdigest()[:16]
    return key, {"date": day.isoformat(), "amount": round(amount, 2), "category": ledger_category(category),
                 "note": note[:120], "source": source}


def add_expense(amount, category, note="", day=None, source="chat"):
    """Log one expense; returns the stored expense."""
    day = day or datetime.now(hub_tz()).date()
    # each entry gets its own id, so the same purchase logged twice counts twice
    key, exp = _expense(day, amount, category, note, source, salt=str(time.time_ns()))
    store().add_expenses(day.strftime("%Y-%m"), {key: exp})
    return exp


_AMOUNT = re.compile(r"\$\s?(\d{1,7}(?:,\d{3})*(?:\.\d{1,2})?)")


def parse_expense(text):
    """'@glass $42.50 groceries at Costco' -> (42.5, 'Groceries', 'groceries at Costco'), or None."""
    m = _AMOUNT.search(text)
    if not m:
        return None
    amount = float(m.group(1).replace(",", ""))
    rest = re.sub(r"@\w+", "", (text[:m.start()] + text[m.end():])).strip(" ,.-:")
    words = rest.lower()
    names = list(GLASS_BUDGETS) + [v for v in GLASS_CATEGORY_MAP.values()]
    category = next((n for n in names if n.lower() in words), None)
    if not category:
        category = next((v for k, v in GLASS_CATEGORY_MAP.items() if k in words), "Other")
    return amount, category, rest or category


def month_status(month=None):
    """{category: {"spent", "budget"}} for a month ("YYYY-MM"), budgets first."""
    month = month or datetime.now(hub_tz()).strftime("%Y-%m")
    out = {c: {"spent": 0.0, "budget": b} for c, b in GLASS_BUDGETS.items()}
    for e in store().list_expenses(month):
        out.setdefault(e["category"], {"spent": 0.0, "budget": None})["spent"] += e["amount"]
    return out


def status_lines(month=None):
    lines = []
    for cat, v in month_status(month).items():
        if v["budget"]:
            lines.append(f"{cat}: ${v['spent']:,.2f} of ${v['budget']:,.0f} ({v['spent'] / v['budget']:.0%})")
        elif v["spent"]:
            lines.append(f"{cat}: ${v['spent']:,.2f} (no budget)")
    return lines


def glass_log_reply(parsed):
    """Log a chat expense; Glass confirms with exact numbers (no model call)."""
    amount, category, note = parsed
    exp = add_expense(amount, category, note)
    v = month_status()[exp["category"]]
    tail = (f" {exp['category']} this month: ${v['spent']:,.2f} of ${v['budget']:,.0f}."
            if v["budget"] else f" {exp['category']} this month: ${v['spent']:,.2f} (no budget set).")
    return f"Logged ${amount:,.2f} for {exp['category']} ({note}).{tail}"


def _parse_day(text):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass
    return None


def import_csv(text):
    """Import a Rocket Money (or similar) transactions CSV. Columns are found
    by header; whether expenses are positive or negative is read from the
    file (most rows are spending). Income, transfers, card payments and
    rows marked ignored are skipped; re-importing is safe (deduped)."""
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    if not rows:
        return {"ok": False, "error": "no rows found"}
    cols = {c.strip().lower(): c for c in rows[0].keys() if c}

    def col(*names):
        return next((cols[n] for n in names if n in cols), None)
    c_date, c_amount = col("date", "transaction date", "original date"), col("amount")
    c_name, c_custom = col("name", "description", "merchant", "payee"), col("custom name")
    c_cat, c_ignored = col("category"), col("ignored from")
    if not (c_date and c_amount):
        return {"ok": False, "error": f"need Date and Amount columns; found {', '.join(cols.values())}"}
    parsed, skipped = [], {"income/transfers": 0, "ignored": 0, "unreadable": 0}
    for r in rows:
        day = _parse_day(r.get(c_date) or "")
        try:
            amount = float((r.get(c_amount) or "").replace("$", "").replace(",", ""))
        except ValueError:
            amount = None
        if day is None or amount is None:
            skipped["unreadable"] += 1
            continue
        cat = (r.get(c_cat) or "").strip() if c_cat else ""
        if c_ignored and (r.get(c_ignored) or "").strip():
            skipped["ignored"] += 1
            continue
        if any(k in cat.lower() for k in _SKIP_CATEGORIES):
            skipped["income/transfers"] += 1
            continue
        note = ((r.get(c_custom) or "").strip() if c_custom else "") or ((r.get(c_name) or "").strip() if c_name else "")
        parsed.append((day, amount, cat, note))
    positive = sum(1 for p in parsed if p[1] > 0)
    sign = 1 if positive >= len(parsed) - positive else -1  # spending is the majority
    by_month = {}
    for day, amount, cat, note in parsed:
        if amount * sign <= 0:
            skipped["income/transfers"] += 1  # money in, e.g. refunds
            continue
        key, exp = _expense(day, amount * sign, cat, note, "csv")
        by_month.setdefault(day.strftime("%Y-%m"), {})[key] = exp
    added = sum(store().add_expenses(m, rows_) for m, rows_ in by_month.items())
    total = sum(len(v) for v in by_month.values())
    return {"ok": True, "added": added, "duplicates": total - added, "skipped": skipped,
            "expenses_were": "positive" if sign > 0 else "negative",
            "columns": {k: v for k, v in {"date": c_date, "amount": c_amount, "name": c_custom or c_name,
                                          "category": c_cat}.items() if v},
            "months": sorted(by_month)}


def glass_context():
    month = datetime.now(hub_tz()).strftime("%Y-%m")
    lines = status_lines(month)
    recent = sorted(store().list_expenses(month), key=lambda e: e["date"])[-8:]
    if not (lines or recent):
        return "\n\nNo expenses logged this month yet. People log them with '@glass $42 groceries'."
    return (f"\n\nThis month ({month}) so far (exact; never invent numbers):\n"
            + "\n".join(f"- {x}" for x in lines)
            + ("\nRecent expenses:\n" + "\n".join(f"- {e['date']} ${e['amount']:,.2f} {e['category']}: {e['note']}"
                                                  for e in recent) if recent else ""))


# ---- Charter's charts: SVG drawn here from data the hub already has (no
# library, no tokens). Stored in meta as chart:<id>, served at /chart/<id>.svg;
# the newest CHART_KEEP are kept.
CHART_KEEP = 30


def _x(text):
    return html.escape(str(text), quote=True)


def bar_chart_svg(title, rows, money=False, limits=None):
    """Horizontal bars. rows: [(label, value)]; limits: {label: budget} draws
    a budget tick per row. Scale: 0 to the largest value or limit."""
    limits = limits or {}
    w, left, right, top, row_h = 640, 150, 90, 46, 30
    h = top + row_h * max(1, len(rows)) + 20
    biggest = max([v for _, v in rows] + [l for l in limits.values() if l] + [1])
    fmt = (lambda v: f"${v:,.0f}") if money else (lambda v: f"{v:,.0f}")
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
           f'font-family="system-ui,sans-serif" font-size="13">',
           f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
           f'<text x="16" y="28" font-size="16" font-weight="bold" fill="#17202b">{_x(title)}</text>']
    span = w - left - right
    for i, (label, value) in enumerate(rows):
        y = top + i * row_h
        bw = span * value / biggest
        limit = limits.get(label)
        color = "#b3261e" if limit and value > limit else "#2f5bd3"  # red only means over budget
        out.append(f'<text x="{left - 8}" y="{y + 18}" text-anchor="end" fill="#17202b">{_x(label)[:22]}</text>')
        if limit:  # light track up to the budget, so the bar and its label read as one row
            out.append(f'<rect x="{left}" y="{y + 5}" width="{span * limit / biggest:.1f}" height="18" fill="#e4e8ee"/>')
        out.append(f'<rect x="{left}" y="{y + 5}" width="{max(bw, 1):.1f}" height="18" fill="{color}"/>')
        if limit:
            lx = left + span * limit / biggest
            out.append(f'<line x1="{lx:.1f}" x2="{lx:.1f}" y1="{y + 1}" y2="{y + 27}" stroke="#17202b" stroke-width="2"/>')
        tail = fmt(value) + (f" of {fmt(limit)}" if limit else "")
        label_x = left + max(bw, span * limit / biggest if limit else 0, 1) + 6  # clear of the tick
        out.append(f'<text x="{label_x:.1f}" y="{y + 18}" fill="#5a6573">{_x(tail)}</text>')
    if not rows:
        out.append(f'<text x="{left}" y="{top + 18}" fill="#5a6573">No data yet</text>')
    out.append("</svg>")
    return "".join(out)


def column_chart_svg(title, cols, money=False):
    """Vertical bars over time. cols: [(label, value)], labels thinned to fit."""
    w, h, left, bottom, top = 640, 300, 56, 40, 46
    span_w, span_h = w - left - 16, h - top - bottom
    biggest = max([v for _, v in cols] + [1])
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
           f'font-family="system-ui,sans-serif" font-size="12">',
           f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
           f'<text x="16" y="28" font-size="16" font-weight="bold" fill="#17202b">{_x(title)}</text>']
    for frac in (0, 0.5, 1):
        y = top + span_h * (1 - frac)
        val = biggest * frac
        out.append(f'<line x1="{left}" x2="{w - 16}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e4e8ee"/>')
        out.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end" fill="#5a6573">'
                   f'{_x(f"${val:,.0f}" if money else f"{val:,.0f}")}</text>')
    n = max(1, len(cols))
    slot = span_w / n
    every = max(1, round(n / 10))
    for i, (label, value) in enumerate(cols):
        bh = span_h * value / biggest
        x = left + i * slot
        out.append(f'<rect x="{x + slot * 0.15:.1f}" y="{top + span_h - bh:.1f}" width="{slot * 0.7:.1f}" '
                   f'height="{bh:.1f}" fill="#2f5bd3"/>')
        if i % every == 0:
            out.append(f'<text x="{x + slot / 2:.1f}" y="{h - bottom + 16}" text-anchor="middle" fill="#5a6573">{_x(label)}</text>')
    out.append("</svg>")
    return "".join(out)


def _chart_spending(month=None):
    month = month or datetime.now(hub_tz()).strftime("%Y-%m")
    st = month_status(month)
    rows = sorted(((c, v["spent"]) for c, v in st.items() if v["spent"] or v["budget"]), key=lambda r: -r[1])
    over = [c for c, v in st.items() if v["budget"] and v["spent"] > v["budget"]]
    top_cat = rows[0] if rows and rows[0][1] else None
    caption = (f"Spending by category for {month}"
               + (f": {top_cat[0]} leads at ${top_cat[1]:,.2f}" if top_cat else ": nothing logged yet")
               + (f"; over budget: {', '.join(over)}" if over else "") + ".")
    return caption, bar_chart_svg(f"Spending by category, {month}", rows, money=True,
                                  limits={c: v["budget"] for c, v in st.items() if v["budget"]})


def _chart_daily(month=None):
    today = datetime.now(hub_tz()).date()
    month = month or today.strftime("%Y-%m")
    per = {}
    for e in store().list_expenses(month):
        per[e["date"]] = per.get(e["date"], 0) + e["amount"]
    first = date.fromisoformat(month + "-01")
    days = [(first + timedelta(d)) for d in range(31) if (first + timedelta(d)).month == first.month
            and (first + timedelta(d)) <= today]
    cols = [(str(d.day), per.get(d.isoformat(), 0)) for d in days]
    total = sum(v for _, v in cols)
    return (f"Daily spending for {month}: ${total:,.2f} so far.",
            column_chart_svg(f"Daily spending, {month}", cols, money=True))


def _chart_calendar():
    today = datetime.now(hub_tz()).date()
    days = [today + timedelta(d) for d in range(14)]
    counts = {d: 0 for d in days}
    for o in calendar_events(days[0], days[-1]) if calendar_linked() else []:
        d = o["start"] if o["all_day"] else o["start"].date()
        if d in counts and not o["birthday"]:
            counts[d] += 1
    busiest = max(days, key=lambda d: counts[d])
    caption = ("Events per day for the next two weeks"
               + (f"; busiest is {busiest:%a %b %d} with {counts[busiest]}." if counts[busiest] else ": nothing scheduled."))
    return caption, column_chart_svg("Events per day, next 14 days",
                                     [(f"{d:%m/%d}", counts[d]) for d in days])


def _chart_coverage():
    raw = store().get_meta("round:news:last")
    if not raw:
        return "No story has been covered in a round yet.", bar_chart_svg("Coverage", [])
    last = json.loads(raw)
    rows = [(f"{AGENTS[a]['name']}'s outlets", last["coverage"].get(a, 0)) for a in ("red", "blue", "gray")]
    return (f"How many of each side's outlets covered \"{last['title'][:80]}\".",
            bar_chart_svg("Outlets covering the latest story", rows))


def _chart_activity():
    counts = {}
    for m in store().list_chat(ALLCHAT_KEEP):
        if m.get("kind") != "event" and m["from"] in AGENTS:
            counts[AGENTS[m["from"]]["name"]] = counts.get(AGENTS[m["from"]]["name"], 0) + 1
    rows = sorted(counts.items(), key=lambda r: -r[1])
    return ("Messages per agent in the recent All Agents thread"
            + (f"; {rows[0][0]} has said the most." if rows else ": nobody has posted yet."),
            bar_chart_svg("Who's been talking (All Agents)", rows))


CHARTS = {  # name: (words that ask for it, builder)
    "daily": (("daily", "per day", "each day", "by day"), _chart_daily),
    "spending": (("spend", "budget", "money", "expense", "category"), _chart_spending),
    "calendar": (("calendar", "schedule", "busy", "events", "week ahead"), _chart_calendar),
    "coverage": (("coverage", "covered", "outlets", "news", "story"), _chart_coverage),
    "activity": (("activity", "talking", "messages", "posted"), _chart_activity),
}


def pick_chart(text):
    words = text.lower()
    return next((name for name, (keys, _) in CHARTS.items() if any(k in words for k in keys)), None)


def save_chart(svg):
    """Store an SVG; returns its URL."""
    st = store()
    cid = hashlib.sha1(f"{time.time_ns()}".encode()).hexdigest()[:12]
    st.set_meta(f"chart:{cid}", svg)
    ids = json.loads(st.get_meta("charts") or "[]")
    ids.append(cid)
    for old in ids[:-CHART_KEEP]:
        st.set_meta(f"chart:{old}", "")
    st.set_meta("charts", json.dumps(ids[-CHART_KEEP:]))
    return f"/chart/{cid}.svg"


def charter_reply(text):
    """(caption, image_url) when the text asks for a chart Charter can draw, else None."""
    name = pick_chart(text)
    if not name:
        return None
    caption, svg = CHARTS[name][1]()
    return caption, save_chart(svg)


def charter_context():
    return ("\n\nYou can draw these charts from real hub data when asked: spending by category, "
            "daily spending, calendar busyness, news coverage by side, and All Agents activity. "
            "You can't chart anything else yet (e.g. workouts); say so instead of making up numbers.")


# ---- Phone notifications (Web Push). Mistral delivers them. Needs the
# dashboard installed to the iPhone Home Screen (iOS 16.4+), VAPID keys in
# Vercel (VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY; /api/push/new-keys makes a
# pair) and a tap on "Turn on" inside the Home Screen app.
def _clean_secret(value):
    """Forgive the usual paste slips: spaces, line breaks and quotes."""
    return "".join(value.split()).strip("\"'")


VAPID_PUBLIC_KEY = _clean_secret(os.environ.get("VAPID_PUBLIC_KEY", ""))
VAPID_PRIVATE_KEY = _clean_secret(os.environ.get("VAPID_PRIVATE_KEY", ""))
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "")


def push_subs():
    return json.loads(store().get_meta("push:subs") or "[]")


def _b64url(text):
    import base64
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def push_problem():
    """(code, explanation) of why phone notifications can't work, or None.
    Never includes key material."""
    if not VAPID_PUBLIC_KEY and not VAPID_PRIVATE_KEY:
        return "no_keys", ("VAPID keys aren't in this deployment: add VAPID_PUBLIC_KEY and "
                           "VAPID_PRIVATE_KEY in Vercel, then redeploy")
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        missing = "VAPID_PUBLIC_KEY" if not VAPID_PUBLIC_KEY else "VAPID_PRIVATE_KEY"
        return "half_keys", f"{missing} is missing in this deployment: add it in Vercel, then redeploy"
    try:
        pub, priv = _b64url(VAPID_PUBLIC_KEY), _b64url(VAPID_PRIVATE_KEY)
    except ValueError:
        return "bad_format", "a VAPID key isn't valid: copy it again exactly as shown, then redeploy"
    if len(pub) == 32 and len(priv) == 65:
        return "swapped", "VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY are swapped in Vercel"
    if len(pub) != 65 or pub[0] != 4:
        return "bad_public", "VAPID_PUBLIC_KEY isn't a valid public key: copy it again"
    if len(priv) != 32:
        return "bad_private", "VAPID_PRIVATE_KEY isn't a valid private key: copy it again"
    try:
        from cryptography.hazmat.primitives import serialization
        from py_vapid import Vapid02
        import pywebpush  # noqa: F401
    except ImportError:
        return "no_library", "the push library isn't installed on the server (requirements.txt)"
    derived = Vapid02.from_raw(VAPID_PRIVATE_KEY.encode()).public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    if derived != pub:
        return "mismatch", ("the two VAPID keys aren't a pair (one came from another refresh): "
                            "generate a new pair and replace both")
    return None


def notify(title, body, url="/"):
    """Push to every subscribed device; returns how many got it. Quietly
    does nothing until keys and a subscription exist. Dead subscriptions
    (404/410) are dropped."""
    subs = push_subs()
    problem = push_problem()
    if problem:
        store().set_meta("push:last_error", problem[1])
        return 0
    if not subs:
        return 0
    try:
        from py_vapid import Vapid02
        from pywebpush import WebPushException, webpush
    except ImportError:
        return 0
    subject = VAPID_SUBJECT or store().get_meta("hub:origin") or ""
    if not subject:
        store().set_meta("push:last_error", "no VAPID_SUBJECT and the dashboard hasn't been opened yet")
        return 0
    vapid = Vapid02.from_raw(VAPID_PRIVATE_KEY.encode())
    payload = json.dumps({"title": title, "body": body[:240], "url": url})
    sent, keep, error = 0, [], ""
    for sub in subs:
        try:
            webpush(sub, payload, vapid_private_key=vapid, vapid_claims={"sub": subject}, ttl=3600, timeout=10)
            sent += 1
            keep.append(sub)
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            if code not in (404, 410):  # gone for good: drop it
                keep.append(sub)
            error = f"push service returned {code}: {str(e)[:120]}"
        except Exception as e:  # network trouble shouldn't break a round
            keep.append(sub)
            error = f"push failed: {e!r}"[:160]
    if keep != subs:
        store().set_meta("push:subs", json.dumps(keep))
    store().set_meta("push:last_error", error)
    return sent


def new_vapid_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    import base64
    key = ec.generate_private_key(ec.SECP256R1())
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return {"VAPID_PUBLIC_KEY": b64(key.public_key().public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)),
            "VAPID_PRIVATE_KEY": b64(key.private_numbers().private_value.to_bytes(32, "big"))}


_ICONS = {}


def _icon_png(size):
    """The Home Screen icon: a white ring and dot on the hub blue (PNG, no deps)."""
    if size in _ICONS:
        return _ICONS[size]
    import struct
    import zlib
    c, r_out, r_in, dot = size / 2, size * 0.30, size * 0.20, size * 0.08
    rows = []
    for y in range(size):
        row = bytearray(b"\x00")
        for x in range(size):
            d = ((x + 0.5 - c) ** 2 + (y + 0.5 - c) ** 2) ** 0.5
            row += b"\xff\xff\xff" if (r_in <= d <= r_out or d <= dot) else b"\x2f\x5b\xd3"
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    _ICONS[size] = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))
    return _ICONS[size]


_SW_JS = """
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data.json(); } catch (_) { d = {title: "Bot Hub", body: e.data ? e.data.text() : ""}; }
  e.waitUntil(self.registration.showNotification(d.title || "Bot Hub",
    {body: d.body || "", data: {url: d.url || "/"}, icon: "/icon-192.png", badge: "/icon-192.png"}));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil(clients.openWindow((e.notification.data && e.notification.data.url) || "/"));
});
"""


_PUSH_JS = """
(async () => {
  const status = document.getElementById("push-status");
  const PH = {"Content-Type": "application/json", "x-dashboard-key": new URLSearchParams(location.search).get("key") || ""};
  if (!("serviceWorker" in navigator)) { status.textContent = "This browser can't show notifications."; return; }
  const reg = await navigator.serviceWorker.register("/sw.js");
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  if (!("PushManager" in window) || !("Notification" in window)) {
    status.textContent = standalone ? "Notifications need iOS 16.4 or later."
      : "On iPhone: Share, then Add to Home Screen. Open Bot Hub from the Home Screen and tap Turn on here.";
    return;
  }
  let key = null, problem = "";
  try {
    const r = await fetch("/api/push/key", {headers: PH});
    if (r.status === 401) problem = "This app isn't signed in: open it once with ?key=YOUR_KEY, then add it to the Home Screen again.";
    else { const d = await r.json(); key = d.publicKey; problem = d.problem || ""; }
  } catch (_) { problem = "Couldn't reach the hub to check notifications."; }
  const sub = await reg.pushManager.getSubscription();
  status.textContent = sub ? "Notifications are on for this device." : problem;
  document.getElementById("push-on").onclick = async () => {
    const perm = await Notification.requestPermission();  // first: iOS needs the tap's user gesture
    if (perm !== "granted") { status.textContent = "Notifications were not allowed. To retry on iPhone, remove the Home Screen app and add it again."; return; }
    if (!key) { status.textContent = problem || "Phone notifications aren't set up on the server yet."; return; }
    const raw = atob(key.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - key.length % 4) % 4));
    const s = await reg.pushManager.subscribe({userVisibleOnly: true,
      applicationServerKey: Uint8Array.from(raw, c => c.charCodeAt(0))});
    const d = await (await fetch("/api/push/subscribe", {method: "POST", headers: PH, body: JSON.stringify({subscription: s})})).json();
    status.textContent = d.ok ? "Notifications are on for this device." : "Couldn't turn on: " + d.error;
  };
  document.getElementById("push-test").onclick = async () => {
    const d = await (await fetch("/api/push/test", {method: "POST", headers: PH, body: "{}"})).json();
    status.textContent = d.ok ? (d.sent ? "Sent to " + d.sent + " device(s)." : "Nothing sent: " + (d.error || "no device subscribed")) : d.error;
  };
})();
"""


# ---- Mistral's daily digest and escalation triage
def morning_digest():
    """(post, phone one-liner) for today, from real data only."""
    today = datetime.now(hub_tz()).date()
    lines, brief = [f"Here's today, {today:%A %B %d}:"], []
    if calendar_linked():
        events = calendar_events(today, today)
        todays = [o for o in events if not o["birthday"]]
        lines.append("Calendar: " + ("; ".join(occurrence_text(o) for o in todays) or "nothing scheduled"))
        if todays:
            brief.append(f"{len(todays)} event{'s' if len(todays) != 1 else ''}")
        soon = [o for o in calendar_events(today, today + timedelta(days=1)) if o["birthday"]]
        for o in soon:
            lines.append(f"Birthday: {o['title']} {'today' if (o['start'] == today) else 'tomorrow'}.")
            brief.append(o["title"])
    try:
        breaking, top = news_items()
        heads = (breaking + top)[:3]
    except Exception:
        heads = []
    if heads:
        lines.append("Headlines:\n" + "\n".join(f"- {i['title']} ({i['source']})" for i in heads))
        brief.append(f"{len(heads)} headlines")
    if GLASS_BUDGETS:
        status = month_status()
        over = [f"{c} (${v['spent']:,.0f} of ${v['budget']:,.0f})" for c, v in status.items()
                if v["budget"] and v["spent"] > v["budget"]]
        near = [c for c, v in status.items() if v["budget"] and 0.9 <= v["spent"] / v["budget"] <= 1]
        if over or near:
            lines.append("Budget: " + "; ".join([f"over in {x}" for x in over] + [f"{c} near its limit" for c in near]))
            brief += [f"{c.split(' (')[0]} over budget" for c in over]
        else:
            lines.append("Budget: all categories on track.")
    since = store().get_meta("round:mistral:digest_id")
    recent = [m for m in store().list_chat(ALLCHAT_KEEP) if since and m["id"] > int(since)]
    if recent:
        lines.append(f"Since yesterday's digest: {len(recent)} posts in All Agents.")
    return "\n".join(lines), " · ".join(brief) or "Nothing pressing today"


def _triage_escalations(did):
    """Mistral answers what the Low Brain can; forwards the rest to Theta."""
    st = store()
    done = set(json.loads(st.get_meta("mistral:triaged") or "[]"))
    todo = [e for e in st.list_escalations(50, open_only=True)
            if e["to_role"] == "low_brain" and e["id"] not in done][:3]
    for e in todo:
        reply = llm_chat("low_brain", [
            {"role": "system", "content": system_prompt("mistral")},
            {"role": "user", "content": f"Escalation #{e['id']} from {display_name(e['from_bot'])}: "
             f"{e['issue']}\nContext: {json.dumps(e.get('context') or {})[:600]}\nHandle it in 2-3 "
             "sentences. If it truly needs Theta's decision, start your reply with THETA:"}])
        if reply.strip().upper().startswith("THETA:"):
            note = reply.strip()[6:].strip()
            new_id = st.add_escalation("mistral", "low_brain", "master", f"#{e['id']}: {e['issue']}",
                                       {"from_escalation": e["id"], "mistral": note}, "awaiting_master")
            st.add_chat("mistral", f"#{e['id']} needs Theta, so I passed it up as #{new_id}. {note}")
            notify("Mistral", f"Escalated to Theta: {e['issue'][:120]}")
            did.append(f"forwarded #{e['id']} to Theta")
        else:
            st.add_chat("mistral", f"On #{e['id']} from {display_name(e['from_bot'])}: {reply.strip()}")
            did.append(f"handled #{e['id']}")
        done.add(e["id"])
    st.set_meta("mistral:triaged", json.dumps(sorted(done)[-500:]))


# ---- Rounds: each agent's own job, run on a schedule (Supabase Cron ->
# /api/round). Jobs post real results to All Agents; agents without a data
# source yet say so instead of inventing work.
def _seen(key):
    return json.loads(store().get_meta(key) or "[]")


def _mark_seen(key, url):
    store().set_meta(key, json.dumps(([url] + [u for u in _seen(key) if u != url])[:50]))


def _theta_decisions(did):
    """Decide escalations that reached the High Brain; an ORDER: reply also
    issues a commandeer order."""
    st = store()
    done = set(json.loads(st.get_meta("theta:decided") or "[]"))
    for e in [e for e in st.list_escalations(50, open_only=True)
              if e["to_role"] == "master" and e["id"] not in done][:3]:
        reply = llm_chat("master", [
            {"role": "system", "content": system_prompt("theta")},
            {"role": "user", "content": f"Escalation #{e['id']} from {display_name(e['from_bot'])}: "
             f"{e['issue']}\nContext: {json.dumps(e.get('context') or {})[:600]}\nDecide in 2-3 "
             "sentences. If the crew must act on it, start your reply with ORDER: and the order."}]).strip()
        if reply.upper().startswith("ORDER:"):
            order = reply[6:].strip()
            oid = st.add_order(order[:500], "theta", expires_at=time.time() + ORDER_DAYS * 86400)
            post_event("theta", f"Theta issued order #{oid}: {order[:200]}")
            st.add_chat("theta", f"On #{e['id']}: {order}")
            did.append(f"ordered on #{e['id']}")
        else:
            st.add_chat("theta", f"On #{e['id']}: {reply}")
            did.append(f"decided #{e['id']}")
        notify("Mistral", f"Theta decided #{e['id']}: {reply[:140]}")
        done.add(e["id"])
    st.set_meta("theta:decided", json.dumps(sorted(done)[-500:]))


def week_facts(today):
    """The week's real numbers for Theta's review."""
    st = store()
    since = datetime.combine(today - timedelta(days=6), datetime.min.time())
    recent = [m for m in st.list_chat(ALLCHAT_KEEP)
              if datetime.strptime(m["at"], "%Y-%m-%d %H:%M:%S") >= since]
    talk = {}
    for m in recent:
        if m.get("kind") != "event" and m["from"] in AGENTS:
            talk[AGENTS[m["from"]]["name"]] = talk.get(AGENTS[m["from"]]["name"], 0) + 1
    escs = st.list_escalations(50)
    facts = [f"All Agents posts this week: {sum(talk.values())} "
             f"({', '.join(f'{k} {v}' for k, v in sorted(talk.items(), key=lambda x: -x[1])) or 'none'})",
             f"Open escalations: {sum(1 for e in escs if e['status'] != 'resolved')}"]
    week_spend = sum(e["amount"] for mth in {today.strftime("%Y-%m"), (today - timedelta(days=6)).strftime("%Y-%m")}
                     for e in st.list_expenses(mth) if e["date"] >= (today - timedelta(days=6)).isoformat())
    if GLASS_BUDGETS or week_spend:
        over = [c for c, v in month_status().items() if v["budget"] and v["spent"] > v["budget"]]
        facts.append(f"Spending this week: ${week_spend:,.2f}; over budget this month: {', '.join(over) or 'none'}")
    if calendar_linked():
        nxt = [o for o in calendar_events(today + timedelta(days=1), today + timedelta(days=7)) if not o["birthday"]]
        bdays = [o["title"] for o in calendar_events(today + timedelta(days=1), today + timedelta(days=7)) if o["birthday"]]
        facts.append(f"Next 7 days: {len(nxt)} calendar events" + (f"; birthdays: {', '.join(bdays)}" if bdays else ""))
    last = st.get_meta("round:news:last")
    if last:
        facts.append(f"Latest story the news miners covered: {json.loads(last)['title']}")
    return facts


def _round_theta(ctx):
    """Summarize new reports, decide escalations that reached him, and post a
    weekly review on Sundays."""
    st = store()
    did = []
    unprocessed = st.unprocessed_reports(50)
    if unprocessed:
        r = summarize(unprocessed)
        if not r["ok"]:
            raise LLMError(r["error"])
        n = r["unprocessed_count"]
        did.append(f"summarized {n} report{'s' if n != 1 else ''}")
    _theta_decisions(did)
    today = datetime.now(hub_tz()).date()
    if today.weekday() == 6 and st.get_meta("round:theta:week") != today.isoformat():
        facts = week_facts(today)
        review = llm_chat("master", [
            {"role": "system", "content": system_prompt("theta")},
            {"role": "user", "content": "Write this week's review for the crew in 4-6 sentences, then "
             "'Priorities for next week:' with 2-3 bullets. Use only these facts; don't invent "
             "numbers or events:\n" + "\n".join(f"- {f}" for f in facts)}], max_tokens=900)
        st.add_chat("theta", f"Weekly review ({today:%b %d}):\n{review.strip()}")
        st.set_meta("round:theta:week", today.isoformat())
        notify("Mistral", "Theta's weekly review is in.")
        did.append("posted the weekly review")
    return ", ".join(did) or "nothing new to summarize"


def _round_mistral(ctx):
    """Morning digest (once a day), breaking-news alerts, escalation triage,
    and the wiring check (posted on the first run and when it changes)."""
    st = store()
    did = []
    today = datetime.now(hub_tz()).date().isoformat()
    if st.get_meta("round:mistral:digest_day") != today:
        post, brief = morning_digest()
        try:
            opener = llm_chat("low_brain", [
                {"role": "system", "content": system_prompt("mistral")},
                {"role": "user", "content": "Write one short sentence to open today's digest. "
                 "Don't mention any events, numbers or headlines."}], max_tokens=300)
            post = f"{opener.strip()}\n{post}"
        except LLMError:
            pass
        item = st.add_chat("mistral", post)
        st.set_meta("round:mistral:digest_day", today)
        st.set_meta("round:mistral:digest_id", str(item["id"]))
        notify("Mistral", brief)
        did.append("posted the morning digest")
    try:
        breaking = news_items()[0]
    except Exception:
        breaking = []
    pushed = _seen("push:breaking")
    for b in [b for b in breaking if b["url"] not in pushed][:2]:
        st.add_chat("mistral", f"Breaking ({b['source']}): {b['title']}\n{b['url']}")
        notify("Mistral", f"Breaking ({b['source']}): {b['title']}", b["url"])
        _mark_seen("push:breaking", b["url"])
        did.append("flagged breaking news")
    _triage_escalations(did)
    # Optional links (testable False, e.g. the calendar) only count once set up and failing.
    problems = sorted(f"{r['name']}: {r['note']}" for r in wiring()
                      if r["state"] == "bad" or (r["state"] == "off" and r.get("testable", True)))
    sig = "|".join(problems)
    if sig == st.get_meta("round:mistral:wiring"):  # None on the first check: report it
        did.append("wiring unchanged")
    else:
        st.set_meta("round:mistral:wiring", sig)
        st.add_chat("mistral", "Wiring check: everyone is wired." if not problems else
                    "Wiring check found problems:\n" + "\n".join(f"- {x}" for x in problems))
        if problems:
            notify("Mistral", f"Wiring problem: {problems[0]}" + (f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""))
        did.append("posted a wiring check")
    return ", ".join(did)


def _round_news(agent):
    """Red, Blue and Gray take the same top story, each grounded in how their
    own outlets covered it (or noting that they haven't)."""
    def job(ctx):
        story = ctx.get("story")
        if not story:
            return "no new headlines"
        seen = side_coverage(agent, story["title"])
        if seen:
            coverage = "How your outlets covered it:\n" + "\n".join(
                f"- {it['source']}: {it['title']}" for it in seen)
        else:
            coverage = "None of your outlets have covered it yet; say so, that's worth knowing."
        take = llm_chat(AGENTS[agent]["tier"], [
            {"role": "system", "content": system_prompt(agent) + " You're posting in the All "
             "Agents group chat."},
            {"role": "user", "content": f"Today's top story ({story['source']}): {story['title']}\n"
             f"{coverage}\nGive your take in 2-3 sentences. You only have these headlines: "
             "say so instead of guessing details."}])
        links = [story["url"]] + [it["url"] for it in seen if it["url"] != story["url"]][:1]
        store().add_chat(agent, take.strip() + "\n" + "\n".join(links))
        return (f"posted a take on \"{story['title'][:60]}\""
                + (f" ({len(seen)} of their outlets covered it)" if seen else " (their outlets haven't covered it)"))
    return job


def _round_lenz(ctx):
    """Pitch one new trending title (TMDB facts when linked, else the feeds)."""
    trending = tmdb_trending()
    item = next((i for i in trending if i["url"] not in _seen("round:lenz:seen")), None)
    if item:
        facts = (f"Trending this week on TMDB: {tmdb_fact_line(item)}\n"
                 f"Synopsis: {item['overview'] or 'none given'}\n"
                 "In 1-2 sentences, say why it might be worth a watch. Use only these facts.")
    else:
        item = next((i for i in widget_items(ENTERTAINMENT_FEEDS)
                     if i["url"] not in _seen("round:lenz:seen")), None)
        if not item:
            return "nothing new to pitch"
        facts = (f"New in the feeds ({item['source']}): {item['title']}\n"
                 "In 1-2 sentences, say why it might be worth a look. You only have the title: "
                 "don't invent details.")
    pitch = llm_chat("miner", [
        {"role": "system", "content": system_prompt("lenz") + " You're posting in the All "
         "Agents group chat."},
        {"role": "user", "content": facts}])
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


def _round_remi(ctx):
    """Today's agenda once a day, an update when today's plans change, and
    birthdays 7 days, 1 day and 0 days ahead."""
    if not calendar_linked():
        return "no calendar linked"
    if REMI_CALENDAR_URLS and len(calendar_problems()) == len(REMI_CALENDAR_URLS) and not BIRTHDAYS:
        raise LLMError("couldn't read any calendar link")
    today = datetime.now(hub_tz()).date()
    todays = [o for o in calendar_events(today, today) if not o["birthday"]]
    agenda = "\n".join(f"- {occurrence_text(o)}" for o in todays) or "- Nothing on the calendar."
    digest = hashlib.sha256(agenda.encode()).hexdigest()
    st = store()
    if st.get_meta("round:remi:day") != today.isoformat():
        lines = [f"Today, {today:%A %B %d}:", agenda]
        for o in calendar_events(today, today + timedelta(days=7)):
            if not o["birthday"]:
                continue
            days = ((o["start"] if o["all_day"] else o["start"].date()) - today).days
            if days == 0:
                lines.append(f"Today: {o['title']}!")
                notify("Mistral", f"Remi: today is {o['title']}!", "/calendar")
            elif days in (1, 7):
                lines.append(f"Coming up: {o['title']} {'tomorrow' if days == 1 else 'in a week'}.")
                if days == 1:
                    notify("Mistral", f"Remi: {o['title']} is tomorrow.", "/calendar")
        try:
            opener = llm_chat("manager", [
                {"role": "system", "content": system_prompt("remi")},
                {"role": "user", "content": "Write one warm sentence to open today's family "
                 "agenda post. Don't list or mention any events or times."}], max_tokens=300)
            lines.insert(0, opener.strip())
        except LLMError:
            pass  # the agenda matters more than the greeting
        st.add_chat("remi", "\n".join(lines))
        st.set_meta("round:remi:day", today.isoformat())
        st.set_meta("round:remi:digest", digest)
        return "posted today's agenda"
    if digest != st.get_meta("round:remi:digest"):
        st.add_chat("remi", f"Today's plans changed:\n{agenda}")
        st.set_meta("round:remi:digest", digest)
        return "posted an agenda update"
    return "agenda unchanged"


def _round_glass(ctx):
    """Budget alerts at 90% and 100% (once each per category per month), and a
    week-in-review on the first round of each Sunday."""
    st = store()
    today = datetime.now(hub_tz()).date()
    month = today.strftime("%Y-%m")
    did = []
    alerted = set(json.loads(st.get_meta(f"round:glass:alerts:{month}") or "[]"))
    for cat, v in month_status(month).items():
        if not v["budget"]:
            continue
        share = v["spent"] / v["budget"]
        level = "100" if share >= 1 else "90" if share >= 0.9 else None
        if level and f"{cat}:{level}" not in alerted:
            alerted.add(f"{cat}:{level}")
            alert = (f"{cat} is over budget: ${v['spent']:,.2f} of ${v['budget']:,.0f}."
                     if level == "100" else
                     f"Heads up: {cat} is at {share:.0%} of its budget "
                     f"(${v['spent']:,.2f} of ${v['budget']:,.0f}).")
            st.add_chat("glass", alert)
            notify("Mistral", f"Glass: {alert}")
            did.append(f"{cat} alert")
    st.set_meta(f"round:glass:alerts:{month}", json.dumps(sorted(alerted)))
    if today.weekday() == 6 and st.get_meta("round:glass:week") != today.isoformat():
        week = [e for m in {month, (today - timedelta(days=6)).strftime("%Y-%m")}
                for e in st.list_expenses(m) if (today - timedelta(days=6)).isoformat() <= e["date"] <= today.isoformat()]
        by_cat = {}
        for e in week:
            by_cat[e["category"]] = by_cat.get(e["category"], 0) + e["amount"]
        lines = [f"Week in review (through {today:%b %d}): ${sum(by_cat.values()):,.2f} spent."]
        lines += [f"- {c}: ${a:,.2f}" for c, a in sorted(by_cat.items(), key=lambda x: -x[1])]
        lines += ["Month so far:"] + [f"- {x}" for x in status_lines(month)]
        st.add_chat("glass", "\n".join(lines))
        st.set_meta("round:glass:week", today.isoformat())
        did.append("posted the week in review")
    if not GLASS_BUDGETS and not st.list_expenses(month):
        return "no budgets or expenses yet"
    return ", ".join(did) or "budgets on track"


def _round_charter(ctx):
    """Sundays: this month's spending chart next to Glass's week in review."""
    st = store()
    today = datetime.now(hub_tz()).date()
    if today.weekday() != 6 or st.get_meta("round:charter:week") == today.isoformat():
        return "no chart due"
    if not st.list_expenses(today.strftime("%Y-%m")):
        return "no spending to chart"
    caption, svg = _chart_spending()
    st.add_chat("charter", caption, image=save_chart(svg))
    st.set_meta("round:charter:week", today.isoformat())
    return "posted the spending chart"


ROUND_JOBS = {
    "theta": _round_theta, "remi": _round_remi, "glass": _round_glass, "charter": _round_charter, "mistral": _round_mistral, "james": _round_james,
    "lenz": _round_lenz, "red": _round_news("red"), "blue": _round_news("blue"),
    "gray": _round_news("gray"),
}
_NEWS_AGENTS = {"red", "blue", "gray"}


def run_round(force=False, now=None, only=None):
    """Run every agent's job that is due (or all, with force; or just `only`),
    in parallel, and post one Hub line saying what each did."""
    now = now or time.time()
    st = store()
    last = json.loads(st.get_meta("round:last") or "{}")
    due = [a for a in ROUND_JOBS if (only is None or a in only)
           and (force or now - last.get(a, 0) >= ROUND_MIN_GAP)]
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
        st.set_meta("round:news:last", json.dumps({"title": ctx["story"]["title"], "coverage": {
            a: len(side_coverage(a, ctx["story"]["title"])) for a in _NEWS_AGENTS}}))
    parts = [f"{AGENTS[a]['name']}: {r['did']}" if r["ok"] else f"{AGENTS[a]['name']}: failed ({r['did']})"
             for a, r in results.items()]
    idle = [AGENTS[a]["name"] for a in AGENTS if a not in ROUND_JOBS] if only is None else []
    if idle:
        parts.append(f"{', '.join(idle)}: no job yet")
    if results:
        post_event("hub", "Round: " + "; ".join(parts) + ".")
    return {"ok": True, "ran": results,
            "skipped": [a for a in ROUND_JOBS if a not in due], "no_job": idle}


# ---- Slash commands: typed in either chat box ("/" opens the list, like
# Discord). Each one runs an agent's job on demand; outputs land in All
# Agents. Only you can run them (bots posting "/..." are just text).
class CommandError(Exception):
    """Unknown command or wrong usage; shown to you, not posted."""


def acknowledge_order(oid, request, agents):
    """Each agent says, in character, what it will do and what it can't."""
    def ack(a):
        try:
            if a == "james":
                return a, james_chat([{"role": "user", "content": f"Order from me: {request}. "
                                       "Acknowledge in 1-2 sentences: what will you do?"}]), None
            return a, llm_chat(AGENTS[a]["tier"], [
                {"role": "system", "content": system_prompt(a) + " You're in the All Agents group chat."},
                {"role": "user", "content": f"The user issued order #{oid}: \"{request}\". Acknowledge "
                 "it in 1-2 sentences: what you'll do to follow it, and plainly what part (if any) "
                 "is outside what you can do."}], max_tokens=400), None
        except LLMError as e:
            return a, None, str(e)
    acked, failed = [], []
    with ThreadPoolExecutor(max_workers=max(1, len(agents))) as ex:
        for a, text, err in ex.map(ack, agents):
            if text:
                store().add_chat(a, f"On order #{oid}: {text.strip()}")
                store().ack_order(oid, a)
                acked.append(AGENTS[a]["name"])
            else:
                failed.append(f"{AGENTS[a]['name']} ({err[:80]})")
    return acked, failed


def _cmd_commandeer(arg):
    if not arg:
        raise CommandError("Usage: /commandeer [@agent ...] <order>")
    targets = mentioned_agents(arg)
    expires = time.time() + ORDER_DAYS * 86400
    oid = store().add_order(arg[:500], "you", targets=targets, expires_at=expires)
    who = ", ".join(AGENTS[a]["name"] for a in targets) or "the whole crew"
    post_event("you", f"You issued order #{oid} to {who}: {arg[:200]}")
    # Targeted agents acknowledge; for the whole crew, Theta answers as commander.
    acked, failed = acknowledge_order(oid, arg[:500], targets or ["theta"])
    until = datetime.fromtimestamp(expires, hub_tz())
    return (f"Order #{oid} to {who}, standing until {until:%b %d}."
            + (f" Acknowledged by {', '.join(acked)}." if acked else "")
            + (f" Couldn't acknowledge: {'; '.join(failed)}." if failed else ""))


def _order_line(o):
    to = ", ".join(display_name(t) for t in o.get("targets") or []) or "everyone"
    exp = o.get("expires_at")
    until = f", until {datetime.fromtimestamp(float(exp), hub_tz()):%b %d}" if exp else ""
    acks = f"; acknowledged by {', '.join(display_name(a) for a in o['acked_by'])}" if o.get("acked_by") else ""
    return f"#{o['id']} to {to} (from {display_name(o['issued_by'])}{until}{acks}): {o['request']}"


def _cmd_orders(arg):
    orders = store().list_active_orders()
    store().add_chat("hub", "Active orders:\n" + "\n".join(f"- {_order_line(o)}" for o in orders)
                     if orders else "No active orders.")
    return f"{len(orders)} active order(s)."


def _cmd_done(arg):
    try:
        oid = int(arg.strip().lstrip("#"))
    except ValueError:
        raise CommandError("Usage: /done <order number>, e.g. /done 12")
    order = store().close_order(oid)
    if not order:
        raise CommandError(f"No active order #{oid}. /orders lists them.")
    post_event("you", f"You closed order #{oid}: {order['request'][:200]}")
    return f"Closed order #{oid}."


def _cmd_round(arg):
    r = run_round(force=True)
    return f"Ran {len(r['ran'])} agents' jobs; the Round line says what each did."


def _cmd_digest(arg):
    post, _ = morning_digest()
    store().add_chat("mistral", post)
    return "Mistral posted the digest."


def _cmd_agenda(arg):
    if not calendar_linked():
        raise CommandError("Remi has no calendar yet: set REMI_CALENDAR_URLS in Vercel.")
    today = datetime.now(hub_tz()).date()
    day = today + timedelta(days=1) if arg.strip().lower() == "tomorrow" else today
    items = calendar_events(day, day)
    lines = [f"{'Tomorrow' if day != today else 'Today'}, {day:%A %B %d}:"] + (
        [f"- {occurrence_text(o)}" for o in items] or ["- Nothing on the calendar."])
    store().add_chat("remi", "\n".join(lines))
    return "Remi posted the agenda."


def _cmd_spend(arg):
    parsed = parse_expense(arg if "$" in arg else "$" + arg.strip())
    if not parsed:
        raise CommandError("Usage: /spend $42 groceries at Costco")
    store().add_chat("glass", glass_log_reply(parsed))
    return "Glass logged it."


def _cmd_budget(arg):
    lines = status_lines()
    store().add_chat("glass", f"Budget for {datetime.now(hub_tz()):%B}:\n" + (
        "\n".join(f"- {x}" for x in lines) if lines else "- Nothing logged and no budgets set."))
    return "Glass posted the budget."


def _cmd_chart(arg):
    name = arg.strip().lower() if arg.strip().lower() in CHARTS else pick_chart(arg)
    if not name:
        raise CommandError("Usage: /chart " + next(c["args"] for c in COMMANDS if c["name"] == "chart"))
    caption, svg = CHARTS[name][1]()
    store().add_chat("charter", caption, image=save_chart(svg))
    return "Charter posted the chart."


def _cmd_news(arg):
    r = run_round(force=True, only=_NEWS_AGENTS)
    return "Red, Blue and Gray: " + "; ".join(f"{AGENTS[a]['name']} {v['did']}" for a, v in r["ran"].items())


def _cmd_trending(arg):
    r = run_round(force=True, only={"lenz"})
    return f"Lenz {r['ran']['lenz']['did']}."


def _cmd_summary(arg):
    unprocessed = store().unprocessed_reports(50)
    if not unprocessed:
        return "No new reports to summarize."
    r = summarize(unprocessed)
    if not r["ok"]:
        raise CommandError(r["error"])
    return f"Theta summarized {r['unprocessed_count']} report(s)."


def _cmd_status(arg):
    rows = [r for r in wiring() if r["state"] != "ok"]
    store().add_chat("mistral", "Everyone is wired." if not rows else "Status:\n" + "\n".join(
        f"- {r['name']}: {'not set up' if r['state'] == 'off' else 'not wired'} ({r['note']})" for r in rows))
    return "Mistral posted the status."


def _cmd_help(arg):
    store().add_chat("hub", "Commands:\n" + "\n".join(
        f"/{c['name']}{' ' + c['args'] if c['args'] else ''}: {c['about']}" for c in COMMANDS))
    return "Posted the command list."


COMMANDS = [  # shown in the "/" menu in this order
    {"name": "commandeer", "args": "[@agent] <order>", "about": "Give the crew (or named agents) a standing order", "run": _cmd_commandeer},
    {"name": "orders", "args": "", "about": "List active orders", "run": _cmd_orders},
    {"name": "done", "args": "<number>", "about": "Close an order", "run": _cmd_done},
    {"name": "round", "args": "", "about": "Run every agent's job now", "run": _cmd_round},
    {"name": "digest", "args": "", "about": "Mistral posts today's digest", "run": _cmd_digest},
    {"name": "agenda", "args": "[tomorrow]", "about": "Remi posts the agenda", "run": _cmd_agenda},
    {"name": "spend", "args": "$42 groceries", "about": "Glass logs an expense", "run": _cmd_spend},
    {"name": "budget", "args": "", "about": "Glass posts this month's budget", "run": _cmd_budget},
    {"name": "chart", "args": "spending|daily|calendar|coverage|activity", "about": "Charter draws a chart", "run": _cmd_chart},
    {"name": "news", "args": "", "about": "Red, Blue and Gray take the top story", "run": _cmd_news},
    {"name": "trending", "args": "", "about": "Lenz pitches the next trending title", "run": _cmd_trending},
    {"name": "summary", "args": "", "about": "Theta summarizes new reports", "run": _cmd_summary},
    {"name": "status", "args": "", "about": "Mistral posts what's wired and what isn't", "run": _cmd_status},
    {"name": "help", "args": "", "about": "List these commands", "run": _cmd_help},
]


def run_command(text):
    """Run '/name args'. Returns a one-line result; raises CommandError."""
    name, _, arg = text.strip()[1:].partition(" ")
    cmd = next((c for c in COMMANDS if c["name"] == name.lower()), None)
    if not cmd:
        raise CommandError(f"Unknown command /{name}. Type / to see the list.")
    post_event("you", f"You used /{cmd['name']}{' ' + arg.strip() if arg.strip() else ''}")
    try:
        return cmd["run"](arg.strip())
    except LLMError as e:
        raise CommandError(str(e))


def menu_data():
    """What the "@" and "/" menus list."""
    online = {a["bot_id"]: a["online"] for a in agent_statuses()}
    return {"agents": [{"id": a, "name": v["name"], "tier": TIER_LABELS[v["tier"]], "online": online.get(a, False)}
                       for a, v in AGENTS.items()],
            "commands": [{k: c[k] for k in ("name", "args", "about")} for c in COMMANDS]}


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
    if TMDB_API_KEY:
        try:
            n = len(tmdb_trending())
            rows.append({"agent": "lenz-tmdb", "name": "Lenz's TMDB", "tier": "", "model": "TMDB trending",
                         "testable": False, "state": "ok", "note": f"{n} trending titles"})
        except LLMError as e:
            rows.append({"agent": "lenz-tmdb", "name": "Lenz's TMDB", "tier": "", "model": "TMDB trending",
                         "testable": False, "state": "bad", "note": f"{e}: check TMDB_API_KEY"})
    else:
        rows.append({"agent": "lenz-tmdb", "name": "Lenz's TMDB", "tier": "", "model": "TMDB trending",
                     "testable": False, "state": "off", "note": "Not linked: set TMDB_API_KEY"})
    subs = len(push_subs())
    problem = push_problem()
    if problem:
        push_row = {"state": "off" if problem[0] == "no_keys" else "bad", "note": problem[1]}
    elif not subs:
        push_row = {"state": "off", "note": "No device yet: tap Turn on in the Home Screen app"}
    elif store().get_meta("push:last_error"):
        push_row = {"state": "bad", "note": store().get_meta("push:last_error")}
    else:
        push_row = {"state": "ok", "note": f"{subs} device(s) subscribed"}
    rows.append({"agent": "push", "name": "Phone notifications", "tier": "", "model": "Web Push (Mistral)",
                 "testable": False, **push_row})
    if calendar_linked():
        bad = calendar_problems()
        rows.append({"agent": "remi-calendar", "name": "Remi's calendar", "tier": "",
                     "model": f"{len(REMI_CALENDAR_URLS)} calendar link(s), {len(BIRTHDAYS)} birthdays",
                     "testable": False,
                     **({"state": "bad", "note": f"Couldn't read link(s) {', '.join(map(str, bad))}: "
                                                  "check REMI_CALENDAR_URLS"} if bad else
                        {"state": "ok", "note": "Calendar readable"})})
    else:
        rows.append({"agent": "remi-calendar", "name": "Remi's calendar", "tier": "",
                     "model": "Google Calendar (iCal)", "testable": False, "state": "off",
                     "note": "Not linked: set REMI_CALENDAR_URLS"})
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


def _cookie(headers, name):
    try:
        c = SimpleCookie(headers.get("cookie", ""))
    except Exception:
        return None
    return c[name].value if name in c else None


def _auth_dashboard(query, headers):
    """Dashboard key as a header, ?key= or the hub_key cookie (set the first
    time you open the dashboard with ?key=, so links and the Home Screen app
    don't need it)."""
    if not DASHBOARD_KEY:
        return True
    return DASHBOARD_KEY in (headers.get("x-dashboard-key"), query.get("key", [None])[0],
                             _cookie(headers, "hub_key"))


def _login_cookie(query):
    """Set-Cookie header when the page was opened with the right ?key=."""
    if DASHBOARD_KEY and query.get("key", [None])[0] == DASHBOARD_KEY:
        return [("Set-Cookie", f"hub_key={DASHBOARD_KEY}; Path=/; Max-Age=31536000; "
                               "HttpOnly; Secure; SameSite=Lax")]
    return []


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
function line(who, text, image) {
  const p = document.createElement("p"), b = document.createElement("b");
  b.textContent = who + ": ";
  p.style.whiteSpace = "pre-wrap";
  p.append(b, text);
  if (image) {
    const img = document.createElement("img");
    img.src = image; img.alt = text; img.style.cssText = "display:block;max-width:100%;margin-top:6px;border:1px solid #ddd";
    p.append(img);
  }
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
    log.replaceChildren(...thread.map(m => m.kind === "event" ? eventLine(m.text) : line(m.name, m.text, m.image)));
    return;
  }
  const name = agentSel.selectedOptions[0].dataset.name;
  log.replaceChildren(...(hist[agentSel.value] || []).map(m => line(m.role === "user" ? "You" : name, m.content, m.image)));
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
async function runCommand(text) {
  status.textContent = "Running " + text.split(" ")[0] + "...";
  try {
    const d = await (await fetch("/api/allchat", {method: "POST", headers: H, body: JSON.stringify({text})})).json();
    if (!d.ok) throw new Error(d.error);
    thread = d.messages;
    status.textContent = d.result + (agentSel.value === ALL ? "" : " (in All Agents)");
  } catch (err) {
    msg.value = text;
    status.textContent = err.message;
  }
  btn.disabled = false;
  show();
}

// "@" and "/" menus, like Discord: type to filter, arrows + Enter/Tab, Esc, or tap.
const menu = document.getElementById("chat-menu");
let menuItems = [], menuActive = 0, menuRange = null;
function menuQuery() {
  const before = msg.value.slice(0, msg.selectionStart);
  let m = before.match(/(^|\\s)@([\\w-]*)$/);
  if (m && agentSel.value === ALL) return {kind: "@", q: m[2].toLowerCase(), start: before.length - m[2].length - 1};
  m = before.match(/^\\/(\\w*)$/);
  if (m) return {kind: "/", q: m[1].toLowerCase(), start: 0};
  return null;
}
function closeMenu() { menu.hidden = true; menuItems = []; menuRange = null; msg.removeAttribute("aria-activedescendant"); }
function renderMenu() {
  const q = menuQuery();
  if (!q) return closeMenu();
  const src = q.kind === "@" ? HUB_MENU.agents : HUB_MENU.commands;
  const key = x => (q.kind === "@" ? x.name : x.name).toLowerCase();
  menuItems = src.filter(x => key(x).startsWith(q.q) || (q.kind === "@" && x.id.startsWith(q.q)))
    .concat(src.filter(x => !key(x).startsWith(q.q) && key(x).includes(q.q) && q.q)).slice(0, 12);
  if (!menuItems.length) return closeMenu();
  menuRange = q; menuActive = Math.min(menuActive, menuItems.length - 1);
  menu.replaceChildren(...menuItems.map((x, i) => {
    const li = document.createElement("li");
    li.id = "chat-menu-" + i; li.setAttribute("role", "option");
    li.setAttribute("aria-selected", String(i === menuActive));
    li.style.cssText = "padding:6px 10px;cursor:pointer;" + (i === menuActive ? "background:#e8eefc" : "");
    const b = document.createElement("b"), small = document.createElement("span");
    small.style.color = "#666";
    if (q.kind === "@") {
      const dot = document.createElement("span");
      dot.textContent = "\u25CF "; dot.style.color = x.online ? "#1a7f37" : "#aaa";
      b.textContent = x.name; small.textContent = " " + x.tier;
      li.append(dot, b, small);
    } else {
      b.textContent = "/" + x.name; small.textContent = (x.args ? " " + x.args : "") + " \u2014 " + x.about;
      li.append(b, small);
    }
    li.onmousedown = ev => { ev.preventDefault(); pickMenu(i); };
    return li;
  }));
  menu.hidden = false;
  msg.setAttribute("aria-activedescendant", "chat-menu-" + menuActive);
}
function pickMenu(i) {
  const x = menuItems[i], q = menuRange;
  if (!x || !q) return;
  const insert = q.kind === "@" ? "@" + x.name + " " : "/" + x.name + " ";
  const end = msg.selectionStart;
  msg.value = msg.value.slice(0, q.start) + insert + msg.value.slice(end);
  const pos = q.start + insert.length;
  msg.setSelectionRange(pos, pos); msg.focus();
  menuActive = 0; closeMenu();
}
msg.addEventListener("input", () => { menuActive = 0; renderMenu(); });
msg.addEventListener("click", renderMenu);
msg.addEventListener("blur", () => setTimeout(closeMenu, 150));
msg.addEventListener("keydown", e => {
  if (menu.hidden) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    menuActive = (menuActive + (e.key === "ArrowDown" ? 1 : menuItems.length - 1)) % menuItems.length;
    renderMenu();
  } else if (e.key === "Enter" || e.key === "Tab") {
    e.preventDefault(); pickMenu(menuActive);
  } else if (e.key === "Escape") {
    e.preventDefault(); closeMenu();
  }
});

document.getElementById("chat-form").onsubmit = async e => {
  e.preventDefault();
  const text = msg.value.trim(), agent = agentSel.value;
  if (!text) return;
  msg.value = ""; btn.disabled = true; closeMenu();
  if (text.startsWith("/")) return runCommand(text);
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
    h.push({role: "assistant", content: d.reply, image: d.image});
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
      if (a.testable !== false) {
        const b = document.createElement("button");
        b.type = "button"; b.textContent = "Test";
        b.onclick = () => testAgent(a.agent, result, b);
        test.append(b);
      }
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
    menu = json.dumps(menu_data()).replace("</", "<\\/")
    return (f"<p><select id=\"chat-agent\" style=\"max-width:100%\">{''.join(groups)}</select></p>"
            "<div id=\"chat-log\"></div>"
            "<form id=\"chat-form\" style=\"position:relative\">"
            "<ul id=\"chat-menu\" role=\"listbox\" hidden style=\"position:absolute;bottom:100%;left:0;"
            "right:0;max-height:260px;overflow-y:auto;margin:0 0 4px;padding:4px 0;list-style:none;"
            "background:#fff;border:1px solid #ccc;border-radius:6px;box-shadow:0 4px 14px rgba(0,0,0,.15);"
            "z-index:5\"></ul>"
            "<textarea id=\"chat-msg\" rows=\"3\" aria-autocomplete=\"list\" aria-controls=\"chat-menu\" "
            "style=\"width:100%\"></textarea><br><button id=\"chat-send\">Send</button> "
            "<i id=\"chat-status\"></i></form>"
            f"<script>window.HUB_MENU = {menu};</script>"
            "<h3>Wiring</h3><div style=\"overflow-x:auto\"><table style=\"border-collapse:collapse\" "
            "cellpadding=\"4\"><thead><tr><th align=\"left\">Agent</th><th align=\"left\">Model</th>"
            "<th align=\"left\">Status</th><th align=\"left\">Details</th><th></th></tr></thead>"
            "<tbody id=\"wiring-rows\"></tbody></table></div>"
            "<p><button id=\"wiring-recheck\" type=\"button\">Recheck</button> "
            "<i id=\"wiring-note\"></i></p>"
            f"<script>{_CHAT_JS}</script>")


_PAGE_CSS = ("<style>body{font-family:system-ui,sans-serif;margin:0;padding:12px 16px 40px;"
             "max-width:960px}nav{display:flex;gap:16px;border-bottom:1px solid #ccc;"
             "padding-bottom:8px;margin-bottom:8px}nav a{text-decoration:none;color:#555;"
             "padding:4px 2px}nav a.on{color:#000;font-weight:bold;border-bottom:3px solid #2f5bd3}"
             ".cal{border-collapse:collapse;width:100%;table-layout:fixed}"
             ".cal th{font-size:12px;color:#666;padding:4px}"
             ".cal td{border:1px solid #ddd;vertical-align:top;height:72px;padding:3px;font-size:11px;"
             "overflow:hidden}.cal td.out{background:#f6f6f6;color:#aaa}.cal td.today{outline:2px solid #2f5bd3}"
             ".cal .n{font-weight:bold;font-size:12px}.cal .e{white-space:nowrap;overflow:hidden;"
             "text-overflow:ellipsis}.cal .b{color:#a35d00}.day{margin:14px 0 4px;font-weight:bold}"
             ".tag{color:#a35d00;font-size:12px}</style>")


def _nav(active):
    tabs = [("/", "Dashboard"), ("/calendar", "Remi's calendar")]
    return "<nav>" + "".join(
        f"<a href=\"{href}\" class=\"{'on' if href == active else ''}\">{label}</a>"
        for href, label in tabs) + "</nav>"


def calendar_page(query):
    """Remi's tab: a month grid plus the same month as a day-by-day list."""
    tz = hub_tz()
    today = datetime.now(tz).date()
    try:
        y, m = (int(x) for x in query.get("month", [""])[0].split("-"))
        first = date(y, m, 1)
    except ValueError:
        first = today.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    prev = (first - timedelta(days=1)).replace(day=1)
    head = (f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Remi's calendar</title>{_PAGE_CSS}{_nav('/calendar')}"
            f"<h1>Remi's calendar</h1>")
    if not calendar_linked():
        return head + ("<p>No calendar linked yet. In Google Calendar on a computer: Settings → "
                       "your calendar → <b>Integrate calendar</b> → copy <b>Secret address in "
                       "iCal format</b>. In Vercel, set <code>REMI_CALENDAR_URLS</code> to it "
                       "(comma-separate several) and redeploy. Treat it like a password.</p>")
    grid_start = first - timedelta(days=(first.weekday() + 1) % 7)  # Sunday
    grid_end = grid_start + timedelta(days=41)
    occ = calendar_events(grid_start, grid_end)
    by_day = {}
    for o in occ:
        d0 = o["start"] if o["all_day"] else o["start"].date()
        d1 = (o["end"] - timedelta(days=1)) if o["all_day"] else o["end"].date()
        d = max(d0, grid_start)
        while d <= max(d0, d1) and d <= grid_end:
            by_day.setdefault(d, []).append(o)
            d += timedelta(days=1)
    rows = []
    for w in range(6):
        cells = []
        for i in range(7):
            d = grid_start + timedelta(days=w * 7 + i)
            items = by_day.get(d, [])
            evs = "".join(
                f"<div class=\"e{' b' if o['birthday'] else ''}\">"
                f"{'' if o['all_day'] else html.escape(_clock(o['start'])) + ' '}{html.escape(o['title'])}</div>"
                for o in items[:3])
            more = f"<div>+{len(items) - 3} more</div>" if len(items) > 3 else ""
            cls = " ".join(c for c in ("out" if d.month != first.month else "",
                                       "today" if d == today else "") if c)
            cells.append(f"<td class=\"{cls}\"><div class=\"n\">{d.day}</div>{evs}{more}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    listing = []
    d = first
    while d < nxt:
        items = by_day.get(d, [])
        if items:
            listing.append(f"<div class=\"day\">{d:%A %B %d}</div><ul>" + "".join(
                f"<li>{html.escape(occurrence_text(o))}"
                f"{' <span class=tag>birthday</span>' if o['birthday'] else ''}</li>" for o in items) + "</ul>")
        d += timedelta(days=1)
    return head + (
        f"<p><a href=\"/calendar?month={prev:%Y-%m}\">&larr; {prev:%B}</a> · "
        f"<b>{first:%B %Y}</b> · <a href=\"/calendar?month={nxt:%Y-%m}\">{nxt:%B} &rarr;</a></p>"
        "<div style=\"overflow-x:auto\"><table class=\"cal\"><tr>"
        + "".join(f"<th>{d}</th>" for d in ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"))
        + "</tr>" + "".join(rows) + "</table></div>"
        + ("".join(listing) or "<p>Nothing scheduled this month.</p>")
        + f"<p><small>Times in {html.escape(HUB_TIMEZONE)}. From your Google Calendar "
          "(read-only), refreshed every 10 minutes.</small></p>")


_BUDGET_JS = """
document.getElementById("csv-import").onclick = async () => {
  const f = document.getElementById("csv-file").files[0], out = document.getElementById("csv-status");
  if (!f) { out.textContent = "Pick your Rocket Money CSV first."; return; }
  out.textContent = "Importing...";
  try {
    const d = await (await fetch("/api/glass/import", {method: "POST",
      headers: {"Content-Type": "application/json", "x-dashboard-key": new URLSearchParams(location.search).get("key") || ""},
      body: JSON.stringify({csv: await f.text()})})).json();
    if (!d.ok) throw new Error(d.error);
    const sk = Object.entries(d.skipped).filter(([, n]) => n).map(([k, n]) => n + " " + k).join(", ");
    out.textContent = "Added " + d.added + " expenses" + (d.duplicates ? ", " + d.duplicates + " already imported" : "")
      + (sk ? "; skipped " + sk : "") + ". Read columns " + Object.values(d.columns).join(", ")
      + "; expenses were " + d.expenses_were + " in this file. Reload to see the totals.";
  } catch (err) { out.textContent = "Import failed: " + err.message; }
};
"""


def _budget_html():
    month = datetime.now(hub_tz()).strftime("%Y-%m")
    rows = []
    for cat, v in month_status(month).items():
        if v["budget"]:
            share = v["spent"] / v["budget"]
            color = "#b3261e" if share >= 1 else "#a35d00" if share >= 0.9 else "#1a7f37"
            rows.append(f"<li><b>{html.escape(cat)}</b> ${v['spent']:,.2f} of ${v['budget']:,.0f}"
                        f"<div style=\"background:#e4e8ee;height:6px;max-width:320px\"><div style=\""
                        f"background:{color};height:6px;width:{min(share, 1) * 100:.0f}%\"></div></div></li>")
        elif v["spent"]:
            rows.append(f"<li><b>{html.escape(cat)}</b> ${v['spent']:,.2f} <i>(no budget)</i></li>")
    listing = (f"<ul style=\"list-style:none;padding-left:0\">{''.join(rows)}</ul>" if rows else
               "<p>No budgets or expenses yet. Set GLASS_BUDGETS in Vercel (e.g. "
               "<code>Groceries:600,Dining:200</code>), log spending with \"@glass $42 groceries\", "
               "or import a Rocket Money export.</p>")
    return (f"<p><small>{month}</small></p>{listing}"
            "<p>Import a Rocket Money export (Transactions → Export on a computer): "
            "<input id=\"csv-file\" type=\"file\" accept=\".csv,text/csv\"> "
            "<button id=\"csv-import\" type=\"button\">Import</button> <i id=\"csv-status\"></i></p>"
            f"<script>{_BUDGET_JS}</script>")


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
                parsed = parse_expense(history[-1]["content"]) if agent == "glass" else None
                chart = charter_reply(history[-1]["content"]) if agent == "charter" else None
                image = None
                if chart:
                    reply, image = chart
                elif parsed:
                    reply = glass_log_reply(parsed)
                elif agent == "james":
                    reply = james_chat(history)
                else:
                    reply = llm_chat(AGENTS[agent]["tier"],
                                     [{"role": "system", "content": system_prompt(agent)}] + history)
            except LLMError as e:
                return _json(502, {"ok": False, "error": str(e)})
            return _json(200, {"ok": True, "agent": agent, "name": AGENTS[agent]["name"],
                               "model": agent_model(agent), "reply": reply, "image": image})

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
            if text.strip().startswith("/"):
                try:
                    result = run_command(text)
                except CommandError as e:
                    return _json(400, {"ok": False, "error": str(e)})
                return _json(200, {"ok": True, "command": True, "result": result,
                                   "messages": allchat_view(), "errors": {}, "routed": []})
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
                except (LLMError, ValueError, KeyError) as e:
                    return a, None, str(e)
            if agents:
                with ThreadPoolExecutor(max_workers=len(agents)) as ex:
                    for a, reply, err in ex.map(answer, agents):
                        if isinstance(reply, tuple):  # Charter's (caption, chart url)
                            st.add_chat(a, reply[0], image=reply[1])
                        elif reply:
                            st.add_chat(a, reply.strip()[:4000])
                        else:
                            errors[AGENTS[a]["name"]] = err
            return _json(200, {"ok": True, "messages": allchat_view(), "errors": errors,
                               "routed": [AGENTS[a]["name"] for a in routed]})

        if path == "/api/glass/expense":
            bot_id = data.get("bot_id")
            if not (_auth_bot(bot_id, headers) if bot_id else _auth_dashboard(query, headers)):
                return _json(401, {"ok": False, "error": "dashboard key or bot key required"})
            try:
                amount = float(data.get("amount"))
            except (TypeError, ValueError):
                return _json(400, {"ok": False, "error": "amount must be a number"})
            if amount <= 0 or not str(data.get("category") or "").strip():
                return _json(400, {"ok": False, "error": "positive amount and a category required"})
            day = _parse_day(str(data.get("date") or "")) if data.get("date") else None
            exp = add_expense(amount, str(data["category"]), str(data.get("note") or ""), day=day,
                              source=bot_id or "dashboard")
            post_event("glass", f"Glass logged ${amount:,.2f} for {exp['category']}"
                                + (f" from {display_name(bot_id)}" if bot_id else ""))
            return _json(200, {"ok": True, "expense": exp})

        if path == "/api/glass/import":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            if not isinstance(data.get("csv"), str):
                return _json(400, {"ok": False, "error": "send {\"csv\": <file text>}"})
            result = import_csv(data["csv"])
            if result["ok"] and result["added"]:
                post_event("glass", f"Glass imported {result['added']} expenses from a CSV "
                                    f"({', '.join(result['months'])})")
            return _json(200 if result["ok"] else 400, result)

        if path == "/api/push/subscribe":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            sub = data.get("subscription")
            if not (isinstance(sub, dict) and str(sub.get("endpoint", "")).startswith("https://")
                    and isinstance(sub.get("keys"), dict) and sub["keys"].get("p256dh") and sub["keys"].get("auth")):
                return _json(400, {"ok": False, "error": "not a push subscription"})
            subs = [x for x in push_subs() if x.get("endpoint") != sub["endpoint"]]
            subs.append({"endpoint": sub["endpoint"], "keys": {"p256dh": sub["keys"]["p256dh"], "auth": sub["keys"]["auth"]}})
            store().set_meta("push:subs", json.dumps(subs[-10:]))
            store().set_meta("push:last_error", "")
            post_event("mistral", "Mistral will now send phone notifications to a new device")
            return _json(200, {"ok": True, "devices": len(subs[-10:])})

        if path == "/api/push/test":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            sent = notify("Mistral", "Test: phone notifications from Bot Hub work.")
            problem = push_problem()
            return _json(200, {"ok": True, "sent": sent, "error": (problem[1] if problem else None)
                               or store().get_meta("push:last_error")
                               or (None if sent else "no device has turned notifications on yet")})

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
    if path == "/sw.js":
        return 200, "text/javascript; charset=utf-8", _SW_JS.encode(), [("Cache-Control", "no-cache")]
    if path in ("/icon-192.png", "/icon-512.png", "/apple-touch-icon.png", "/favicon.ico"):
        size = {"/icon-192.png": 192, "/icon-512.png": 512, "/favicon.ico": 32}.get(path, 180)
        return 200, "image/png", _icon_png(size), [("Cache-Control", "public, max-age=604800")]
    if path == "/manifest.webmanifest":
        # Opened signed in (Safari's "Add to Home Screen"), the app starts with the
        # key, so the Home Screen copy (which has its own cookies) is signed in too.
        start = (f"/?key={DASHBOARD_KEY}" if DASHBOARD_KEY and _auth_dashboard(query, headers) else "/")
        manifest = {"name": "Bot Hub", "short_name": "Bot Hub", "start_url": start, "scope": "/",
                    "display": "standalone", "background_color": "#ffffff", "theme_color": "#2f5bd3",
                    "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                              {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}]}
        return (200, "application/manifest+json", json.dumps(manifest).encode(),
                [("Cache-Control", "no-store")])
    if path == "/api/push/key":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        problem = push_problem()
        return _json(200, {"ok": True, "publicKey": None if problem else VAPID_PUBLIC_KEY,
                           "problem": problem[1] if problem else None})
    if path == "/api/push/health":
        # Public on purpose: says whether push is configured, never with what.
        problem = push_problem()
        return _json(200, {"ok": True, "status": problem[0] if problem else "ok",
                           "devices": len(push_subs())})
    if path == "/api/push/new-keys":
        if not _auth_dashboard(query, headers) or not DASHBOARD_KEY:
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, {"ok": True, **new_vapid_keys(), "next": "Add both to Vercel (Production and Preview, "
                           "Sensitive on), redeploy, then tap Turn on in the Home Screen app. Keep "
                           "VAPID_PRIVATE_KEY secret; this page makes a new pair each time."})

    if path == "/":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        st = store()
        host = headers.get("host")
        if host and st.get_meta("hub:origin") != f"https://{host}":
            st.set_meta("hub:origin", f"https://{host}")  # the push "subject" when VAPID_SUBJECT is unset
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
            f"<li>{html.escape(_order_line(o))}</li>"
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
                     "<i id=\"round-status\"></i></p>"
                     "<p>Phone notifications (from Mistral): <button id=\"push-on\" type=\"button\">Turn on</button> "
                     "<button id=\"push-test\" type=\"button\">Send a test</button> <i id=\"push-status\"></i></p>"
                     f"<script>{_PUSH_JS}</script>")
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
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Bot Hub</title><link rel=\"manifest\" href=\"/manifest.webmanifest\" crossorigin=\"use-credentials\">"
            "<link rel=\"apple-touch-icon\" href=\"/apple-touch-icon.png\"><meta name=\"theme-color\" content=\"#2f5bd3\">"
            "<meta name=\"apple-mobile-web-app-capable\" content=\"yes\">"
            f"{_PAGE_CSS}{_nav('/')}<h1>Bot hub</h1>"
            f"<h2>Agents</h2><ul style=\"list-style:none;padding-left:0\">{agent_items}</ul>{round_btn}"
            f"<h2>Chat</h2>{_chat_html()}"
            f"<h2>News</h2>{news_html}"
            f"<h2>Entertainment</h2><ul>{ent_items}</ul>"
            f"<h2>Fitness — overall health</h2>{fit_html}{app_link}"
            f"<h2>Budget (Glass)</h2>{_budget_html()}"
            f"<h2>Reports</h2><ul>{items}</ul>"
            f"<h2>Escalations</h2><ul>{esc_items}</ul>"
            f"<h2>Commandeer orders</h2><ul>{ord_items}</ul>"
            f"{storage_note}"
            + (f"<p><small>{TMDB_NOTICE}</small></p>" if TMDB_API_KEY else "")
        ).encode()
        return 200, "text/html; charset=utf-8", body, _login_cookie(query)

    if path == "/calendar":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return 200, "text/html; charset=utf-8", calendar_page(query).encode(), _login_cookie(query)

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
        return _json(200, [o for o in store().list_active_orders()
                           if not o.get("targets") or bot_id in o["targets"]])

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

    if path.startswith("/chart/") and path.endswith(".svg"):
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        cid = path[len("/chart/"):-len(".svg")]
        svg = store().get_meta(f"chart:{cid}") if cid.isalnum() else None
        if not svg:
            return _json(404, {"ok": False, "error": "no such chart"})
        return 200, "image/svg+xml", svg.encode(), [("Cache-Control", "private, max-age=86400")]

    if path == "/api/glass":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        month = query.get("month", [datetime.now(hub_tz()).strftime("%Y-%m")])[0]
        return _json(200, {"ok": True, "month": month, "status": month_status(month),
                           "expenses": sorted(store().list_expenses(month), key=lambda e: e["date"])})

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
        status, ctype, out, *extra = handle(method, path, query, headers, body)
    except Exception as exc:  # e.g. storage down: answer, don't crash
        print(f"handle error on {method} {path}: {exc!r}")
        (status, ctype, out), extra = _json(500, {"ok": False, "error": "internal error"}), []
    start_response(f"{status} {_REASONS.get(status, '')}",
                   [("Content-Type", ctype), ("Content-Length", str(len(out)))]
                   + (extra[0] if extra else []))
    return [out]


if __name__ == "__main__":
    # Local test server (memory store unless KV vars are set).
    from wsgiref.simple_server import make_server
    port = int(os.environ.get("PORT", "8770"))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"Bot hub (Vercel edition) on http://{host}:{port} — storage: {STORAGE_MODE}")
    make_server(host, port, app).serve_forever()
