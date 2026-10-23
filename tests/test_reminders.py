import sys, json, threading, os, io, time
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
DB, CALLS = {}, []
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.endswith("/models"): return self._send(200, {"data": [{"id": "openai/gpt-oss-20b"}, {"id": "openai/gpt-oss-120b"}, {"id": "models/gemini-3.8-flash"}]})
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
            elif op == "HSET":
                h_ = DB.setdefault(k, {}); r = sum(1 for x in a[::2] if x not in h_); h_.update(zip(a[::2], a[1::2]))
            elif op == "HGET": r = DB.get(k, {}).get(a[0])
            elif op == "HMGET": r = [DB.get(k, {}).get(x) for x in a]
            elif op == "HGETALL": r = [x for kv in DB.get(k, {}).items() for x in kv]
            elif op == "SMEMBERS": r = []
            return self._send(200, {"result": r})
        CALLS.append(body)
        who = body["messages"][0]["content"].split(",")[0].replace("You are ", "")
        self._send(200, {"choices": [{"message": {"content": f"{who} will do it, within limits."}}]})
srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="glass:gk1,lenz:lk", GROQ_API_KEY="qk", GEMINI_API_KEY="gk",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g",
                  VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="t")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}
from wsgiref.util import setup_testing_defaults
def call(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s)))
    return int(got["s"][:3]), json.loads(out) if out[:1] in (b"{", b"[") else out
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
K = {"x-dashboard-key": "dk"}
def cmd(text): return call("POST", "/api/allchat", headers=K, body={"text": text})
print("mode:", mode)
from datetime import datetime, timedelta
tz = h.hub_tz()
NOW = datetime(2026, 10, 22, 7, 30, tzinfo=tz)  # a Thursday, 7:30 am
def P(text, now=NOW):
    r = h.parse_reminder(text, now)
    return r["what"], datetime.fromtimestamp(r["at"], tz).strftime("%a %H:%M"), r["repeat"], r["nag"]
def PD(text):
    r = h.parse_reminder(text, NOW)
    return r["what"], datetime.fromtimestamp(r["at"], tz).strftime("%Y-%m-%d %H:%M")
check("date with dashes and a time (the oil change bug)", PD("Oil change 1-22-2027 at 3pm") == ("Oil change", "2027-01-22 15:00"))
check("date alone -> 9 AM that day", PD("remind me oil change on 1/22/2027") == ("oil change", "2027-01-22 09:00"))
check("month names, ordinals, day-first", PD("oil change January 22nd, 2027") == ("oil change", "2027-01-22 09:00") and PD("dentist 22 Jan 2027 at 10:30") == ("dentist", "2027-01-22 10:30"))
check("no year and already past this year -> next year", PD("oil change jan 22") == ("oil change", "2027-01-22 09:00"))
check("ISO dates", PD("renew passport 2027-03-05") == ("renew passport", "2027-03-05 09:00"))
try:
    h.parse_reminder("oil change 1-22-2026", NOW); past = False
except ValueError as e:
    past = "already passed" in str(e)
check("a date that has passed is refused, not moved", past)
check("weekday beside a date doesn't fight it", PD("fri 1/22/2027 oil change") == ("oil change", "2027-01-22 09:00"))
check("8am every day ... until done", P("8am every day take my meds until done") == ("take my meds", "Thu 08:00", "daily", True))
check("time already passed today -> tomorrow", P("remind me to stretch at 7am") == ("stretch", "Fri 07:00", None, False))
check("in 20 min", P("in 20 min check the oven") == ("check the oven", "Thu 07:50", None, False))
check("in 2 hours", P("call mom in 2 hours") == ("call mom", "Thu 09:30", None, False))
check("tomorrow 9:15pm", P("tomorrow 9:15pm put the bins out") == ("put the bins out", "Fri 21:15", None, False))
check("24-hour clock", P("20:30 lock the door") == ("lock the door", "Thu 20:30", None, False))
check("weekday name, then weekly", P("fri 6pm pay rent weekly") == ("pay rent", "Fri 18:00", "weekly", False))
check("every monday", P("every monday at 9am standup notes") == ("standup notes", "Mon 09:00", "weekly", False))
sat = datetime(2026, 10, 24, 10, 0, tzinfo=tz)
check("weekdays skip the weekend", P("weekdays 8am vitamins", sat) == ("vitamins", "Mon 08:00", "weekdays", False))
check("'at 8' means the next 8 (am at 7:30)", P("at 8 water the plants")[1] == "Thu 08:00")
check("'at 8' after 8 am means 8 pm", P("at 8 water the plants", datetime(2026, 10, 22, 9, 0, tzinfo=tz))[1] == "Thu 20:00")
check("noon", P("noon lunch pills")[1] == "Thu 12:00")
check("tonight", P("tonight charge the car")[1] == "Thu 20:00")
check("numbers in the task aren't times", P("8am every day take 2 pills")[0] == "take 2 pills")
for bad, hint in (("take my meds", "When?"), ("8am", "What should"), ("13pm meds", "doesn't look right")):
    try:
        h.parse_reminder(bad, NOW); check(f"{bad!r} rejected", False)
    except ValueError as e:
        check(f"{bad!r} -> hint: {e}", hint in str(e))
