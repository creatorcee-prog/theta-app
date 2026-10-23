import sys, json, threading, os, io, time
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
from email.utils import format_datetime
from datetime import datetime, timezone

SEEN, LLM_FAIL, DB = [], [None], {}
NOW = time.time()
def rss(title, items):
    body = "".join(f"<item><title>{t}</title><link>https://x/{abs(hash(t))}</link>"
                   f"<pubDate>{format_datetime(datetime.fromtimestamp(NOW - m * 60, timezone.utc))}</pubDate></item>"
                   for t, m in items)
    return f"<rss><channel><title>{title}</title>{body}</channel></rss>".encode()
FEEDS = {  # (title, minutes ago)
    "/a.xml": rss("Outlet A", [("BREAKING: Volcano Erupts Near Naples Italy Today", 10), ("A two", 300), ("A three", 300)]),
    "/b.xml": rss("Outlet B", [("Big Storm Hits Miami Florida Coast Tonight", 20), ("B two", 300)]),
    "/c.xml": rss("Outlet C", [("Miami Florida Storm Hits Coast With Winds", 30), ("C two", 300)]),
    "/d.xml": rss("Outlet D", [("Storm Slams Miami Florida Coast Overnight", 40), ("LIVE: Old Story Here Long Ago", 500)]),
    "/e.xml": rss("Outlet E", [("Live updates: Market Rally Lifts Dow Jones", 5)]),
}
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj, raw=None):
        b = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.endswith("/models"):
            if self.headers.get("Authorization") not in ("Bearer gk", "Bearer qk"): return self._send(401, {"error": "x"})
            ids = ["models/gemini-3.8-flash", "models/gemini-3.8-pro"] if "gemini" in self.path else ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
            return self._send(200, {"object": "list", "data": [{"id": i} for i in ids]})
        self._send(200, None, FEEDS.get(self.path, b"<rss/>"))
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.startswith("/redis"):
            op, k, a = body[0], body[1], body[2:]
            if op == "INCR": DB[k] = DB.get(k, 0) + 1; r = DB[k]
            elif op == "LPUSH": DB.setdefault(k, []).insert(0, a[0]); r = 1
            elif op == "LRANGE":
                l = DB.get(k, []); e = int(a[1]); r = l[int(a[0]):(None if e == -1 else e + 1)]
            elif op == "SADD": DB.setdefault(k, set()).update(a); r = len(a)
            elif op == "SMEMBERS": r = sorted(DB.get(k, set()))
            elif op == "LTRIM": DB[k] = DB.get(k, [])[int(a[0]):int(a[1]) + 1]; r = "OK"
            elif op == "HSET": DB.setdefault(k, {}).update(zip(a[::2], a[1::2])); r = 1
            elif op == "HGET": r = DB.get(k, {}).get(a[0])
            elif op == "HMGET": r = [DB.get(k, {}).get(x) for x in a]
            elif op == "HGETALL": r = [x for kv in DB.get(k, {}).items() for x in kv]
            return self._send(200, {"result": r})
        SEEN.append((self.path, self.headers["Authorization"], body))
        if LLM_FAIL[0] == "empty": return self._send(200, {"choices": [{"message": {"content": None, "reasoning": "hmm"}}]})
        if LLM_FAIL[0]: return self._send(LLM_FAIL[0], {"error": "x"})
        self._send(200, {"choices": [{"message": {"content": f"[{body['model']}] ok"}}]})

srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(BOT_KEYS="remi:rk,lenz:lk,theta:tk,x9:xk", BOT_NAMES="lenz:@lenz_bot", DASHBOARD_KEY="dk",
                  GEMINI_API_KEY="gk", NEWS_FEEDS=",".join(base + p for p in FEEDS),
                  ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json", RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
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
    return int(got["s"][:3]), out
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
K = {"x-dashboard-key": "dk"}; U = [{"role": "user", "content": "hello"}]
def chat(agent, msgs=U): return call("POST", "/api/chat", headers=K, body={"agent": agent, "messages": msgs})
print("mode:", mode, h.STORAGE_MODE)

# --- chat by agent
s, b = chat("mistral"); path, auth, req = SEEN[-1]; sysmsg = req["messages"][0]["content"]
check("Mistral -> gemini-3.8-flash", s == 200 and path == "/gemini" and auth == "Bearer gk" and req["model"] == "gemini-3.8-flash")
check("gemini thinking low", req.get("reasoning_effort") == "low")
check("Mistral persona prompt", sysmsg.startswith("You are Mistral, the Low Brain") and "Theta (High Brain)" in sysmsg)
check("reply names agent", json.loads(b)["name"] == "Mistral")
s, b = chat("theta"); path, _, req = SEEN[-1]
check("Theta stands in on gemini", s == 200 and path == "/gemini" and "isn't answering right now" in req["messages"][0]["content"] and "You are Theta, the High Brain" in req["messages"][0]["content"])
n = len(SEEN); s, b = chat("remi")
check("Remi without GROQ key -> 502", s == 502 and b"GROQ_API_KEY is not set" in b and len(SEEN) == n)
os.environ["GROQ_API_KEY"] = "qk"
s, b = chat("remi"); path, _, req = SEEN[-1]
check("Remi -> groq gpt-oss-120b, motherly, low reasoning", s == 200 and path == "/groq" and req["model"] == "openai/gpt-oss-120b" and "motherly" in req["messages"][0]["content"] and req.get("reasoning_effort") == "low")
s, b = chat("red"); req = SEEN[-1][2]
check("Red -> groq gpt-oss-20b, partisan + no invented facts", s == 200 and req["model"] == "openai/gpt-oss-20b" and "Republican" in req["messages"][0]["content"] and "never invent facts" in req["messages"][0]["content"])
check("unknown agent 400", chat("bob")[0] == 400)
check("old tier field 400", call("POST", "/api/chat", headers=K, body={"tier": "miner", "messages": U})[0] == 400)
check("chat needs key", call("POST", "/api/chat", body={"agent": "red", "messages": U})[0] == 401)

# --- roles / names
check("theta is master by default", h.role_of("theta") == "master" and h.role_of("glass") == "manager")
check("names: agent, BOT_NAMES override, unknown", h.display_name("remi") == "Remi" and h.display_name("lenz") == "@lenz_bot" and h.display_name("zz") == "@zz")
s, _ = call("POST", "/api/commandeer", headers={"x-bot-key": "tk"}, body={"bot_id": "theta", "request": "go"})
check("theta may commandeer", s == 200)
s, _ = call("POST", "/api/commandeer", headers={"x-bot-key": "rk"}, body={"bot_id": "remi", "request": "go"})
check("remi may not commandeer", s == 403)

# --- status
check("status needs activity", call("POST", "/api/status", headers={"x-bot-key": "rk"}, body={"bot_id": "remi"})[0] == 400)
check("status needs bot key", call("POST", "/api/status", headers={"x-bot-key": "no"}, body={"bot_id": "remi", "activity": "x"})[0] == 401)
check("status ok", call("POST", "/api/status", headers={"x-bot-key": "rk"}, body={"bot_id": "remi", "activity": "  researching  "})[0] == 200)
call("POST", "/api/report", headers={"x-bot-key": "lk"}, body={"bot_id": "lenz", "event_type": "news", "payload": {"title": "Lenz pick"}})
s, b = call("GET", "/api/agents", "key=dk"); ag = {a["bot_id"]: a for a in json.loads(b)}
check("agents list", s == 200 and list(ag)[0] == "theta" and {"mistral", "glass", "remi", "lenz", "red", "blue", "gray", "charter", "x9"} <= set(ag))
check("remi online researching", ag["remi"]["online"] and ag["remi"]["activity"] == "researching" and ag["remi"]["tier"] == "Manager")
check("lenz online via report", ag["lenz"]["online"] and ag["lenz"]["activity"] == "online" and ag["lenz"]["name"] == "@lenz_bot")
check("theta online via commandeer, red offline", ag["theta"]["online"] and not ag["red"]["online"] and ag["red"]["activity"] == "offline")
check("goes offline after AGENT_ONLINE_SECONDS", not {a["bot_id"]: a for a in h.agent_statuses(now=time.time() + 700)}["remi"]["online"])
check("agents needs key", call("GET", "/api/agents")[0] == 401)
s, b = call("GET", "/api/bots"); bots = json.loads(b)
check("/api/bots lists agents", s == 200 and bots[0]["bot_id"] == "theta" and any(x["bot_id"] == "x9" for x in bots))

# --- news
br, top = h.news_items(now=NOW)
bt = [i["title"] for i in br]
check("breaking: flagged + 3-outlet story, max 2, newest first", bt == ["Live updates: Market Rally Lifts Dow Jones", "BREAKING: Volcano Erupts Near Naples Italy Today"])
h.NEWS_BREAKING_MAX = 5; br, top = h.news_items(now=NOW); bt = [i["title"] for i in br]
check("storm carried by 3 outlets is breaking, one per outlet", "Big Storm Hits Miami Florida Coast Tonight" in bt and sum("Storm" in t for t in bt) == 1)
check("old LIVE item outside window not breaking", all("Old Story" not in t for t in bt))
h.NEWS_BREAKING_MAX = 2; br, top = h.news_items(now=NOW)
tt = [i["title"] for i in top]
check("top: round-robin by rank, one copy per story, none from breaking", tt == ["Big Storm Hits Miami Florida Coast Tonight", "A two", "B two", "C two", "LIVE: Old Story Here Long Ago", "A three"])
h.NEWS_TOP = 3; _, top3 = h.news_items(now=NOW); h.NEWS_TOP = 8
check("top capped at NEWS_TOP", len(top3) == 3)

# --- dashboard + summary
s, b = call("GET", "/", "key=dk"); page = b.decode()
check("home: crew windows in order, breaking tag, bot-pushed items", s == 200 and "<h2>Your crew</h2>" in page and page.index('href="/agent/theta"') < page.index('href="/agent/lenz"') and '<span class="tag">Breaking</span>' in page and "Lenz pick" in page)
s, b = call("GET", "/api/widgets", "key=dk"); w = json.loads(b)
check("widgets news = breaking + top + bots", s == 200 and w["news"][0].get("breaking") and w["news"][-1]["title"] == "Lenz pick")
s, b = call("POST", "/api/summary", headers=K)
check("summary via Theta on gemini", s == 200 and "You are Theta" in SEEN[-1][2]["messages"][0]["content"] and SEEN[-1][0] == "/gemini")

# --- model upkeep
s, b = call("GET", "/api/models", "key=dk"); m = json.loads(b)
check("/api/models lists usable models per key", s == 200 and m["gemini"]["models"] == ["gemini-3.8-flash", "gemini-3.8-pro"] and "openai/gpt-oss-120b" in m["groq"]["models"] and m["in_use"]["low_brain"] == "gemini: gemini-3.8-flash")
check("/api/models needs key", call("GET", "/api/models")[0] == 401)
k = os.environ.pop("GROQ_API_KEY"); s, b = call("GET", "/api/models", "key=dk"); os.environ["GROQ_API_KEY"] = k
check("/api/models says which key is missing", json.loads(b)["groq"] == {"error": "GROQ_API_KEY is not set"})
check("gpt-oss gets reasoning_effort, other groq models don't", h.provider_extra("groq", "openai/gpt-oss-20b") == {"reasoning_effort": "low"} and h.provider_extra("groq", "llama-4-scout") == {})
LLM_FAIL[0] = "empty"; s, b = chat("mistral")
check("empty reply -> 502 explaining it", s == 502 and b"returned an empty reply" in b)
LLM_FAIL[0] = None
