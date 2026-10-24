"""Stage 1d: Release Calendar on Home.

No browser or DOM harness exists in this repo, so placement is verified
at the strongest level available: the generated HTML of both pages,
the shared release_strip() source, and the shipped CSS/JS. The test
does NOT claim click, tap, or visual verification.

Covers:
- Home renders the Release Calendar (the existing release_strip()).
- Lenz still renders the same calendar, unchanged.
- Both placements use the same component and data path (no second
  implementation, no new endpoint, no extra fetch).
- No duplicate IDs: exactly one #releases per page; the filter script
  scopes to its own page's strip.
- Existing Home sections (Your crew, Top stories, Watch & listen,
  footer) and Lenz sections stay intact; the strip sits after
  Watch & listen and before the footer.
- Responsive safeguards: the strip reuses the existing card + rstrip
  horizontal scroller (overflow-x:auto), so it cannot clip or
  overflow on narrow screens.
- Scope guards: nothing else moved (Security/Speed stay in
  Diagnostics, not Home).
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
s, home = call("GET", "/", headers=K)
check("home serves", s == 200)
home = home.decode() if isinstance(home, bytes) else home
check("home renders the Release Calendar",
      'id="releases"' in home and "Release calendar" in home)
check("home strip is the existing card component",
      '<section class="card stack rcal" id="releases">' in home)
check("home strip sits after Watch & listen and before the footer",
      home.index("Watch &amp; listen") < home.index('id="releases"') < home.index('<footer class="foot"'))
check("home has exactly one releases strip (no duplicate id)",
      home.count('id="releases"') == 1)

# --- Lenz keeps the same calendar ---
s, lenz = call("GET", "/lenz", headers=K)
check("lenz serves", s == 200)
lenz = lenz.decode() if isinstance(lenz, bytes) else lenz
check("lenz still renders the Release Calendar",
      'id="releases"' in lenz and "Release calendar" in lenz)
check("lenz has exactly one releases strip",
      lenz.count('id="releases"') == 1)


def strip_of(page):
    i = page.index('id="releases"')
    start = page.rindex("<section", 0, i)
    return page[start:page.index("</section>", i) + len("</section>")]


check("home and lenz render the identical strip (same component, same cache)",
      strip_of(home) == strip_of(lenz))

# --- Same component / data path, no second implementation ---
import os as _os
src = open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "api", "index.py")).read()
home_src = src[src.index("def home_page("):src.index("def chat_page(")]
_ls = src.index("def lenz_page(")
_nx = src.index("\ndef ", _ls + 1)
lenz_src = src[_ls:_nx]
check("home_page and lenz_page both call the existing release_strip()",
      "release_strip()" in home_src and "release_strip()" in lenz_src)
check("home does not refresh releases itself (cache path unchanged)",
      "refresh_releases" not in home_src)
check("release filter script makes no network calls",
      "fetch(" not in h._RELEASE_JS)
check("release filter script scopes to its own page strip",
      'getElementById("releases")' in h._RELEASE_JS)

# --- Responsive safeguards preserved ---
check("strip reuses the existing horizontal scroller (overflow-x:auto)",
      ".rstrip{display:flex" in src and "overflow-x:auto" in src)
check("strip card uses the existing card/stack conventions",
      ".rcal{margin-top:16px}" in src)

# --- Existing Home and Lenz behavior intact ---
check("home keeps Your crew, Top stories, Watch & listen",
      "Your crew" in home and "Top stories" in home and "Watch &amp; listen" in home)
check("home keeps the quick actions and footer",
      "Quick actions" in home and '<footer class="foot"' in home)
check("lenz keeps its header, KPIs, and log form",
      "Entertainment" in lenz and "Most beloved" in lenz and 'id="lenz-add"' in lenz)

# --- Scope guards: nothing else moved ---
check("Security/Speed stay in Diagnostics, not Home",
      'id="security"' not in home and 'id="speed"' not in home)
s, diag = call("GET", "/diagnostics", headers=K)
diag = diag.decode() if isinstance(diag, bytes) else diag
check("diagnostics still has Security and Speed",
      'id="security"' in diag and 'id="speed"' in diag)
print("done")