# DST: a daily 8am stays 8am across the November change
r = h.parse_reminder("8am every day meds", datetime(2026, 10, 31, 9, 0, tzinfo=tz))
nxt = h._next_after(r, datetime.fromtimestamp(r["at"], tz))
check("daily stays at 8:00 across the DST change", datetime.fromtimestamp(r["at"], tz).hour == 8 and nxt.hour == 8 and nxt.date() == datetime(2026, 11, 2).date())

# --- tick: fire, repeat, nag, ack
PUSHED = []
h.notify = lambda title, body, url="/": PUSHED.append((title, body, url)) or 1
h.store().set_meta("reminders", "[]")
t0 = NOW.timestamp()
med = h.add_reminder("8am every day take my meds until done", NOW)
oven = h.add_reminder("in 20 min check the oven", NOW)
h.DIGEST_TIME = "23:59"
check("tick before anything's due sends nothing", h.run_tick(t0) == {"fired": [], "nagged": [], "digest": False} and not PUSHED)
res = h.run_tick(t0 + 31 * 60)  # 8:01
check("8:01: both fire (earliest first), pushed to the phone, opening the reminders", res["fired"] == ["check the oven", "take my meds"] and ("Remi", "Reminder: take my meds", "/agent/remi#reminders") in PUSHED)
rs = {r["what"]: r for r in h.reminders()}
check("the one-off is gone; the daily one moves to tomorrow 8:00 and waits for done",
      "check the oven" not in rs and datetime.fromtimestamp(rs["take my meds"]["at"], tz).strftime("%a %H:%M") == "Fri 08:00" and rs["take my meds"]["pending"])
PUSHED.clear()
check("10 min later: no nag yet", h.run_tick(t0 + 41 * 60)["nagged"] == [])
check("15 min later: nag", h.run_tick(t0 + 47 * 60)["nagged"] == ["take my meds"] and PUSHED[-1][1] == "Still to do: take my meds")
for k in range(10):
    h.run_tick(t0 + (47 + 15 * (k + 1)) * 60)
check(f"nags stop after REMINDER_NAG_MAX ({h.REMINDER_NAG_MAX})", sum(1 for p in PUSHED if p[1].startswith("Still")) == h.REMINDER_NAG_MAX)
h.ack_reminder(med["id"])
check("done: no longer pending, still repeats", not h.reminders()[0]["pending"] and h.reminders()[0]["repeat"] == "daily")
# a one-off "until done" stays until it's marked done
h.store().set_meta("reminders", "[]")
one = h.add_reminder("in 5 min take antibiotics until done", NOW)
h.run_tick(t0 + 6 * 60); h.run_tick(t0 + 7 * 60)
check("one-off until-done fires once, then waits", sum(1 for p in PUSHED if p[1] == "Reminder: take antibiotics") == 1 and h.reminders()[0]["pending"])
check("its line still renders", "take antibiotics" in h.reminder_line(h.reminders()[0]))
h.ack_reminder(one["id"])
check("marked done -> removed", h.reminders() == [])

