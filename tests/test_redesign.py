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
h.CHAT_MODE = "crew"  # these tests cover each agent answering (CHAT_MODE=crew); test_desk.py covers the front desk
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}

def call(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
from wsgiref.util import setup_testing_defaults
import urllib.error, xml.etree.ElementTree as ET
def call(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s, h=dict(hd))))
    return int(got["s"][:3]), (json.loads(out) if out[:1] in (b"{", b"[") else out), got["h"]
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
K = {"x-dashboard-key": "dk"}

# --- Phase 1 redesign: nav, mini bar, diagnostics, money donut ---
import re, subprocess, tempfile
from urllib.parse import quote

def page(path, qs="", headers=None):
    s, b, _ = call("GET", path, qs, headers=headers or K)
    assert s == 200, (path, s)
    return b.decode()

def tabbar_links(html):
    nav = html.split('<nav class="tabbar')[1].split("</nav>")[0]
    return re.findall(r'href="([^"]+)"', nav)

def rail_links(html):
    rail = html.split('<aside class="rail')[1].split("</aside>")[0]
    return re.findall(r'href="([^"]+)"', rail)

home = page("/")
check("bottom bar has exactly Home, Diagnostics, Settings",
      tabbar_links(home) == ["/", "/diagnostics", "/settings"])
rl = rail_links(home)
check("sidebar Sections still link Chat, Calendar, Money",
      "/chat" in rl and "/calendar" in rl and "/money" in rl)
check("mini chat bar on Home, above the tab bar, with a draft field",
      '<div class="minibar">' in home and '<form class="minibox" action="/chat"' in home
      and 'name="say"' in home and "hasminibar" in home)
check("mini bar suggestions fit Home",
      "/chat?say=" + quote("What's new today?") in home)
chat = page("/chat")
check("chat page keeps its full composer and has no mini bar",
      'id="chat-form"' in chat and '<div class="minibar">' not in chat
      and 'class="on"' not in chat.split('<nav class="tabbar')[1].split("</nav>")[0])
for p in ("/settings", "/money", "/calendar"):
    check(f"mini bar on {p}", '<div class="minibar">' in page(p))
_, css, _ = call("GET", "/ui.css")
check("mini bar chips hide while typing on small screens (CSS)",
      ".minibar:focus-within .minichips{display:none}" in css.decode())
s, b, _ = call("GET", "/chat", "say=hello%20there", headers=K)
check("?say= prefill reaches the chat composer as a draft, unsent",
      '"draft": "hello there"' in b.decode())

check("diagnostics needs the key", call("GET", "/diagnostics")[0] == 401)
d = page("/diagnostics")
for sec in ("Diagnostics", "Crew", "Storage", "Scheduled work", "Recent failures", "Token use",
            "Models &amp; providers", "diag-wiring-rows"):
    check(f"diagnostics has {sec}", sec in d)
check("diagnostics highlights its own tab",
      'href="/diagnostics" class="on"' in d)
check("diagnostics never claims unmeasured token use is healthy",
      "not tracked yet" in d)
def syntax_ok(src):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(src)
    r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
    os.unlink(f.name)
    return r.returncode == 0
bad = [i for i, js in enumerate(re.findall(r"<script>(.*?)</script>", d, re.S)) if not syntax_ok(js)]
check("diagnostics inline scripts parse", not bad)

h.GLASS_BUDGETS = {"Groceries": 50}
h.add_expense(60, "Groceries")
h.add_expense(40, "Dining")
m = page("/money")
check("money shows a spending donut reconciling with the header total",
      "$100.00 spent" in m and '<div class="donut">' in m and "Groceries" in m
      and "$60.00" in m and "$40.00" in m)
home2 = page("/")
check("home flags an over-budget category as needing attention",
      "Needs attention" in home2 and "over its $50 budget" in home2)
h.store().set_meta("round:failures", json.dumps({"red": "boom"}))
home3 = page("/")
check("home flags a failed round as needing attention",
      "Last round failed for" in home3)
check("diagnostics lists the failed round",
      "boom" in page("/diagnostics"))

# --- Phase 2: working notes carry started/elapsed/state ---
import time as _time
_now = _time.time()
h.store().set_meta("chat:working", json.dumps({"r1": {"agent": "mistral", "name": "Mistral", "step": "thinking",
    "at": _now, "started": _now - 30, "state": "working", "done": ["glass"]}}))
s, w, _ = call("GET", "/api/chat/working", "rid=r1", headers=K)
check("working endpoint reports agent, step, trail, elapsed and state",
      s == 200 and w["agent"] == "mistral" and w["step"] == "thinking" and w["done"] == ["glass"]
      and w["state"] == "working" and 29 <= w["elapsed"] <= 120)
s, w, _ = call("GET", "/api/chat/working", "rid=nope", headers=K)
check("working endpoint returns just ok for an unknown rid",
      s == 200 and w == {"ok": True})
h._REQ.rid = "r2"
h.store().set_meta("chat:working", json.dumps({"r2": {"agent": "mistral", "name": "Mistral", "step": "",
    "at": _now, "started": 1000.0, "state": "working", "done": []}}))
h.working("theta", "pondering")
_note = json.loads(h.store().get_meta("chat:working"))["r2"]
check("working() keeps the first-seen start time across updates",
      _note["started"] == 1000.0 and _note["agent"] == "theta" and _note["step"] == "pondering"
      and _note["state"] == "working")
h.working_final("r2", "completed")
check("working_final marks completion",
      json.loads(h.store().get_meta("chat:working"))["r2"]["state"] == "completed")
h.working_final("r2", "bogus")
check("working_final ignores unknown states",
      json.loads(h.store().get_meta("chat:working"))["r2"]["state"] == "completed")
h.working_final("nope", "completed")
check("working_final on a missing note is a no-op", True)
_, chatjs, _ = call("GET", "/chat.js")
check("chat.js resumes a pending reply after refresh and shows elapsed time",
      b"theta-pending-rid" in chatjs and b"chat-working-elapsed" in chatjs and b"still working" in chatjs)
print("done")
