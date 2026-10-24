"""Regression test: Mistral's normal hub prompt must include the six
Phase 4 tools (web_search, fetch_page, task_create, task_list,
task_complete, task_note).

Guards the silent-failure mode where a failed tool_bridge import left
agents with only the original tools: the old `except ImportError:
BRIDGE_TOOLS = {}` fallback hid the failure, so Mistral reported the
original tools and nothing else. The ledger-execution checks run in
memory mode only: this file's fake Upstash does not implement SET/GET,
which the task ledger needs (production Upstash does)."""
import sys, json, threading, os, io
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
DB = {}


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
            else: r = None
            return self._send(200, {"result": r})
        self._send(200, {"choices": [{"message": {"content": "ok"}}]})


srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="glass:gk1,lenz:lk", GROQ_API_KEY="<redacted>", GEMINI_API_KEY="<redacted>",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g",
                  VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="<redacted>")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
from wsgiref.util import setup_testing_defaults


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


def call(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s, h=dict(hd))))
    return int(got["s"][:3]), (json.loads(out) if out[:1] in (b"{", b"[") else out), got["h"]


K = {"x-dashboard-key": "dk"}
SIX = ["web_search", "fetch_page", "task_create", "task_list", "task_complete", "task_note"]

check("bridge import is healthy, not the silent {} fallback", h.BRIDGE_IMPORT_ERROR is None)
check("BRIDGE_TOOLS holds all six tools", sorted(h.BRIDGE_TOOLS) == sorted(SIX))
p = h.tools_prompt("mistral")
for t in SIX:
    check(f"tools_prompt('mistral') lists {t}", f"ACTION: {t} |" in p)
d = h.desk_system("mistral")
for t in SIX:
    check(f"desk_system('mistral') lists {t}", f"ACTION: {t} |" in d)
if mode == "memory":
    out = h.run_actions("mistral", "ACTION: task_create | mistral tools probe")
    check("run_actions executes task_create", isinstance(out, str) and "Task created: mistral tools probe" in out)
    out = h.run_actions("mistral", "ACTION: task_list | open")
    check("run_actions executes task_list", "mistral tools probe" in out)
s, b, _ = call("GET", "/diagnostics", headers=K)
html = b.decode()
check("diagnostics page renders", s == 200)
check("diagnostics shows the Tools section", ">Tools<" in html)
check("diagnostics reports bridge import ok", "Import: ok" in html)
for t in SIX:
    check(f"diagnostics lists {t}", t in html)
print("done")
