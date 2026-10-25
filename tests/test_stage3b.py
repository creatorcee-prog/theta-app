"""Stage 3b: Chat layout redesign on the Stage 3a Glass+ foundation.

No browser or DOM harness exists in this repo, so the redesign is
verified at the strongest level available: the shipped CSS, the
served chat page markup, and the shipped chat JS source. The test
does NOT claim click, tap, or visual verification.

Covers:
- Message hierarchy: own messages carry a mine class in render()
  and get a subtle accent tint; turns get more air while
  continuations stay tight.
- Scannability: long code blocks cap at 340px and scroll instead
  of dominating the thread.
- States reuse the 3a foundation: the send button shows
  .is-loading while a send is in flight (the existing disabled
  guard + finally reset are untouched), and the status line shows
  .is-error for send failures, partial agent failures, and failed
  action presses, cleared on the next send / clean result.
- Members drawer adopts the shared .glass surface (its own solid
  background removed, shadow and fixed positioning kept).
- Structure and semantics preserved: composer, working indicator,
  trail, day separators, mention menu, attach UI, submission guard,
  /api/allchat, /api/chat/press, /api/chat/working all intact.
- Scope: no attachment work (3c), no endpoint or routing changes,
  agent set and themes unchanged.
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
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="lenz:lk", GEMINI_API_KEY="gk", GROQ_API_KEY="qk",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="tk")
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

# --- Message hierarchy + spacing ---
check("turns get more air", ".msg{display:grid;grid-template-columns:minmax(0,1fr);padding:8px 16px 6px}" in css)
check("own messages carry a mine class in render()", '(m.from === "you" ? " mine" : "")' in js)
check("own messages are right-aligned glass bubbles",
      ".msg.mine .mbody{width:fit-content;max-width:min(76ch,85%);margin-left:auto;background:var(--surface);border-radius:20px;padding:10px 14px;overflow-wrap:anywhere}" in css
      and ".msg.mine .meta{display:none}" in css)
check("continuations stay tight", ".msg.cont{padding-top:1px}" in css)

# --- Scannability: long code blocks scroll ---
check("code blocks cap their height and scroll",
      "max-height:340px;overflow-y:auto" in css and ".md pre{" in css)

# --- Composer uses the Glass+ radius token (value-identical) ---
check("composer radius uses the token", "border-radius:var(--r);padding:5px 5px 5px 14px" in css)

# --- Send + error states reuse the 3a foundation ---
check("send shows the loading state", 'btn.classList.add("is-loading")' in js and 'btn.classList.remove("is-loading")' in js)
check("send still disables + resets via finally",
      'btn.disabled = true' in js and 'finally { sending = false; btn.disabled = false; btn.classList.remove("is-loading"); }' in js)
check("failures show the error state",
      js.count('classList.add("is-error")') >= 2 and 'status.classList.toggle("is-error", errs.length > 0)' in js)
check("error state clears on next send / clean result", 'status.classList.remove("is-error")' in js)

# --- Members drawer adopts the shared glass surface ---
s, chat = call("GET", "/chat", headers=K)
check("chat serves", s == 200)
chat = chat.decode() if isinstance(chat, bytes) else chat
check("members drawer uses the glass class", 'class="members glass"' in chat)
_seg = css[css.index(".members.open{"):css.index("}", css.index(".members.open{"))]
check("drawer no longer sets its own solid background", "background" not in _seg)
check("drawer keeps its shadow and fixed positioning", "position:fixed" in _seg and "box-shadow" in _seg)

# --- Structure preserved (meaningful, not just class names) ---
for frag in ['id="chat-form"', 'id="chat-msg"', 'id="chat-send"', 'id="msgs"', 'id="chat-working"',
             'id="chat-status"', 'id="chat-menu"', 'class="members glass"', 'class="chans"']:
    check(f"chat keeps {frag}", frag in chat)
# --- Chat top removed (header row + channel chiprow) by owner request ---
check("chathead removed", 'class="chathead"' not in chat)
check("chiprow removed", 'class="chiprow"' not in chat)
check("members button removed", 'id="members-btn"' not in chat)
check("day separators kept", "daysep" in js)
check("agent trail kept", 'className = "trail"' in js)
check("working indicator kept", 'id="chat-working-done"' in chat and "wdots" in chat)

# --- Submission semantics + endpoints untouched ---
for frag in ["form.onsubmit", "if (sending) return", "/api/allchat", "/api/chat/press", "/api/chat/working"]:
    check(f"chat keeps {frag}", frag in js)

# --- Attach UI untouched (3c work, not this PR) ---
check("attach UI intact", 'id="chat-file"' in chat and 'id="chat-attach"' in chat)

# --- Narrow-screen structure kept ---
check("chat grid stays flexible", ".chat{display:grid;grid-template-columns:minmax(0,1fr)" in css)
check("two-column message grid is gone", "grid-template-columns:40px minmax(0,1fr)" not in css)

# --- Scope guards ---
check("agent set unchanged",
      set(h.AGENTS) == {"theta", "mistral", "glass", "remi", "lenz", "red", "blue", "gray", "charter", "qwerty", "james"})
check("all 12 themes intact", len(h.THEMES) == 12)
for pth in ("/", "/settings", "/diagnostics"):
    s, _b = call("GET", pth, headers=K)
    check(f"page {pth} renders", s == 200)
print("stage3b: all checks passed")
