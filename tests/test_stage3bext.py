"""Stage 3b extension: chat hierarchy, composer states, responsive audit.

Built on the merged Stage 3b (PR #56) per the GPT brief's Phase 2, after
its Phase 1 inspection. Small, restrained changes only:

- Message bodies get a line-length cap (76ch) so long replies stay
  readable on wide desktop layouts; no effect on narrow screens.
- The chat send button grows to a 44px touch target, scoped to
  #chat-send so the Home mini bar button is untouched.
- Verified-but-unchanged (documented, not re-implemented): the composer
  is pinned (flex column + scrolling .msgs + flex:none composer), the
  tab bar height already includes the safe-area inset (so the composer
  needs none), the scroll stick logic, and the failure path that
  restores unsent text. No stop/cancel button: the backend has no cancel
  endpoint, and the brief forbids simulating one.

No browser or DOM harness exists in this repo, so verification is at
the strongest level available: the shipped CSS, the served chat page
markup, and the shipped chat JS source. This test does NOT claim click,
tap, or visual verification.
"""
import sys, json, threading, os, io
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
DB = {}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.endswith("/models"):
            return self._send(200, {"data": [{"id": "openai/gpt-oss-20b"}, {"id": "openai/gpt-oss-120b"}]})
        self._send(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"] or 0)))
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
            else: r = None
            return self._send(200, {"result": r})
        return self._send(200, {"choices": [{"message": {"content": "Mini bar reply ok."}}]})


srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="lenz:lk", GEMINI_API_KEY="<redacted>", GROQ_API_KEY="<redacted>",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="<redacted>")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}
from wsgiref.util import setup_testing_defaults


def call(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs,
           "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items():
        env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s)))
    return int(got["s"][:3]), (json.loads(out) if out[:1] == b"{" else out)


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        if detail:
            print(str(detail)[-2000:])
        sys.exit(1)


K = {"x-dashboard-key": "dk"}
print("mode:", mode, h.STORAGE_MODE)

css = h._UI_CSS
js = h._CHAT_JS

# --- Line length: message bodies cap at 76ch on wide layouts ---
check("message body column carries the mbody class",
      'body.className = "mbody"' in js)
check("message bodies cap at 76ch", ".mbody{max-width:76ch}" in css)

# --- Composer: chat send button is a 44px touch target, scoped ---
check("chat send button is 44px", "#chat-send{width:44px;height:44px}" in css)
check("mini bar send button untouched (still 38px)",
      ".minibox .btn.send{width:38px;height:38px;" in css)

# --- Pinned composer + safe-area: verified structure, unchanged ---
check("thread is a flex column", ".thread{display:flex;flex-direction:column" in css)
check("messages scroll internally", ".msgs{flex:1;overflow-y:auto" in css)
check("composer is pinned (flex:none)",
      ".composer{position:relative;padding:8px 12px calc(10px + env(safe-area-inset-bottom) * 0);flex:none}" in css)
check("tab bar height already includes the safe-area inset",
      "--tabh:calc(60px + env(safe-area-inset-bottom))" in css)

# --- No simulated stop/cancel: no cancel endpoint is called ---
check("no cancel endpoint is simulated", "/api/chat/cancel" not in js)

# --- Stage 3b behavior preserved ---
check("own messages still carry the mine class", '(m.from === "you" ? " mine" : "")' in js)
check("send loading state intact",
      'btn.classList.add("is-loading")' in js and 'btn.classList.remove("is-loading")' in js)
check("send guard + finally intact",
      "if (sending) return" in js and "finally { sending = false; btn.disabled = false;" in js)
check("error state intact", 'classList.add("is-error")' in js)
check("code blocks still capped", "max-height:340px;overflow-y:auto" in css)

# --- Served chat page keeps its structure ---
s, chat = call("GET", "/chat", headers=K)
check("chat page serves 200", s == 200, chat[:200] if isinstance(chat, bytes) else chat)
body = chat.decode() if isinstance(chat, bytes) else str(chat)
for frag in ['id="chat-form"', 'id="chat-msg"', 'id="chat-send"', 'id="chat-working"',
             'id="chat-menu"', 'id="chat-file"', 'id="msgs"']:
    check("served chat page keeps " + frag, frag in body)

print("stage3bext: all checks passed")
