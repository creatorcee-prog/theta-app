import sys, json, threading, os, io, time
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
TZ = ZoneInfo("America/Denver")
TODAY = datetime.now(TZ).date()
def d(n): return (TODAY + timedelta(days=n)).strftime("%Y%m%d")
monday = TODAY - timedelta(days=TODAY.weekday())
ICS = "\r\n".join([
 "BEGIN:VCALENDAR", "VERSION:2.0",
 # timed, local TZID, today 9-10am
 "BEGIN:VEVENT", "UID:a", f"DTSTART;TZID=America/Denver:{d(0)}T090000", f"DTEND;TZID=America/Denver:{d(0)}T100000",
 "SUMMARY:Dentist\\, Dr. Lee", "LOCATION:Main St", "END:VEVENT",
 # UTC timed today 23:30Z
 "BEGIN:VEVENT", "UID:b", f"DTSTART:{d(1)}T013000Z", f"DTEND:{d(1)}T020000Z", "SUMMARY:Late call", "END:VEVENT",
 # all-day 3-day trip starting tomorrow
 "BEGIN:VEVENT", "UID:c", f"DTSTART;VALUE=DATE:{d(1)}", f"DTEND;VALUE=DATE:{d(4)}", "SUMMARY:Camping trip", "END:VEVENT",
 # weekly Mon+Wed soccer from 4 weeks ago, 5pm, one exdate, one moved
 "BEGIN:VEVENT", "UID:w", f"DTSTART;TZID=America/Denver:{(monday - timedelta(weeks=4)).strftime('%Y%m%d')}T170000",
 f"DTEND;TZID=America/Denver:{(monday - timedelta(weeks=4)).strftime('%Y%m%d')}T180000",
 "RRULE:FREQ=WEEKLY;BYDAY=MO,WE", f"EXDATE;TZID=America/Denver:{(monday + timedelta(days=7)).strftime('%Y%m%d')}T170000",
 "SUMMARY:Soccer practice", "END:VEVENT",
 "BEGIN:VEVENT", "UID:w", f"RECURRENCE-ID;TZID=America/Denver:{(monday + timedelta(days=9)).strftime('%Y%m%d')}T170000",
 f"DTSTART;TZID=America/Denver:{(monday + timedelta(days=9)).strftime('%Y%m%d')}T183000",
 f"DTEND;TZID=America/Denver:{(monday + timedelta(days=9)).strftime('%Y%m%d')}T193000", "SUMMARY:Soccer practice (moved)", "END:VEVENT",
 # yearly birthday 7 days ahead (started years ago)
 "BEGIN:VEVENT", "UID:y", f"DTSTART;VALUE=DATE:{(TODAY + timedelta(days=7)).replace(year=2015).strftime('%Y%m%d')}",
 "RRULE:FREQ=YEARLY", "SUMMARY:Grandma's birthday", "END:VEVENT",
 # cancelled today
 "BEGIN:VEVENT", "UID:x", f"DTSTART;TZID=America/Denver:{d(0)}T120000", f"DTEND;TZID=America/Denver:{d(0)}T130000",
 "STATUS:CANCELLED", "SUMMARY:Cancelled lunch", "END:VEVENT",
 # monthly 2nd Tuesday, 3 occurrences only
 "BEGIN:VEVENT", "UID:m", f"DTSTART;TZID=America/Denver:{(TODAY.replace(day=1)).strftime('%Y%m%d')}T190000",
 f"DTEND;TZID=America/Denver:{(TODAY.replace(day=1)).strftime('%Y%m%d')}T200000",
 "RRULE:FREQ=MONTHLY;BYDAY=2TU;COUNT=3", "SUMMARY:PTA meeting", "END:VEVENT",
 "END:VCALENDAR", ""])
