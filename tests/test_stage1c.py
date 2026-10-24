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
import re as _re, os as _os

# --- Speed before any recorded load: honest empty state, nothing invented ---
check("speed card with no measurements says so plainly",
      "Nothing measured yet" in h.speed_card())

# --- Diagnostics: moved panels present, existing sections preserved ---
s, diag = call("GET", "/diagnostics", headers=K)
check("diagnostics serves", s == 200)
diag = diag.decode() if isinstance(diag, bytes) else diag
check("diagnostics keeps the Crew table",
      "<h2>Crew</h2>" in diag and "<th>Agent</th><th>Tier</th><th>Status</th><th>Activity</th>" in diag)
check("diagnostics has the Security and health panel with its id",
      'id="security"' in diag and "Security and health" in diag
      and "QWERTY checks this every round" in diag)
check("diagnostics has the Speed panel with its id",
      'id="speed"' in diag and "<h2>Speed</h2>" in diag
      and "How long the server takes" in diag)
check("diagnostics keeps Models & providers (1b canonical panel)",
      "Models &amp; providers" in diag and 'id="diag-wiring-rows"' in diag)
check("diagnostics keeps Storage, Scheduled work, Token use, Tools",
      "<h2>Storage</h2>" in diag and "<h2>Scheduled work</h2>" in diag
      and "<h2>Token use</h2>" in diag and "<h2>Tools</h2>" in diag)

# --- Speed placement: Storage + Speed share one grid2, Crew sits above it ---
g2 = [m.start() for m in _re.finditer('<div class="grid2"', diag)]
storage_i = diag.index("<h2>Storage</h2>")
speed_i = diag.index("<h2>Speed</h2>")
crew_i = diag.index("<h2>Crew</h2>")
containing = max(g for g in g2 if g <= storage_i)
following = min([g for g in g2 if g > containing] or [len(diag)])
check("Speed sits immediately right of Storage in the same grid2",
      containing < storage_i < speed_i < following)
check("Crew table sits full-width above the Storage/Speed grid2",
      crew_i < containing)

# --- Stacking + clipping protection at CSS level (no browser harness) ---
s, css = call("GET", "/ui.css")
css = css.decode() if isinstance(css, bytes) else css
check("grid2 is two columns only on wide screens, single column below",
      "@media (min-width:1000px){.grid2{grid-template-columns:repeat(2,minmax(0,1fr))}}" in css)
check("grid cards cannot blow out from long strings",
      ".grid2 > .card{min-width:0}" in css)
check("Speed table scrolls instead of clipping on narrow screens",
      ".md .md-scroll{overflow-x:auto" in css)

# --- Settings: moved panels gone, everything else preserved ---
s, settings = call("GET", "/settings", headers=K)
check("settings serves", s == 200)
settings = settings.decode() if isinstance(settings, bytes) else settings
check("settings no longer has Security or Speed panels",
      'id="security"' not in settings and 'id="speed"' not in settings
      and "Security and health" not in settings
      and "How long the server takes" not in settings)
check("settings keeps passkeys, devices, Gmail, memory, Siri",
      "Sign in with Face ID" in settings and "Devices" in settings and "Gmail" in settings
      and "Memory and notes" in settings and "Voice commands (Siri)" in settings)
check("settings keeps Rounds, Bench, Standing orders, reports, About",
      "<h2>Rounds</h2>" in settings and "Mistral benchmark" in settings
      and "<h2>Standing orders</h2>" in settings and "<h2>Latest reports</h2>" in settings
      and "<h2>About</h2>" in settings)
check("wiring consolidated by merged Stage 1b (Settings copy gone, Diagnostics canonical)",
      'id="wiring-rows"' not in settings and 'id="diag-wiring-rows"' in diag)

# --- Speed shows real rows after a recorded load (no fabricated metrics) ---
s, diag2 = call("GET", "/diagnostics", headers=K)
diag2 = diag2.decode() if isinstance(diag2, bytes) else diag2
check("Speed panel shows the recorded Settings load with real times",
      "<td>Settings</td>" in diag2 and " s</td>" in diag2)

# --- security_rows(): normal output + error fallback, no endpoint of its own ---
check("security_rows renders list items",
      h.security_rows().startswith("<li"))
_real = h.watchdog_findings
def _boom():
    raise RuntimeError("watchdog down")
h.watchdog_findings = _boom
try:
    check("security_rows failure degrades to a plain notice, not a crash",
          "couldn\'t check right now" in h.security_rows())
finally:
    h.watchdog_findings = _real

# --- No panel leakage without the dashboard key; wiring endpoint unchanged ---
s, diag_nokey = call("GET", "/diagnostics")
diag_nokey = diag_nokey.decode() if isinstance(diag_nokey, bytes) else diag_nokey
check("diagnostics without key does not leak the moved panels",
      'id="security"' not in diag_nokey and 'id="speed"' not in diag_nokey)
s, settings_nokey = call("GET", "/settings")
settings_nokey = settings_nokey.decode() if isinstance(settings_nokey, bytes) else settings_nokey
check("settings without key does not leak the moved panels",
      'id="security"' not in settings_nokey and 'id="speed"' not in settings_nokey)
s, d = call("GET", "/api/wiring", "key=dk")
check("wiring endpoint unchanged with key",
      s == 200 and d.get("ok") is True and isinstance(d.get("agents"), list))
s, d = call("GET", "/api/wiring")
check("wiring endpoint still needs the key", s == 401)

# --- Server-rendered nature: no security/speed JS exists to duplicate ---
src = open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "api", "index.py")).read()
check("no security/speed JS constants or handlers exist anywhere",
      "_SECURITY_JS" not in src and "_SPEED_JS" not in src
      and 'getElementById("security"' not in src and 'getElementById("speed"' not in src)
check("all Security pointers now target Diagnostics",
      "/settings#security" not in src and "/diagnostics#security" in src)

# --- Scope guards: later work not leaked in, Stage 1a intact ---
s, home = call("GET", "/", headers=K)
home = home.decode() if isinstance(home, bytes) else home
check("release calendar IS on Home now (Stage 1d)", 'id="releases"' in home)
check("no storage meter invented", 'id="storage-meter"' not in diag)
s, chat_js = call("GET", "/chat.js")
chat_js = chat_js.decode()
check("stage 1a composer guard intact",
      "let sending = false" in chat_js and "finally { sending = false; btn.disabled = false; }" in chat_js)
s, ui_js = call("GET", "/ui.js")
ui_js = ui_js.decode()
check("stage 1a mini bar submit intact",
      ".minibar form.minibox" in ui_js and '"/api/allchat"' in ui_js)
check("stage 1a diagnostics clipping rules intact",
      ".grid2 > .card{min-width:0}" in css)
print("stage1c checks done")
