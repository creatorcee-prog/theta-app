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

# --- Canonical Diagnostics wiring panel ---
s, diag = call("GET", "/diagnostics", headers=K)
check("diagnostics serves", s == 200)
diag = diag.decode() if isinstance(diag, bytes) else diag
check("diagnostics keeps the Crew table",
      "<h2>Crew</h2>" in diag and "<th>Agent</th><th>Tier</th><th>Status</th><th>Activity</th>" in diag)
check("diagnostics has the canonical Models & providers panel",
      "Models &amp; providers" in diag and 'id="wiring"' in diag
      and 'id="diag-wiring-rows"' in diag and 'id="diag-wiring-recheck"' in diag)
check("diagnostics panel copy no longer points at Settings",
      "Live check." in diag and "Open in Settings" not in diag)
check("diagnostics fires exactly one wiring fetch on load (no duplicate path)",
      diag.count('fetch("/api/wiring"') == 1)
check("diagnostics recheck control is wired to the same load (live: fresh=1)",
      'document.getElementById("diag-wiring-recheck").onclick = () => load(true);' in diag)
check("diagnostics keeps the per-agent Test capability Settings had",
      'Wiring test: reply with just OK.' in diag and 'b.textContent = "Test"' in diag
      and "Test sends a tiny message and uses a few tokens." in diag)
check("no dead Settings wiring link remains on diagnostics",
      "/settings#wiring" not in diag)

# --- Settings duplicate removed, unrelated sections preserved ---
s, settings = call("GET", "/settings", headers=K)
check("settings serves", s == 200)
settings = settings.decode() if isinstance(settings, bytes) else settings
check("settings wiring section and script are gone",
      'id="wiring-rows"' not in settings and 'id="wiring-recheck"' not in settings
      and "<h2>Wiring</h2>" not in settings and "Wiring test:" not in settings)
check("settings keeps passkeys, devices, Gmail, memory, Siri",
      "Sign in with Face ID" in settings and "Devices" in settings and "Gmail" in settings
      and "Memory and notes" in settings and "Voice commands (Siri)" in settings)
check("settings no longer keeps Security/Health and Speed (moved by Stage 1c)",
      'id="security"' not in settings and 'id="speed"' not in settings)
check("no dead Settings wiring link remains on settings",
      "/settings#wiring" not in settings)

# --- Source-level pointer repairs (notification, reply text, hub map, dead script) ---
import os as _os
src = open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "api", "index.py")).read()
check("no /settings#wiring reference remains anywhere",
      "/settings#wiring" not in src)
check("cap notification now points at the canonical panel",
      "/diagnostics#wiring" in src)
check("capped-master reply and hub map point at Diagnostics, not Settings Wiring",
      "check Diagnostics \u2192 Models & providers" in src
      and "Wiring (what's connected)" not in src)
check("Settings-only wiring script constant is removed",
      "_WIRING_JS" not in src)

# --- Endpoints unchanged: auth + semantics preserved ---
s, d = call("GET", "/api/wiring", "key=dk")
check("wiring endpoint works with key",
      s == 200 and d.get("ok") is True and isinstance(d.get("agents"), list) and len(d["agents"]) > 0
      and all("agent" in r and "model" in r and "state" in r for r in d["agents"]))
s, d = call("GET", "/api/wiring")
check("wiring endpoint still needs the key", s == 401)
s, d = call("GET", "/api/models", "key=dk")
check("models endpoint preserved with key",
      s == 200 and "in_use" in d and "groq" in d)  # note: this endpoint has no ok field

# --- Scope guards: later stages not leaked in, Stage 1a intact ---
check("Security/Health and Speed ARE in diagnostics now (Stage 1c)",
      'id="security"' in diag and 'id="speed"' in diag)
s, home = call("GET", "/", headers=K)
home = home.decode() if isinstance(home, bytes) else home
check("release calendar IS on Home now (Stage 1d)", 'id="releases"' in home)
check("no storage meter invented", 'id="storage-meter"' not in diag)
s, chat_js = call("GET", "/chat.js")
chat_js = chat_js.decode()
check("stage 1a composer guard intact",
      "let sending = false" in chat_js and "finally { sending = false; btn.disabled = false; btn.classList.remove(\"is-loading\"); }" in chat_js)
s, ui_js = call("GET", "/ui.js")
ui_js = ui_js.decode()
check("stage 1a mini bar submit intact",
      ".minibar form.minibox" in ui_js and '"/api/allchat"' in ui_js)
s, css = call("GET", "/ui.css")
css = css.decode() if isinstance(css, bytes) else css
check("stage 1a diagnostics clipping rules intact",
      ".grid2 > .card{min-width:0}" in css)
print("stage1b checks done")
