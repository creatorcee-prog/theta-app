import sys, json, threading, os, io, time
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
from email.utils import format_datetime
from datetime import datetime, timezone
SEEN, DB, GYM = [], {}, {"summary": "Units: lb. Last: Bench 185x5", "gets": 0}
NOW = time.time()
def rss(title, items):
    body = "".join(f"<item><title>{t}</title><link>https://n/{abs(hash(t))}</link><pubDate>{format_datetime(datetime.fromtimestamp(NOW - 600, timezone.utc))}</pubDate></item>" for t in items)
    return f"<rss><channel><title>{title}</title>{body}</channel></rss>".encode()
FEEDS = {"/a.xml": rss("Outlet A", ["Senate Passes Budget Bill", "Storm Nears Coast"]),
         "/b.xml": rss("Outlet B", ["Markets Close Higher"]),
         "/ent.xml": rss("Movies Feed", ["Big Sequel Tops Box Office", "Indie Gem Arrives"]),
         "/red.xml": rss("Red Outlet", ["Senate Passes Budget Bill After Marathon Vote", "Border Story"]),
         "/blue.xml": rss("Blue Outlet", ["Climate Report Released"]),
         "/gray.xml": rss("Gray Outlet", ["What the Senate Budget Bill Passes Means for You", "Local Story"])}
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj, raw=None):
        b = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path in FEEDS: return self._send(200, None, FEEDS[self.path])
        if self.path == "/gym/api/hub": GYM["gets"] += 1; return self._send(200, {"coach": "James", "summary": GYM["summary"]})
        if self.path.endswith("/models"):
            return self._send(200, {"data": [{"id": "models/gemini-3.8-flash"}]} if "gemini" in self.path else {"data": [{"id": "openai/gpt-oss-20b"}, {"id": "openai/gpt-oss-120b"}]})
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
            elif op == "SADD": DB.setdefault(k, set()).update(a); r = 1
            elif op == "SMEMBERS": r = sorted(DB.get(k, set()))
            return self._send(200, {"result": r})
        SEEN.append((self.path, body))
        who = body["messages"][0]["content"].split(",")[0].replace("You are ", "")
        self._send(200, {"choices": [{"message": {"content": f"{who}'s take."}}]})
srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk", CRON_SECRET="cs", BOT_KEYS="lenz:lk,theta:tk,remi:rk", GEMINI_API_KEY="gk", GROQ_API_KEY="qk",
                  GARAGE_GYM_URL=base + "/gym", GARAGE_GYM_SECRET="gs", NEWS_FEEDS=f"{base}/a.xml,{base}/b.xml",
                  ENTERTAINMENT_FEEDS=f"{base}/ent.xml", NEWS_BREAKING_MAX="0",
                  RED_FEEDS=f"{base}/red.xml", BLUE_FEEDS=f"{base}/blue.xml", GRAY_FEEDS=f"{base}/gray.xml")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="t")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.list_models = h._list_models  # these tests swap keys mid-run; a deploy would start fresh
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}
from wsgiref.util import setup_testing_defaults
def call(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs,
           "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s)))
    return int(got["s"][:3]), json.loads(out) if out[:1] == b"{" else out
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
def thread(): return call("GET", "/api/allchat", "key=dk")[1]["messages"]
def events(): return [m["text"] for m in thread() if m.get("kind") == "event"]
print("mode:", mode, h.STORAGE_MODE)

# --- events from agent actions (no tokens)
call("POST", "/api/report", headers={"x-bot-key": "lk"}, body={"bot_id": "lenz", "event_type": "entertainment", "payload": {"title": "Dune 3 trailer"}})
esc = call("POST", "/api/escalate", headers={"x-bot-key": "lk"}, body={"bot_id": "lenz", "issue": "Feed is down"})[1]["escalation_id"]
oid = call("POST", "/api/commandeer", headers={"x-bot-key": "tk"}, body={"bot_id": "theta", "request": "All stop"})[1]["order_id"]
call("POST", f"/api/orders/{oid}/ack", headers={"x-bot-key": "rk"}, body={"bot_id": "remi"})
call("POST", "/api/fitness", headers={"x-bot-key": "lk"}, body={"bot_id": "lenz", "summary": {"steps": 9000}})
for _ in range(2): call("POST", "/api/status", headers={"x-bot-key": "rk"}, body={"bot_id": "remi", "activity": "checking the calendar"})
ev = events()
check("templated events for each agent action", ev == ["Lenz reported entertainment: Dune 3 trailer", f"Lenz escalated #{esc} to the Manager: Feed is down",
      f"Theta issued order #{oid}: All stop", f"Remi acknowledged order #{oid}", "Lenz posted a fitness summary", "Remi is now checking the calendar"])
check("events cost no tokens", SEEN == [])
check("events are marked as events in the thread", all(m["kind"] == "event" for m in thread()))
ctx = h.chat_line(thread()[0])
check("events reach agents' context as [event] lines", ctx == "[event] Lenz reported entertainment: Dune 3 trailer")

# --- round auth
check("round needs cron secret or dashboard key", call("POST", "/api/round", body={})[0] == 401 and call("POST", "/api/round", headers={"authorization": "Bearer wrong"}, body={})[0] == 401)

# --- first round (cron)
s, r = call("POST", "/api/round", headers={"authorization": "Bearer cs"}, body={})
check("cron round runs every job", s == 200 and set(r["ran"]) == set(h.ROUND_JOBS) and all(x["ok"] for x in r["ran"].values()) and r["no_job"] == [h.AGENTS[a]["name"] for a in h.AGENTS if a not in h.ROUND_JOBS])
msgs = thread()
by = {}
for m in msgs: by.setdefault(m["name"], []).append(m)
check("Theta summarized the new report into the thread", r["ran"]["theta"]["did"] == "summarized 1 report" and by["Theta"][-1]["text"].startswith("Summary of 1 new report:"))
takes = [by[n][-1]["text"] for n in ("Red", "Blue", "Gray")]
check("Red, Blue and Gray each take the same new story, with its link", len({t.split("\n")[1] for t in takes}) == 1 and all(t.split("\n")[1].startswith("https://n/") for t in takes))
news_reqs = [b for p, b in SEEN if "Today's top story" in b["messages"][-1]["content"]]
check("news prompt gives the headline and asks not to guess", len(news_reqs) == 3 and all("Senate Passes Budget Bill" in b["messages"][-1]["content"] and "say so instead of guessing" in b["messages"][-1]["content"] for b in news_reqs))
by_side = {b["messages"][0]["content"].split(",")[0].replace("You are ", ""): b["messages"][-1]["content"] for b in news_reqs}
check("Red and Gray see their own outlets' coverage", "- Red Outlet: Senate Passes Budget Bill After Marathon Vote" in by_side["Red"] and "- Gray Outlet: What the Senate Budget Bill Passes Means for You" in by_side["Gray"])
check("Blue is told its outlets haven't covered it", "None of your outlets have covered it yet" in by_side["Blue"])
check("round line says how many of each side's outlets covered it", "(1 of their outlets covered it)" in r["ran"]["red"]["did"] and "(their outlets haven't covered it)" in r["ran"]["blue"]["did"])
red_post = [m for m in msgs if m["name"] == "Red"][-1]["text"].split("\n")
check("Red's post links the story and his outlet's version", len(red_post) == 3 and red_post[1] != red_post[2])
check("Red's chat prompt carries his outlets' latest headlines; Blue's his", "Red Outlet: Border Story" in h.system_prompt("red") and "Blue Outlet: Climate Report Released" in h.system_prompt("blue") and "Border Story" not in h.system_prompt("blue"))
check("Lenz pitched a feed item", by["Lenz"][-1]["text"].startswith("Lenz's take.") and "Big Sequel" in r["ran"]["lenz"]["did"])
check("QWERTY posted the watchdog report in #dev-and-security (no tokens)", by["QWERTY"][-1]["text"].startswith("Watchdog")
      and by["QWERTY"][-1]["ch"] == "dev")
check("James noted new training numbers", "James checked your training: new numbers on the Fitness card." in events())
summary = [e for e in events() if e.startswith("Round: ")]
check("one Hub line sums up the round", len(summary) == 1 and (not r["no_job"] or ", ".join(r["no_job"]) + ": no job yet" in summary[0]) and msgs[-1]["name"] == "Hub")
ag = {a["bot_id"]: a for a in h.agent_statuses()}
check("agents that ran show online with what they did", ag["red"]["online"] and ag["red"]["activity"].startswith("posted a take on"))
check("later they show idle with last active time", "idle, last active" in {a["bot_id"]: a for a in h.agent_statuses(now=time.time() + 4000)}["red"]["activity"])

# --- second cron round right away: nothing due
n_events, n_calls = len(events()), len(SEEN)
s, r = call("POST", "/api/round", headers={"authorization": "Bearer cs"}, body={})
check("too soon: every job skipped, nothing posted, no tokens", r["ran"] == {} and len(r["skipped"]) == len(h.ROUND_JOBS) and len(events()) == n_events and len(SEEN) == n_calls)

# --- forced round from the dashboard: next story, unchanged things stay quiet
s, r = call("POST", "/api/round", qs="key=dk", body={"force": True})
check("forced round runs", s == 200 and len(r["ran"]) == len(h.ROUND_JOBS))
check("news moves on to the next unseen story", "Markets Close Higher" in r["ran"]["red"]["did"] or "Storm Nears Coast" in r["ran"]["red"]["did"])
check("Lenz moves on to the next item", "Indie Gem" in r["ran"]["lenz"]["did"])
check("unchanged wiring and training stay quiet", r["ran"]["qwerty"]["did"] in ("nothing new", "all quiet") and r["ran"]["mistral"]["did"] == "nothing new" and r["ran"]["james"]["did"] == "training unchanged" and r["ran"]["theta"]["did"] == "nothing new to summarize")

# --- failures are reported, not hidden, and retried next time
before = json.loads(h.store().get_meta("round:last"))
k = os.environ.pop("GROQ_API_KEY")
s, r = call("POST", "/api/round", qs="key=dk", body={"force": True})
os.environ["GROQ_API_KEY"] = k
after = json.loads(h.store().get_meta("round:last"))
check("missing Groq key: news miners fail, others fine", not r["ran"]["red"]["ok"] and "GROQ_API_KEY" in r["ran"]["red"]["did"] and r["ran"]["mistral"]["ok"])
check("failures named in the round line", "Red: failed (GROQ_API_KEY is not set" in [e for e in events() if e.startswith("Round: ")][-1])
qw = [m for m in h.allchat_view(200, channel="dev") if m["from"] == "qwerty"][-1]["text"]
check("QWERTY flags the new wiring problem", qw.startswith("Watchdog report") and "GROQ_API_KEY" in qw)
check("a failure doesn't count as a run; a success does", all(after[a] == before[a] for a in ("red", "blue", "gray")) and after["mistral"] > before["mistral"])
check("Lenz with nothing new succeeds without a model call", r["ran"]["lenz"] == {"ok": True, "did": "nothing new to pitch"})
h.DASHBOARD_KEY = ""
check("no dashboard key set: only the cron secret can run rounds", call("POST", "/api/round", body={"force": True})[0] == 401)