STATE = {"ics": ICS, "fail": False, "llm": 0}
DB = {}
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj, raw=None):
        b = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/cal.ics":
            return self._send(500, {}) if STATE["fail"] else self._send(200, None, STATE["ics"].encode())
        if self.path.endswith("/models"): return self._send(200, {"data": [{"id": "openai/gpt-oss-120b"}, {"id": "openai/gpt-oss-20b"}, {"id": "models/gemini-3.8-flash"}]})
        self._send(404, {})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.startswith("/redis"):
            op, k, a = body[0], body[1], body[2:]
            if op == "INCR": DB[k] = DB.get(k, 0) + 1; r = DB[k]
            elif op == "LPUSH": DB.setdefault(k, []).insert(0, a[0]); r = 1
            elif op == "LTRIM": DB[k] = DB.get(k, [])[int(a[0]):int(a[1]) + 1]; r = "OK"
            elif op == "LRANGE":
                l = DB.get(k, []); e = int(a[1]); r = l[int(a[0]):(None if e == -1 else e + 1)]
            elif op == "HSET": DB.setdefault(k, {}).update(zip(a[::2], a[1::2])); r = 1
            elif op == "HGET": r = DB.get(k, {}).get(a[0])
            elif op == "HMGET": r = [DB.get(k, {}).get(x) for x in a]
            elif op == "HGETALL": r = [x for kv in DB.get(k, {}).items() for x in kv]
            elif op == "SMEMBERS": r = []
            return self._send(200, {"result": r})
        STATE["llm"] += 1; STATE["last"] = body; STATE.setdefault("calls", []).append(body)
        self._send(200, {"choices": [{"message": {"content": "Good morning, my loves!"}}]})
srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk", GROQ_API_KEY="qk", GEMINI_API_KEY="gk", HUB_TIMEZONE="America/Denver",
                  REMI_CALENDAR_URLS=f"{base}/cal.ics", BIRTHDAYS=f"Sam:{(TODAY + timedelta(days=1)).strftime('%m-%d')}, Bad:13-40",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json", RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="t")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.ROUND_POSTS = "agents"  # these tests read each agent's own round post; test_rounds2 covers the summary
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}
from wsgiref.util import setup_testing_defaults
def call(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs,
           "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s, h=hd)))
    return int(got["s"][:3]), out, dict((k.lower(), v) for k, v in got["h"])
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
print("mode:", mode)

occ = h.calendar_events(TODAY, TODAY)
titles = [o["title"] for o in occ]
check("today: dentist (unescaped), no cancelled lunch", "Dentist, Dr. Lee" in titles and "Cancelled lunch" not in titles)
check("UTC event lands on the right local day", "Late call" in titles)  # 01:30Z tomorrow = 7:30pm today in Denver (UTC-6)
dent = [o for o in occ if o["title"].startswith("Dentist")][0]
check("times in hub timezone", h.occurrence_text(dent) == "9 AM–10 AM: Dentist, Dr. Lee (Main St)")
trip = [o for o in h.calendar_events(TODAY + timedelta(days=2), TODAY + timedelta(days=2)) if o["title"] == "Camping trip"]
check("multi-day all-day event shows on its middle day", len(trip) == 1 and h.occurrence_text(trip[0]) == "All day: Camping trip")
check("all-day end is exclusive", not [o for o in h.calendar_events(TODAY + timedelta(days=4), TODAY + timedelta(days=4)) if o["title"] == "Camping trip"])
two_weeks = h.calendar_events(monday, monday + timedelta(days=13))
soccer = [(o["title"], o["start"].date() - monday) for o in two_weeks if o["title"].startswith("Soccer")]
check("weekly Mon/Wed with an EXDATE and a moved occurrence", [(t, x.days) for t, x in soccer] == [("Soccer practice", 0), ("Soccer practice", 2), ("Soccer practice (moved)", 9)])
moved = [o for o in two_weeks if o["title"] == "Soccer practice (moved)"][0]
check("moved occurrence keeps its new time", h._clock(moved["start"]) == "6:30 PM")
pta = [o["start"].date() for o in h.calendar_events(TODAY.replace(day=1), TODAY.replace(day=1) + timedelta(days=150)) if o["title"] == "PTA meeting"]
check("monthly 2nd Tuesday, COUNT=3", len(pta) == 3 and all(x.weekday() == 1 and 8 <= x.day <= 14 for x in pta))
week = h.calendar_events(TODAY, TODAY + timedelta(days=7))
bdays = sorted(o["title"] for o in week if o["birthday"])
check("birthdays: yearly event 7 days out + BIRTHDAYS entry tomorrow; bad entry ignored", bdays == ["Grandma's birthday", "Sam's birthday"])

ctx = h.system_prompt("remi")
check("Remi's prompt carries the real calendar, other agents' don't", "Dentist, Dr. Lee" in ctx and "never change times" in ctx and "Dentist" not in h.system_prompt("glass"))

# round job
r = h.run_round(force=True)
check("Remi posts today's agenda", r["ran"]["remi"] == {"ok": True, "did": "posted today's agenda"})
post = [m for m in h.allchat_view() if m["from"] == "remi"][-1]["text"]
check("agenda: greeting, exact times, birthdays 1 and 7 days out", post.startswith("Good morning, my loves!") and "- 9 AM–10 AM: Dentist, Dr. Lee (Main St)" in post and "Coming up: Sam's birthday tomorrow." in post and "Coming up: Grandma's birthday in a week." in post and "Camping" not in post)
check("the greeting prompt forbids listing events", any("family agenda post" in c["messages"][-1]["content"] and "Don't list or mention any events" in c["messages"][-1]["content"] for c in STATE["calls"]))
r = h.run_round(force=True)
check("same day, same plans: quiet", r["ran"]["remi"]["did"] == "agenda unchanged")
STATE["ics"] = STATE["ics"].replace("SUMMARY:Dentist\\, Dr. Lee", "SUMMARY:Dentist moved?").replace("T090000", "T110000").replace("T100000", "T120000")
h._CAL_CACHE.clear(); [h.store().set_meta("snap:cal:" + h._snap_key(u), "") for u in h.REMI_CALENDAR_URLS]
r = h.run_round(force=True)
upd = [m for m in h.allchat_view() if m["from"] == "remi"][-1]["text"]
check("plans change: update posted", r["ran"]["remi"]["did"] == "posted an agenda update" and upd.startswith("Today's plans changed:") and "11 AM–12 PM: Dentist moved?" in upd)

# wiring + failure
w = {x["agent"]: x for x in h.wiring()}
check("wiring: calendar readable, not testable", w["remi-calendar"]["state"] == "ok" and w["remi-calendar"]["testable"] is False)
STATE["fail"] = True; h._CAL_CACHE.clear()
for u in h.REMI_CALENDAR_URLS:  # the stored copy has gone stale and a refresh runs (as the next page or tick would)
    k = "snap:cal:" + h._snap_key(u); snap = json.loads(h.store().get_meta(k)); snap["at"] -= 3600; h.store().set_meta(k, json.dumps(snap))
h.refresh_shared(); h._CAL_CACHE.clear()
check("a broken calendar keeps showing the last good copy for now", h.calendar_events(TODAY, TODAY) if "TODAY" in dir() else True)
w = {x["agent"]: x for x in h.wiring()}
check("wiring: unreadable link flagged", w["remi-calendar"]["state"] == "bad" and "REMI_CALENDAR_URLS" in w["remi-calendar"]["note"])
check("dashboard survives an unreadable calendar", call("GET", "/", "key=dk")[0] == 200)
STATE["fail"] = False; h._CAL_CACHE.clear()

# calendar page + cookie login
s, b, hd = call("GET", "/calendar", "key=dk"); page = b.decode()
check("calendar page: nav, month grid, today's dentist, list, birthday tag", s == 200 and 'href="/calendar" class="on"' in page and '<table class="cal">' in page and "Dentist moved?" in page and "birthday</span>" in page)
check("opening with ?key= sets a session cookie (not the key)", "hub_sess=" in hd.get("set-cookie", "") and "hub_key=dk" not in hd.get("set-cookie", "") and "HttpOnly" in hd["set-cookie"])
check("cookie alone opens pages and APIs", call("GET", "/calendar", headers={"cookie": "hub_key=dk"})[0] == 200 and call("GET", "/api/allchat", headers={"cookie": "hub_key=dk"})[0] == 200)
check("wrong cookie refused", call("GET", "/calendar", headers={"cookie": "hub_key=nope"})[0] == 401)
nxt = (TODAY.replace(day=1) + timedelta(days=32)).replace(day=1)
s, b, _ = call("GET", "/calendar", f"month={nxt:%Y-%m}", headers={"cookie": "hub_key=dk"})
check("month navigation", s == 200 and f"<h1>{nxt:%B %Y}</h1>" in b.decode())
check("bad month param falls back to this month", call("GET", "/calendar", "month=zzz", headers={"cookie": "hub_key=dk"})[0] == 200)
s, b, _ = call("GET", "/", "key=dk")
check("dashboard has the tabs", b'href="/calendar"' in b)
h.REMI_CALENDAR_URLS[:] = []; h.BIRTHDAYS[:] = []
s, b, _ = call("GET", "/calendar", headers={"cookie": "hub_key=dk"})
check("unlinked: setup instructions", b"Secret address in iCal format" in b)
check("unlinked: round says no calendar", h.run_round(force=True)["ran"]["remi"]["did"] == "no calendar linked")
