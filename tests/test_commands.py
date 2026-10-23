import sys, json, threading, os, io, time
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
T = datetime.now(ZoneInfo("America/Denver")).date()
ICS = "\r\n".join(["BEGIN:VCALENDAR", "BEGIN:VEVENT", "UID:a", f"DTSTART;TZID=America/Denver:{T + timedelta(days=1):%Y%m%d}T090000",
                   f"DTEND;TZID=America/Denver:{T + timedelta(days=1):%Y%m%d}T100000", "SUMMARY:Vet visit", "END:VEVENT", "END:VCALENDAR"])
DB, CALLS = {}, []
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj, raw=None):
        b = raw if raw is not None else json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/cal.ics": return self._send(200, None, ICS.encode())
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
        CALLS.append(body)
        self._send(200, {"choices": [{"message": {"content": "ok"}}]})
srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="lenz:lk", GROQ_API_KEY="qk", GEMINI_API_KEY="gk", GLASS_BUDGETS="Groceries:600",
                  REMI_CALENDAR_URLS=f"{base}/cal.ics", NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
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
K = {"x-dashboard-key": "dk"}
def cmd(text): return call("POST", "/api/allchat", headers=K, body={"text": text})
def last(sender): return [m for m in h.allchat_view() if m["from"] == sender][-1]
print("mode:", mode)
s, d = cmd("/commandeer Everyone check in by noon")
o = h.store().list_active_orders()
check("/commandeer: order from You; Theta acknowledges for the crew", s == 200 and d["command"] and "Acknowledged by Theta" in d["result"] and any(x["issued_by"] == "you" and x["request"] == "Everyone check in by noon" for x in o) and len(CALLS) == 1)
check("events: 'You used' and 'You issued'", [m["text"] for m in h.allchat_view() if m.get("kind") == "event"][-2:] == ["You used /commandeer Everyone check in by noon", f"You issued order #{o[0]['id']} to the whole crew: Everyone check in by noon"])
s, page = call("GET", "/settings", "key=dk")
check("settings lists the order with who it's for and from", f"#{o[0]['id']} to everyone (from You, until".encode() in page)
s, d = call("GET", "/api/orders", "bot_id=lenz", headers={"x-bot-key": "lk"})
check("bots see your order", any(x["request"] == "Everyone check in by noon" for x in json.loads(d)))
check("/commandeer without text: usage, nothing posted", cmd("/commandeer")[1] == {"ok": False, "error": "Usage: /commandeer [@agent ...] <order>"})
check("unknown command", "Unknown command /nope" in cmd("/nope")[1]["error"])
s, d = cmd("/agenda tomorrow")
check("/agenda tomorrow: Remi posts it", s == 200 and last("remi")["text"].startswith("Tomorrow, ") and "9 AM–10 AM: Vet visit" in last("remi")["text"])
s, d = cmd("/spend 42.50 groceries at Costco")
check("/spend without $ works", s == 200 and last("glass")["text"] == "Logged $42.50 for Groceries (groceries at Costco). Groceries this month: $42.50 of $600.")
check("/spend junk: usage", cmd("/spend lots")[1]["error"].startswith("Usage: /spend"))
s, d = cmd("/budget"); check("/budget", "Groceries: $42.50 of $600 (7%)" in last("glass")["text"])
s, d = cmd("/chart spending"); check("/chart spending: Charter posts an image", last("charter")["image"].startswith("/chart/"))
s, d = cmd("/chart my daily spend"); check("/chart by words", last("charter")["text"].startswith("Daily spending"))
check("/chart nonsense: usage lists charts", "spending|daily|calendar|coverage|activity" in cmd("/chart zebras")[1]["error"])
s, d = cmd("/digest"); check("/digest: Mistral posts today's digest", last("mistral")["text"].startswith("Here's today") and "Vet visit" not in last("mistral")["text"])
n = len([m for m in h.allchat_view() if m["from"] == "mistral"]); cmd("/digest")
check("/digest can be re-run (not once-a-day)", len([m for m in h.allchat_view() if m["from"] == "mistral"]) == n + 1)
s, d = cmd("/news"); check("/news runs only the news trio", d["result"].startswith("Red, Blue and Gray: ") and "no new headlines" in d["result"])
s, d = cmd("/trending"); check("/trending runs Lenz", d["result"].startswith("Lenz "))
round_lines = [m["text"] for m in h.allchat_view() if m.get("kind") == "event" and m["text"].startswith("Round: ")]
check("partial rounds don't list 'no job yet'", all("no job yet" not in x for x in round_lines))
s, d = cmd("/summary"); check("/summary with nothing new", d["result"] == "No new reports to summarize.")
s, d = cmd("/status"); check("/status: Mistral posts what isn't wired", last("mistral")["text"].startswith("Status:") and "Phone notifications: not set up" in last("mistral")["text"])
s, d = cmd("/help"); helpt = last("hub")["text"]
check("/help lists every command", all(f"/{c['name']}" in helpt for c in h.COMMANDS))
s, d = cmd("/round"); check("/round runs everyone", d["result"].startswith(f"Ran {len(h.ROUND_JOBS)} agents"))
check("commands need the dashboard key", call("POST", "/api/allchat", body={"text": "/round"})[0] == 401)
s, d = call("POST", "/api/allchat", headers={"x-bot-key": "lk"}, body={"bot_id": "lenz", "text": "/commandeer take over"})
check("a bot typing /commandeer just posts text", s == 200 and d["messages"][-1]["text"] == "/commandeer take over" and not any(x["request"] == "take over" for x in h.store().list_active_orders()))
menu = h.menu_data()
check("menu data: all agents with tier/online, all commands", [a["id"] for a in menu["agents"]] == list(h.AGENTS) and menu["commands"][0]["name"] == "commandeer" and "task" in menu["commands"][0]["about"] and menu["commands"][1]["name"] == "project")
s, page = call("GET", "/chat", "key=dk")
check("menu embedded safely in the chat page", b"window.HUB_MENU = {" in page and b'id="chat-menu"' in page)