# --- chat, commands, API
h.store().set_meta("reminders", "[]")
n = len(CALLS)
s, d = call("POST", "/api/allchat", headers=K, body={"text": "@remi remind me at 9pm every day to take my meds until done", "channel": "family"})
check("asking Remi sets it, with no model call", "I'll remind you" in d["messages"][-1]["text"] and len(CALLS) == n and h.reminders()[0]["nag"])
s, d = call("POST", "/api/allchat", headers=K, body={"text": "@remi remind me sometime about stuff", "channel": "family"})
check("vague request: Remi asks when", "When?" in d["messages"][-1]["text"] and len(h.reminders()) == 1)
h.run_tick(time.time() + 86400 * 2)
s, d = call("POST", "/api/allchat", headers=K, body={"text": "@remi took them", "channel": "family"})
check("'took them' marks the nagging one done", "Marked done: take my meds" in d["messages"][-1]["text"] and not h.reminders()[0]["pending"])
s, d = call("POST", "/api/allchat", headers=K, body={"text": "/remind tomorrow 10am dentist"})
check("/remind", s == 200 and "dentist" in d["result"] and len(h.reminders()) == 2)
s, d = call("POST", "/api/allchat", headers=K, body={"text": "/remind whenever"})
check("/remind without a time explains", s == 400 and "When?" in d["error"])
s, d = call("POST", "/api/allchat", headers=K, body={"text": "/reminders"})
check("/reminders lists them in #family", s == 200 and "Your reminders:" in d["messages"][-1]["text"] and d["messages"][-1]["ch"] == "family")
rid = [r for r in h.reminders() if r["what"] == "dentist"][0]["id"]
s, d = call("POST", "/api/allchat", headers=K, body={"text": f"/forget #{rid}"})
check("/forget", s == 200 and len(h.reminders()) == 1)
s, d = call("POST", "/api/reminders", headers=K, body={"text": "in 1 min stand up"})
check("API: add", s == 200 and d["line"].startswith(f"#{d['reminder']['id']} stand up"))
s, d = call("GET", "/api/reminders", headers=K)
check("API: list", s == 200 and len(d["reminders"]) == 2)
s, d = call("POST", f"/api/reminders/{d['reminders'][-1]['id']}/delete", headers=K)
check("API: delete", s == 200 and len(h.reminders()) == 1)
check("API: unknown -> 404", call("POST", "/api/reminders/999/done", headers=K)[0] == 404 and call("POST", "/api/reminders/x/zap", headers=K)[0] == 404)
check("API needs the key", call("GET", "/api/reminders")[0] == 401 and call("POST", "/api/reminders", body={"text": "x"})[0] == 401)
check("tick needs the cron secret or key", call("POST", "/api/tick")[0] == 401)
h.CRON_SECRET = "cs"
s, d = call("POST", "/api/tick", headers={"authorization": "Bearer cs"})
check("tick with the cron secret", s == 200 and "fired" in d)
s, page = call("GET", "/calendar", headers=K)
check("Calendar tab has the reminders card", b'id="reminders"' in page and b"take my meds" in page and b'id="rem-form"' in page)
check("Remi's prompt knows the reminders", "take my meds" in h.system_prompt("remi"))
h.DIGEST_TIME = "07:00"
h.store().set_meta("round:mistral:digest_day", "")
NOTES = []
real_notify = h.notify
h.notify = lambda title, body, url="/": NOTES.append((title, body)) or 1
h.news_items = lambda: ([], [])
h.add_reminder("8am every day take my meds until done", datetime(2026, 10, 23, 6, 0, tzinfo=tz))
d0 = datetime(2026, 10, 23, 6, 55, tzinfo=tz).timestamp()
check("tick before DIGEST_TIME: no digest", h.run_tick(d0)["digest"] is False and not [n for n in NOTES if n[0] == "Mistral"])
d1 = datetime(2026, 10, 23, 7, 2, tzinfo=tz).timestamp()
r1 = h.run_tick(d1)
mis = [n for n in NOTES if n[0] == "Mistral"]
check("tick after DIGEST_TIME sends the digest, with today's reminders", r1["digest"] is True and len(mis) == 1 and "reminder" in mis[0][1])
dig = [m for m in h.allchat_view() if m["from"] == "mistral"][-1]["text"]
check("digest lists reminders", "Reminders:" in dig and "take my meds" in dig)
check("only once a day", h.run_tick(d1 + 300)["digest"] is False and len([n for n in NOTES if n[0] == "Mistral"]) == 1)
check("the round sees it was sent", h.digest_due(datetime(2026, 10, 23, 13, 0, tzinfo=tz)) is False)
h.notify = real_notify
print("done")
