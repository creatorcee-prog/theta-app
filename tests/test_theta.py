import sys, json, threading, os, io, time
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta
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
            elif op == "SADD": DB.setdefault(k, set()).update(a); r = 1
            elif op == "SMEMBERS": r = sorted(DB.get(k, set()))
            return self._send(200, {"result": r})
        CALLS.append(body); last = body["messages"][-1]["content"]
        if "Escalation #" in last and "buy" in last: reply = "ORDER: Glass, cap Dining at $150 this month."
        elif "Escalation #" in last: reply = "Approved; carry on."
        elif "weekly review" in last or "this week's review" in last: reply = "A steady week.\nPriorities for next week:\n- Rest"
        else: reply = "ok"
        self._send(200, {"choices": [{"message": {"content": reply}}]})
srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="glass:gk1,mistral:mk1", GROQ_API_KEY="qk", GEMINI_API_KEY="gk", GLASS_BUDGETS="Dining:100",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
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
    return int(got["s"][:3]), json.loads(out) if out[:1] == b"{" else out
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
print("mode:", mode)
e1 = call("POST", "/api/escalate", headers={"x-bot-key": "mk1"}, body={"bot_id": "mistral", "issue": "Approve the new reminder schedule?"})[1]["escalation_id"]
e2 = call("POST", "/api/escalate", headers={"x-bot-key": "mk1"}, body={"bot_id": "mistral", "issue": "Should we buy a new dining table?"})[1]["escalation_id"]
h.add_expense(130, "Dining", "dinner")
r = h.run_round(force=True)["ran"]["theta"]
check("Theta decides both master escalations", r["ok"] and f"decided #{e1}" in r["did"] and f"ordered on #{e2}" in r["did"])
theta = [m["text"] for m in h.allchat_view() if m["from"] == "theta"]
check("decision posted", f"On #{e1}: Approved; carry on." in theta)
orders = h.store().list_active_orders()
check("ORDER: reply issues a commandeer order from Theta", any(o["issued_by"] == "theta" and o["request"] == "Glass, cap Dining at $150 this month." for o in orders) and f"On #{e2}: Glass, cap Dining at $150 this month." in theta)
check("order shows as an event", any(m["text"].startswith("Theta issued order #") for m in h.allchat_view() if m.get("kind") == "event"))
check("decided once", "decided" not in h.run_round(force=True)["ran"]["theta"]["did"])
real_dt = h.datetime
def sunday_shift(d):
    """Days to a Sunday that isn't today and is in today's month, so
    month totals still hold (from Oct 26 the next Sunday is November)."""
    ahead = (6 - d.weekday()) % 7 or 7
    return ahead if (d + timedelta(days=ahead)).month == d.month else -((d.weekday() + 1) % 7 or 7)
class Sunday(real_dt):
    @classmethod
    def now(cls, tz=None): return real_dt.now(tz) + timedelta(days=sunday_shift(real_dt.now(tz)))
h.datetime = Sunday
r1 = h.run_round(force=True)["ran"]["theta"]
facts_prompt = [c for c in CALLS if "this week's review" in c["messages"][-1]["content"]][-1]["messages"][-1]["content"]
r2 = h.run_round(force=True)["ran"]["theta"]
h.datetime = real_dt
check("Sunday: weekly review posted once", "posted the weekly review" in r1["did"] and "weekly review" not in r2["did"])
check("review prompt carries only real facts", "Use only these facts" in facts_prompt and "Spending this week: $130.00; over budget this month: Dining" in facts_prompt and "Open escalations:" in facts_prompt and "All Agents posts this week:" in facts_prompt)
review = [m["text"] for m in h.allchat_view() if m["from"] == "theta"][-1]
check("review posted with priorities", review.startswith("Weekly review (") and "Priorities for next week:" in review)
check("no reports and nothing else: the old wording stays", h.run_round(force=True)["ran"]["theta"]["did"] == "nothing new to summarize")
