"""Stage 1a: chat submission hardening + Diagnostics responsive clipping.

No browser or DOM harness exists in this repo, so the client-side
guard is verified at the strongest level available: the exact
JavaScript the server ships (/chat.js, /ui.js) plus the generated
HTML/CSS, and the WSGI request path the mini bar posts to. The test
does NOT claim click or tap verification.

Covers:
- Main composer: one explicit in-flight guard shared by button and
  keyboard submission (both funnel through form.onsubmit), released
  in a finally, with failure restore preserved.
- Mini bar: Send submits through /api/allchat (channel "all", same
  payload shape as the composer) with its own guard and failure
  feedback; the GET-to-/chat fallback stays for no-JS.
- Diagnostics layout: grid children can shrink, long words in table
  cells and card lists wrap, tables stay inside horizontal scrollers,
  and no later-stage move (wiring consolidation, Security/Speed
  relocation, release calendar) leaked into this PR.
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

# --- Main composer guard (shipped /chat.js) ---
s, chat_js = call("GET", "/chat.js")
check("chat.js serves", s == 200 and isinstance(chat_js, bytes))
chat_js = chat_js.decode()
check("composer has an explicit in-flight guard",
      "let sending = false" in chat_js and "if (sending) return" in chat_js)
check("guard is set before the send and released in a finally",
      "if (sending) return; sending = true" in chat_js
      and "finally { sending = false; btn.disabled = false; }" in chat_js)
check("button and keyboard share the guarded submit path",
      'form.onsubmit = async' in chat_js
      and 'form.requestSubmit()' in chat_js)
check("composer keeps failure restore + working poll + single image input",
      'setPic(image)' in chat_js and 'startWorking(rid' in chat_js
      and "Couldn't send: " in chat_js)

s, chat_html = call("GET", "/chat", headers=K)
check("chat page serves", s == 200)
chat_html = chat_html.decode() if isinstance(chat_html, bytes) else chat_html
check("composer markup: one form, send button, single image picker",
      '<form class="composer" id="chat-form">' in chat_html
      and 'id="chat-send"' in chat_html
      and 'id="chat-file" accept="image/*"' in chat_html
      and 'multiple' not in chat_html.split('id="chat-file"')[1].split('>')[0])

# --- Mini bar Send-submit (shipped /ui.js + home markup) ---
s, ui_js = call("GET", "/ui.js")
check("ui.js serves", s == 200 and isinstance(ui_js, bytes))
ui_js = ui_js.decode()
mb = ui_js[ui_js.index(".minibar form.minibox"):] if ".minibar form.minibox" in ui_js else ""
check("mini bar handler posts to the composer endpoint with channel all",
      '"/api/allchat"' in mb and 'channel: "all"' in mb)
check("mini bar has its own guard, released in a finally, with failure feedback",
      "let sending = false" in mb and "if (!text || sending) return" in mb
      and "finally { sending = false; send.disabled = false; }" in mb
      and "Couldn't send: " in mb)
check("mini bar keeps the pending-rid handoff so chat can resume working state",
      'theta-pending-rid' in mb)

s, home = call("GET", "/", headers=K)
check("home serves", s == 200)
home = home.decode() if isinstance(home, bytes) else home
check("mini bar markup: GET fallback kept, Send label, status element",
      '<form class="minibox" action="/chat" method="get"' in home
      and 'aria-label="Send"' in home and 'aria-label="Open chat"' not in home
      and 'class="minibar-status"' in home)

# --- Mini bar payload through the real endpoint ---
s, d = call("POST", "/api/allchat", headers=K,
            body={"text": "minibar probe", "channel": "all", "rid": "mb1"})
check("mini bar payload is accepted and the message is saved",
      s == 200 and d.get("ok") and
      any(m.get("from") == "you" and "minibar probe" in m.get("text", "") for m in d.get("messages", [])))
s, d = call("POST", "/api/allchat",
            body={"text": "minibar probe", "channel": "all", "rid": "mb2"})
check("unauthenticated mini bar post fails cleanly (JS shows the error)",
      s == 401 and not d.get("ok"))

# --- Diagnostics layout (served CSS + generated HTML) ---
s, css = call("GET", "/ui.css")
check("ui.css serves", s == 200 and isinstance(css, bytes))
css = css.decode()
check("grid children can shrink (the clip fix)",
      ".grid2 > .card{min-width:0}" in css)
check("long words wrap in table cells and card lists",
      ".tbl td{" in css and "overflow-wrap:break-word" in css
      and ".card li{overflow-wrap:break-word}" in css)
check("mini bar status line is styled",
      ".minibar-status{" in css)

s, diag = call("GET", "/diagnostics", headers=K)
check("diagnostics serves", s == 200)
diag = diag.decode() if isinstance(diag, bytes) else diag
check("diagnostics keeps all sections",
      all(t in diag for t in ["<h2>Crew</h2>", "<h2>Storage</h2>", "<h2>Scheduled work</h2>",
                               "<h2>Recent failures</h2>", "<h2>Token use</h2>", "<h2>Tools</h2>",
                               "Models &amp; providers"]))
check("every diagnostics table sits inside a horizontal scroller",
      diag.count("<table") == diag.count('class="scrollx"') + diag.count('class="md-scroll"')
      and diag.count("<table") == 5)

# --- Stage 1a scope guards: later stages must NOT be in this PR ---
s, settings = call("GET", "/settings", headers=K)
check("settings serves", s == 200)
settings = settings.decode() if isinstance(settings, bytes) else settings
# Superseded by Stage 1b (PR: diagnostics-wiring-consolidation): wiring IS
# consolidated now, so this guard asserts the new state instead of the old one.
check("wiring consolidated (Settings copy removed, Diagnostics canonical)",
      'id="wiring-rows"' not in settings and 'id="wiring-recheck"' not in settings
      and 'id="diag-wiring-rows"' in diag)
check("Security and Speed moved (in Diagnostics, not Settings) — Stage 1c",
      'id="security"' in diag and 'id="speed"' in diag
      and 'id="security"' not in settings and 'id="speed"' not in settings)
check("release calendar not yet moved (still off Home)",
      'id="releases"' not in home)
print("done")
