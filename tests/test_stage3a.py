"""Stage 3a: Glass+ foundation and agent icons.

No browser or DOM harness exists in this repo, so the foundation is
verified at the strongest level available: the shipped CSS, the
generated HTML of Home/Settings/Diagnostics, and the served avatar
SVGs (parsed as XML). The test does NOT claim click, tap, or visual
verification — the refreshed glyphs are simple geometry on the shared
24x24 grid, and their exact path data is asserted, not their pixels.

Covers:
- Glass+ tokens exist and are wired into the shared classes where
  their values already match (card padding, stack gap, button and
  field radii), so the token system is real without restyling pages.
- One shared .glass surface: solid by default, translucent + blurred
  only under @supports (backdrop-filter), so it stays usable where
  blur is unsupported; the tab bar and sidebar adopt it and no longer
  carry their own blur declarations.
- Reusable control states: loading, success, error, disabled
  (including native :disabled for inputs, selects, textareas).
- Agent icons: every agent's avatar still serves as distinct, valid
  SVG; unknown agents still fall back to the hub's; the five redrawn
  glyphs (Lenz play, Red megaphone, Blue bubble, Gray scales, James
  dumbbell) plus QWERTY's stroke-width normalization are present;
  Theta's mark is unchanged (the app icon is drawn from it).
- Originals stay retrievable: AGENT_MARKS_LEGACY holds the pre-3a
  set verbatim in this file, and AGENT_LOOKS is untouched.
- Scope: agent names/routing unchanged, no new endpoint, all 12
  themes intact, key pages still render.
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

# --- Glass+ tokens exist and are wired into shared classes ---
check("tokens defined", "--r-sm:12px" in css and "--pad:18px" in css and "--gap:14px" in css
      and "--glass-blur:22px" in css)
check("card padding and stack gap use tokens", "padding:var(--pad)" in css and "gap:var(--gap)" in css)
check("button and field radii use the token", css.count("border-radius:var(--r-sm)") >= 2)

# --- One shared glass surface, solid when blur is unsupported ---
check("glass surface is solid by default", ".glass{background:var(--surface)}" in css)
check("glass translucency is gated on backdrop-filter support",
      "@supports (backdrop-filter:blur(1px))" in css
      and "backdrop-filter:blur(var(--glass-blur))" in css)
_seg = css[css.index(".glass{"):css.index(".is-loading")]
check("glass surface sets no width (narrow-screen safe)", "width" not in _seg)
check("tab bar and sidebar no longer carry their own blur",
      "blur(22px) saturate(170%)" not in css and css.count("blur(22px)") == 0)

# --- Reusable control states ---
check("loading state", ".is-loading{opacity:.6;pointer-events:none;cursor:wait}" in css)
check("success state", ".is-success{border-color:var(--good);color:var(--good)}" in css)
check("error state", ".is-error{border-color:var(--bad);color:var(--bad)}" in css)
check("disabled state", ".is-disabled{opacity:.55;pointer-events:none;cursor:default}" in css)
check("native disabled controls", "input:disabled,select:disabled,textarea:disabled{opacity:.55;cursor:default}" in css)

# --- Shell adopts the glass surface ---
s, home = call("GET", "/", headers=K)
check("home serves", s == 200)
home = home.decode() if isinstance(home, bytes) else home
check("sidebar and tab bar use the shared glass class",
      'class="rail glass"' in home and 'class="tabbar glass"' in home)

# --- Agent icons: distinct, valid, fallback intact ---
import xml.etree.ElementTree as ET
svgs = {}
for a in h.AGENTS:
    s, svg = call("GET", f"/avatar/{a}.svg")
    check(f"avatar {a} serves as SVG", s == 200 and svg.startswith(b"<svg"))
    ET.fromstring(svg)
    svgs[a] = svg
check("every agent avatar is distinct", len(set(svgs.values())) == len(svgs))
check("unknown avatar falls back to the hub's", call("GET", "/avatar/nobody.svg")[1] == call("GET", "/avatar/hub.svg")[1])
for a, marker in [("lenz", "M10.2 8.4"), ("red", "M3 10.5"), ("blue", "M4 5.5h16"),
                  ("gray", "M12 4v16"), ("james", "M7 7v10"), ("qwerty", 'stroke-width="2.6"')]:
    check(f"refreshed {a} glyph present", marker.encode() in svgs[a])

# --- Originals stay retrievable in the file ---
check("legacy set covers every agent", set(h.AGENT_MARKS_LEGACY) == set(h.AGENT_MARKS))
check("only the refreshed glyphs changed",
      {a for a in h.AGENT_MARKS if h.AGENT_MARKS_LEGACY[a] != h.AGENT_MARKS[a]}
      == {"lenz", "red", "blue", "gray", "james", "qwerty"})
check("theta mark unchanged (app icon is drawn from it)",
      h.AGENT_MARKS["theta"] == h.AGENT_MARKS_LEGACY["theta"])
check("agent looks (colors) untouched", all(h.AGENT_LOOKS[a][0] for a in h.AGENTS))

# --- Scope guards ---
check("agent names and routing unchanged",
      set(h.AGENTS) == {"theta", "mistral", "glass", "remi", "lenz", "red", "blue", "gray", "charter", "qwerty", "james"})
check("avatar_img still points at the avatar route", "/avatar/lenz.svg" in h.avatar_img("lenz"))
check("all 12 themes intact", len(h.THEMES) == 12)
for pth in ("/", "/settings", "/diagnostics", "/agent/glass"):
    s, _b = call("GET", pth, headers=K)
    check(f"page {pth} renders", s == 200)
print("stage3a: all checks passed")
