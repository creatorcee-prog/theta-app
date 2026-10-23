import sys, json, threading, os, io, time
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer

GYM = {"calls": [], "proposed": 0, "down": False}
DB = {}
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _gym(self, method):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
        GYM["calls"].append((method, self.headers.get("Authorization"), body))
        if GYM["down"]: return self._send(500, {"error": "summary failed"})
        if self.headers.get("Authorization") != "Bearer gym-secret": return self._send(401, {"error": "unauthorized"})
        if method == "GET": return self._send(200, {"coach": "James", "summary": "Units: lb. Today: 2026-10-22 (Thu).\nLast session: Bench Press 185x5"})
        return self._send(200, {"outcome": "answered", "answer": "Bench is up 10 lb. Nice work!", "proposedChanges": GYM["proposed"]})
    def do_GET(self):
        if self.path == "/gym/api/hub": return self._gym("GET")
        self._send(404, {})
    def do_POST(self):
        if self.path == "/gym/api/hub": return self._gym("POST")
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.startswith("/redis"):
            op, k, a = body[0], body[1], body[2:]
            if op == "INCR": DB[k] = DB.get(k, 0) + 1; r = DB[k]
            elif op == "LPUSH": DB.setdefault(k, []).insert(0, a[0]); r = 1
            elif op == "LTRIM": DB[k] = DB.get(k, [])[int(a[0]):int(a[1]) + 1]; r = "OK"
            elif op == "LRANGE":
                l = DB.get(k, []); e = int(a[1]); r = l[int(a[0]):(None if e == -1 else e + 1)]
            elif op == "SMEMBERS": r = sorted(DB.get(k, set()))
            elif op == "HSET": DB.setdefault(k, {}).update(zip(a[::2], a[1::2])); r = 1
            elif op == "HGETALL": r = [x for kv in DB.get(k, {}).items() for x in kv]
            elif op == "HGET": r = DB.get(k, {}).get(a[0])
            elif op == "HMGET": r = [DB.get(k, {}).get(x) for x in a]
            return self._send(200, {"result": r})
        self._send(404, {})

srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk", GARAGE_GYM_URL=base + "/gym/", GARAGE_GYM_SECRET="gym-secret",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json", RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="t")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
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
K = {"x-dashboard-key": "dk"}
def chat(msgs): return call("POST", "/api/chat", headers=K, body={"agent": "james", "messages": msgs})
print("mode:", mode, h.STORAGE_MODE)

check("trailing slash trimmed from GARAGE_GYM_URL", h.GARAGE_GYM_URL == base + "/gym")
check("James is a manager from Garage Gym", h.role_of("james") == "manager" and h.agent_model("james") == "Garage Gym's coach model")
# agents list before any contact: James offline
ag = {a["bot_id"]: a for a in h.agent_statuses()}
check("James offline before contact", not ag["james"]["online"] and ag["james"]["model"] == "Garage Gym's coach model")

msgs = [{"role": "user", "content": "how's my bench?"}, {"role": "assistant", "content": "Up 5 lb."},
        {"role": "user", "content": "and squats?"}, {"role": "assistant", "content": "Flat."},
        {"role": "user", "content": "what should I change?"}]
s, b = chat(msgs); d = json.loads(b); method, auth, body = GYM["calls"][-1]
check("chat goes to Garage Gym with bearer secret", s == 200 and method == "POST" and auth == "Bearer gym-secret")
check("hub messages become question + history pairs", body == {"question": "what should I change?", "history": [{"question": "how's my bench?", "answer": "Up 5 lb."}, {"question": "and squats?", "answer": "Flat."}]})
check("reply passes through, labeled with Garage Gym", d["reply"] == "Bench is up 10 lb. Nice work!" and d["name"] == "James" and d["model"] == "Garage Gym's coach model")
GYM["proposed"] = 2; s, b = chat(msgs[-1:])
check("proposed changes point to the app", s == 200 and "James suggested 2 changes. Open Garage Gym" in json.loads(b)["reply"])
GYM["proposed"] = 0
s, b = call("GET", "/api/agents", "key=dk"); ag = {a["bot_id"]: a for a in json.loads(b)}
check("James online after answering", ag["james"]["online"])

h.GARAGE_GYM_SECRET = "wrong"; s, b = chat(msgs[-1:])
check("wrong secret -> 502 naming Garage Gym 401", s == 502 and b"Garage Gym returned 401" in b)
h.GARAGE_GYM_SECRET = ""; n = len(GYM["calls"]); s, b = chat(msgs[-1:])
check("unlinked -> 502 with setup hint, no call", s == 502 and b"set GARAGE_GYM_URL and GARAGE_GYM_SECRET" in b and len(GYM["calls"]) == n)
s, b = call("GET", "/", "key=dk")
check("unlinked home explains how to link", s == 200 and b"Link Garage Gym to see your training" in b)
h.GARAGE_GYM_SECRET = "gym-secret"

# Fitness card + cache
h._JAMES_CACHE.update(at=0.0, ttl=0, value=None)
n = len(GYM["calls"])
s, b = call("GET", "/agent/james", "key=dk"); page = b.decode()
check("James's page shows his training summary", s == 200 and "<h2>Training</h2>" in page and "Bench Press 185x5" in page)
check("James's page names his home and links his channel", "Manager · Garage Gym" in page and 'href="/chat?ch=gym"' in page)
call("GET", "/", "key=dk")
check("summary cached between loads", len([c for c in GYM["calls"][n:] if c[0] == "GET"]) == 1)
s, b = call("GET", "/api/widgets", "key=dk")
check("widgets include james", json.loads(b)["james"]["coach"] == "James")
GYM["down"] = True; h._JAMES_CACHE.update(at=0.0, ttl=0, value=None); h.store().set_meta("snap:gym:summary", "")  # forget the stored copy too
s, b = call("GET", "/", "key=dk")
check("Garage Gym down -> home still loads with hint", s == 200 and b"Garage Gym hasn&#x27;t answered yet" in b)
check("failure cached 1 min", h._JAMES_CACHE["ttl"] == 60)
GYM["down"] = False
s, b = call("POST", "/api/chat", headers=K, body={"agent": "remi", "messages": msgs[-1:]})
check("other agents unaffected (no GROQ key -> 502 Groq)", s == 502 and b"GROQ_API_KEY" in b)
s, b = call("GET", "/api/bots"); j = [x for x in json.loads(b) if x["bot_id"] == "james"][0]
check("/api/bots labels James's model as Garage Gym's", j["model"] == "Garage Gym's coach model")
