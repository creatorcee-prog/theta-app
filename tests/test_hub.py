import sys, json, threading, os
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer

# Fake Upstash REST: POST JSON array command, returns {"result": ...}
DB = {}
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        assert self.headers["Authorization"] == "Bearer tok"
        c = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        op, k, a = c[0], c[1], c[2:]
        if op == "INCR": DB[k] = DB.get(k, 0) + 1; r = DB[k]
        elif op == "LPUSH": DB.setdefault(k, []).insert(0, a[0]); r = len(DB[k])
        elif op == "LRANGE":
            l = DB.get(k, []); e = int(a[1]); r = l[int(a[0]):(None if e == -1 else e + 1)]
        elif op == "LTRIM": DB[k] = DB.get(k, [])[int(a[0]):int(a[1]) + 1]; r = "OK"
        elif op == "HSET": DB.setdefault(k, {}).update(zip(a[::2], a[1::2])); r = 1
        elif op == "HGET": r = DB.get(k, {}).get(a[0])
        elif op == "HMGET": r = [DB.get(k, {}).get(x) for x in a]
        elif op == "HGETALL": r = [x for kv in DB.get(k, {}).items() for x in kv]
        elif op == "SMEMBERS": r = []
        b = json.dumps({"result": r}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

mode = sys.argv[1]
if mode == "redis":
    srv = HTTPServer(("127.0.0.1", 8799), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ.update(BOT_KEYS="m:k,x:y", BOT_ROLES="m:master,x:boss", DASHBOARD_KEY="dk",
                  NEWS_FEEDS="http://127.0.0.1:1/none.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/none.json")
if mode in ("redis", "down"):
    os.environ.update(UPSTASH_REDIS_REST_URL="http://127.0.0.1:%d" % (8799 if mode == "redis" else 1),
                      UPSTASH_REDIS_REST_TOKEN="tok")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
from wsgiref.util import setup_testing_defaults
import io

def call(method, path, qs="", headers=None, body=b""):
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs,
           "CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s, h=dict(hd))))
    return got["s"], got["h"]["Content-Type"], out

def check(name, cond): print(("PASS " if cond else "FAIL ") + name); assert cond

print("mode:", mode, "storage:", h.STORAGE_MODE)
if mode == "down":
    s, _, b = call("GET", "/", "key=dk"); check("storage down -> 500 not crash", s.startswith("500") and b"internal error" in b)
    sys.exit()
check("storage mode", h.STORAGE_MODE == ("upstash-redis" if mode == "redis" else "memory (not persistent)"))
s, _, _ = call("POST", "/api/report", headers={"x-bot-key": "k"}, body=b'{"bot_id":"m","event_type":"news","payload":{"title":"Hello"}}')
check("report ok", s.startswith("200"))
s, _, b = call("POST", "/api/commandeer", headers={"x-bot-key": "k"}, body=b'{"bot_id":"m","request":"go"}')
check("commandeer ok", s.startswith("200"))
oid = json.loads(b)["order_id"]
s, _, b = call("POST", f"/api/orders/{oid}/ack", headers={"x-bot-key": "y"}, body=b'{"bot_id":"x"}')
check("ack ok", s.startswith("200") and b'"x"' in b)
s, _, b = call("POST", "/api/commandeer", headers={"x-bot-key": "y"}, body=b'{"bot_id":"x","request":"go"}')
check("unknown role 'boss' cannot commandeer", s.startswith("403"))
s, _, _ = call("POST", "/api/summary"); check("summary needs key", s.startswith("401"))
s, _, b = call("POST", "/api/summary", headers={"x-dashboard-key": "dk"}); check("summary with key, no model key -> 502", s.startswith("502") and b"GEMINI_API_KEY is not set" in b)
s, _, b = call("GET", "/api/bots"); check("bots with unknown role", s.startswith("200") and b'"role": "miner"' in b)
for q in ("limit=abc", "limit=0", "limit=500"):
    s, _, _ = call("GET", "/api/feed", "key=dk&" + q); check("feed " + q + " -> 400", s.startswith("400"))
s, _, b = call("GET", "/api/feed", "key=dk&limit=5"); check("feed limit=5", s.startswith("200") and b"Hello" in b)
s, _, _ = call("GET", "/api/fitness", "key=dk&limit=x"); check("fitness bad limit -> 400", s.startswith("400"))
s, ct, b = call("GET", "/", "key=dk")
check("home utf-8", s.startswith("200") and ct == "text/html; charset=utf-8" and "Your crew".encode() in b)
s, _, b = call("GET", "/settings", "key=dk")
check("settings shows report + order", b"Hello" in b and f"#{oid} to everyone (from @m".encode() in b)
