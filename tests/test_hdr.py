"""HDR: Display P3 wide-gamut colors + high-dynamic-range highlight boost.

Progressive enhancement only: SDR rules are untouched, and the wide-gamut /
high-dynamic-range rules live inside media queries, so an SDR display sees
today's CSS. Visual proof needs a P3/XDR display; headless Chromium is sRGB,
so the browser tier pins the SDR look and that color(display-p3) parses.
"""
import sys, json, threading, os, re
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
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="lenz:lk", GEMINI_API_KEY="g", GROQ_API_KEY="q",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="t")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h

css = h._UI_CSS
js = h._UI_JS


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


# --- SDR rules are untouched ---
for name, t in h.THEMES.items():
    for m in ("light", "dark"):
        check("SDR base keeps the %s/%s hex accents" % (name, m),
              ("--accent:" + t[m]["accent"]) in css and ("--accent2:" + t[m]["accent2"]) in css)
check("SDR theta light accent precedes its P3 override",
      css.index("--accent:#5543e8") < css.index("color(display-p3 0.3035 0.2150 0.9823)"))

# --- P3 accents for every theme ---
p3vals = re.findall(r"color\(display-p3 ([0-9.]+) ([0-9.]+) ([0-9.]+)\)", css)
check("every P3 channel is in [0,1]", all(0 <= float(c) <= 1 for v in p3vals for c in v))
check("P3 accent count is 12 themes x (light + dark + auto-dark) x 2 accents + 4 Gemini stops",
      css.count("color(display-p3") == 76)
for name, t in h.THEMES.items():
    sel = ':root[data-theme="' + name + '"]'
    li = "--accent:" + h._p3(t["light"]["accent"]) + ";--accent2:" + h._p3(t["light"]["accent2"])
    dk = "--accent:" + h._p3(t["dark"]["accent"]) + ";--accent2:" + h._p3(t["dark"]["accent2"])
    check("P3 light + dark accents for " + name,
          ("@media (color-gamut:p3){" + sel + "{" + li + "}") in css
          and (sel + '[data-mode="dark"]{' + dk + "}") in css
          and ("@media (color-gamut:p3) and (prefers-color-scheme:dark){" + sel
               + ':not([data-mode="light"]){' + dk + "}}") in css)
check("theta P3 conversion is pinned (a matrix change fails loudly)",
      "color(display-p3 0.3035 0.2150 0.9823)" in css)

# --- Gemini stops in P3, same geometry and peak alphas ---
gem_before = ("@media (color-gamut:p3){#bg-layer.bg-gemini::before{background-image:"
               "radial-gradient(50% 95% at 65% -10%,color(display-p3 0.0000 0.3675 0.9917 / .85),transparent 70%),"
               "radial-gradient(40% 85% at 30% -5%,color(display-p3 0.0000 0.8338 0.9671 / .55),transparent 70%)}")
gem_after = ("#bg-layer.bg-gemini::after{background-image:"
             "radial-gradient(45% 90% at 35% -10%,color(display-p3 0.0000 0.7375 0.4699 / .70),transparent 70%),"
             "radial-gradient(40% 80% at 15% -5%,color(display-p3 0.7547 0.5893 0.0000 / .85),transparent 70%)}")
check("Gemini P3 stops keep the Vivid geometry and alphas",
      gem_before in css and gem_after in css)
check("Gemini P3 block comes after the SDR Gemini rules",
      css.index("#bg-layer.bg-gemini::before{content") < css.index(gem_before))

# --- Dynamic-range highlight boost ---
check("dynamic-range block boosts Gemini curtains and liquid edge light",
      "@media (dynamic-range:high){" in css
      and "#bg-layer.bg-gemini::before,#bg-layer.bg-gemini::after{filter:brightness(1.12) saturate(1.2)}" in css
      and "rgba(255,255,255,.85)" in css and "rgba(255,255,255,.35)" in css)
check("dynamic-range block comes after the liquid rules it overrides",
      css.index(':root[data-glassstyle="liquid"] .card,') < css.index("@media (dynamic-range:high)"))
check("typing bloom still wins while typing (more specific selector intact)",
      "#bg-layer.bg-gemini.typing::before,#bg-layer.bg-gemini.typing::after{filter:brightness(1.4) saturate(1.25)}" in css)

# --- Shard blue tints switch to P3 on P3 displays ---
check("engine detects P3 and switches shard blue tints",
      'matchMedia("(color-gamut: p3)")' in js
      and "function tintB(a)" in js
      and '"color(display-p3 0.72 0.88 1 / " + a + ")"' in js
      and "tintB(0.04 + al * 0.18)" in js
      and "tintB(aa * 0.7 * depR)" in js)
check("no raw blue-tint call sites remain (only tintB's SDR fallback)",
      js.count("rgba(215,230,255,") == 1)

print("hdr: all checks passed")
