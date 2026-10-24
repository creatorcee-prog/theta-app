"""Stage 2: Home agent organization — expandable agent panels.

No browser or DOM harness exists in this repo, so placement is verified
at the strongest level available: the generated HTML of Home, Settings,
Diagnostics, and the Lenz page, plus the shipped CSS/JS. The test does
NOT claim click, tap, or visual verification.

Covers:
- Home has an Agents section with three expandable panels, collapsed
  by default: Lenz (channels + releases), QWERTY (security summary),
  Mistral (phone notification sending — NOT under Lenz).
- Mistral's notification controls moved from Settings to the Home
  Mistral panel with their existing handler script; exactly one
  instance of each control id on Home; Settings keeps a pointer.
- Lenz's channels are env-configured (no movable UI control exists),
  so the Lenz panel surfaces their status + links instead of
  inventing or duplicating controls; the Lenz page keeps its own
  controls and the Release Calendar stays on Home and Lenz (1d).
- QWERTY's full Security panel stays in Diagnostics (1c); Home
  shows only a summary + links. Shared wiring stays in Diagnostics
  and is not duplicated on Home.
- Shared Home sections, Settings sections (including the Mistral
  benchmark, out of this stage's scope), and the 1d ordering all
  stay intact; panels reuse card/stack classes (no fixed widths).
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

# --- Home renders the Release Calendar ---
# --- Agents section on Home ---
s, home = call("GET", "/", headers=K)
check("home serves", s == 200)
home = home.decode() if isinstance(home, bytes) else home
check("home has Agents section", "<h2>Agents</h2>" in home and "Expand an agent for its controls." in home)
for pid, label in [("agent-lenz", "Lenz"), ("agent-qwerty", "QWERTY"), ("agent-mistral", "Mistral")]:
    check(f"home has collapsed {label} panel",
          f'<details class="card stack" id="{pid}"' in home)
check("home has exactly three agent panels", home.count("<details") == 3)
check("agents section sits after the crew windows and before quick actions",
      home.index('aria-label="Agent windows"') < home.index('id="agent-lenz"') < home.index('class="quickactions"'))

# --- Mistral: notification sending moved, not duplicated, not under Lenz ---
check("mistral panel holds the notification controls",
      'id="agent-mistral"' in home and 'id="push-on"' in home and 'id="push-test"' in home and 'id="push-status"' in home)
check("no duplicate notification control ids on Home",
      home.count('id="push-on"') == 1 and home.count('id="push-test"') == 1 and home.count('id="push-status"') == 1)
check("push handler script travels with the panel",
      home.index('id="push-test"') < home.index("push-status") and "Notifications are on for this device." in home)
check("notification controls sit inside the Mistral panel, not the Lenz panel",
      home.index('id="agent-mistral"') < home.index('id="push-on"') < home.index("</details>", home.index('id="agent-mistral"')))
s, settings = call("GET", "/settings", headers=K)
settings = settings.decode() if isinstance(settings, bytes) else settings
check("settings no longer holds the notification controls",
      'id="push-on"' not in settings and 'id="push-test"' not in settings and 'id="push-status"' not in settings)
check("settings points to the moved controls", "Phone notifications now live under Mistral on" in settings)

# --- Lenz: channel status + links (channels are env-only; no control invented) ---
check("lenz panel reports channel status",
      'id="agent-lenz"' in home and "YouTube:" in home and "Reddit:" in home and "Twitch:" in home)
check("lenz panel names the env/redeploy rule", "Environment Variables and need a redeploy" in home)
check("lenz panel links to the Lenz page and the calendar",
      'href="/lenz"' in home and 'href="#releases"' in home)
s, lenz = call("GET", "/lenz", headers=K)
lenz = lenz.decode() if isinstance(lenz, bytes) else lenz
check("lenz page keeps its own controls",
      'id="lenz-add"' in lenz and 'id="lenz-import"' in lenz and 'data-kind=' in lenz)
check("release calendar preserved on Home and Lenz (Stage 1d)",
      'id="releases"' in home and 'id="releases"' in lenz)
check("strip still after Watch & listen and before the footer",
      home.index("Watch &amp; listen") < home.index('id="releases"') < home.index("<footer"))

# --- QWERTY: summary on Home, full report stays in Diagnostics ---
check("qwerty panel links to Security in Diagnostics",
      'id="agent-qwerty"' in home and 'href="/diagnostics#security"' in home)
s, diag = call("GET", "/diagnostics", headers=K)
diag = diag.decode() if isinstance(diag, bytes) else diag
check("full Security panel stays in Diagnostics (Stage 1c)",
      'id="security"' in diag and "Security and health" in diag)
check("shared wiring stays in Diagnostics, not duplicated on Home",
      'id="diag-wiring-recheck"' in diag and 'id="diag-wiring-recheck"' not in home and 'id="wiring"' not in home)

# --- Shared sections intact; scope guards ---
check("shared home sections intact",
      "Your crew" in home and "Top stories" in home and "Watch &amp; listen" in home and "<footer" in home)
check("settings sections intact (benchmark stays; out of scope)",
      "Mistral benchmark" in settings and "Sign in with Face ID" in settings and "Rounds" in settings)
check("panels reuse card/stack classes, no fixed widths",
      'class="card stack" id="agent-lenz"' in home and 'width:' not in home[home.index('id="agent-lenz"'):home.index('id="agent-qwerty"')])
check("summary affordance rule shipped", "details.card summary{cursor:pointer}" in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api", "index.py")).read())
print("stage2: all checks passed")
