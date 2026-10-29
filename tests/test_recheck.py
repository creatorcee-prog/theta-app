"""Diagnostics → Models & providers: Recheck checks live (fresh=1), and rows
for jobs that are set up but haven't run yet say so instead of "not set up".
No live network: model lists, calendars, Gmail and Finnhub are stubbed."""
import sys, json, os, io, time
sys.dont_write_bytecode = True
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
os.environ.update(DASHBOARD_KEY="dk", GROQ_API_KEY="qk", GEMINI_API_KEY="gk", ANTHROPIC_API_KEY="",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h  # memory store in both modes: nothing here depends on Redis
from datetime import datetime, timezone
from wsgiref.util import setup_testing_defaults


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


def call(path, qs=""):
    env = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO()}
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s)))
    return int(got["s"][:3]), json.loads(out) if out[:1] == b"{" else out


LISTS = []
def fake_list(p):
    LISTS.append(p)
    return {"models": ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "gemini-3.8-flash"]}
h._list_models = fake_list
h.tmdb_trending = lambda: []
row = lambda rows, a: next(r for r in rows if r["agent"] == a)
print("mode:", mode)

# ---- model lists: the cache is skipped only on Recheck
h._MODELS_CACHE.clear()
h.wiring(); n = len(LISTS); h.wiring()
check("a normal load reuses the 10-minute model-list cache", len(LISTS) == n)
h.wiring(fresh=True)
check("Recheck asks the providers again", len(LISTS) > n)
s, d = call("/api/wiring", "key=dk&fresh=1")
check("/api/wiring?fresh=1 is the live check", s == 200 and d["ok"] and len(LISTS) > n + 1)
page = call("/diagnostics", "key=dk")[1].decode()
check("the Recheck button asks for fresh=1", 'onclick = () => load(true)' in page and '"?fresh=1"' in page)

# ---- rounds: scheduled, not "not set up", once the cron is alive
h.store().set_meta("round:last", "{}")
h.store().set_meta("tick:last", "0")
check("no round and no tick: still points at the Supabase job", "run the bot-hub-rounds job" in row(h.wiring(), "rounds")["note"])
h.store().set_meta("tick:last", str(time.time() - 120))
r = row(h.wiring(), "rounds")
check("tick alive, no round yet: says it's scheduled and when", r["state"] == "ok" and "Scheduled" in r["note"]
      and "first round should come at" in r["note"])
at = datetime(2026, 10, 29, 13, 0, tzinfo=timezone.utc).timestamp()
check("next round after 13:00 UTC is 18:00 UTC", h.next_round_at(at).astimezone(timezone.utc).hour == 18)
at = datetime(2026, 10, 29, 19, 0, tzinfo=timezone.utc).timestamp()
nxt = h.next_round_at(at).astimezone(timezone.utc)
check("after the last one, it's 00:00 UTC the next day", nxt.hour == 0 and nxt.day == 30)

# ---- calendar: live on Recheck
h.REMI_CALENDAR_URLS = ["https://cal.example/a.ics", "https://cal.example/b.ics"]
FETCHED = []
def fake_text(u):
    FETCHED.append(u)
    return None if u.endswith("b.ics") else "BEGIN:VCALENDAR\nEND:VCALENDAR"
h._calendar_text = fake_text
h.calendar_problems = lambda: []
check("a normal load uses the saved status", row(h.wiring(), "remi-calendar")["state"] == "ok" and not FETCHED)
r = row(h.wiring(fresh=True), "remi-calendar")
check("Recheck reads each calendar now and names the bad one", r["state"] == "bad" and "2" in r["note"] and len(FETCHED) == 2)

# ---- Gmail: live on Recheck
h.gmail_connected = lambda: True
h.gmail_api = lambda m, p, *a, **k: {"emailAddress": "me@example.com"}
r = row(h.wiring(fresh=True), "gmail")
check("Recheck asks Gmail who it's connected as", r["state"] == "ok" and "me@example.com" in r["note"] and "just now" in r["note"])
def gmail_down(*a, **k): raise h.LLMError("Gmail returned 401: invalid_grant")
h.gmail_api = gmail_down
r = row(h.wiring(fresh=True), "gmail")
check("...and says so when the sign-in has expired", r["state"] == "bad" and "401" in r["note"])

# ---- stocks: set up but no prices yet is not "not set up"
h.FINNHUB_API_KEY = "fk"; h.stocks_on = lambda: True; h.stock_symbols = lambda: ["NVDA"]
h.store().set_meta("stocks:quotes", "{}")
check("set up, no prices yet: ok, not grey", row(h.wiring(), "stocks")["state"] == "ok")
h.finnhub = lambda path, **p: {"c": 123.45}
r = row(h.wiring(fresh=True), "stocks")
check("Recheck gets a live price", r["state"] == "ok" and "$123.45" in r["note"])
h.finnhub = lambda path, **p: {"c": 0}
check("...and flags a symbol with no price", row(h.wiring(fresh=True), "stocks")["state"] == "bad")

# ---- Lenz's channels: set up but not checked yet is ok
h.LENZ_YOUTUBE = ["@somechannel"]
h.store().set_meta("lenz:feeds:at", "0")
r = row(h.wiring(), "lenz-feeds")
check("Lenz's channels set up, first check pending: ok", r["state"] == "ok" and "first check comes" in r["note"])
print("ALL PASS")
