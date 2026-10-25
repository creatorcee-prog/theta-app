"""Backgrounds, distinct from themes (backgrounds PR).

A fifth theta_ui cookie segment (theme.mode.layout.glassstyle.bg,
default "theme") renders data-bg on the page; Settings offers
Theme, Shards, Stars, Black, and Gemini. The background is a
fixed layer behind all content, opaque, so it never fights the
color scheme: any theme works with any background. Shards is a
black canvas of drifting polygons that bounce off each other
and the walls, lit from the top-left; Stars is twinkling stars
on black; Black is plain black; Gemini is the slow drifting
aurora gradient from the Gemini app. Canvas modes draw one
frame immediately and animate with rAF (which pauses while
hidden); reduced motion freezes them.
"""
import sys, json, threading, os
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
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="tk")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h

css = h._UI_CSS
js = h._UI_JS
readme = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "README.md")).read()


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


# --- The cookie carries the background, defaulting to the theme ---
check("ui_prefs parses the fifth cookie segment",
      h.ui_prefs({"cookie": "theta_ui=theta.dark.grid.liquid.shards"}) == ("theta", "dark", "grid", "liquid", "shards"))
check("four-segment cookies default to the theme background",
      h.ui_prefs({"cookie": "theta_ui=theta.dark.grid.liquid"}) == ("theta", "dark", "grid", "liquid", "theme"))
check("no cookie defaults to the theme background",
      h.ui_prefs({}) == ("theta", "auto", "grid", "plus", "theme"))
check("an unknown background value defaults to the theme background",
      h.ui_prefs({"cookie": "theta_ui=theta.auto.grid.plus.neon"})[4] == "theme")

# --- The page renders the attribute the CSS and engine key on ---
for v in ("shards", "stars", "black", "gemini"):
    html = h.page({"cookie": "theta_ui=theta.auto.grid.plus." + v}, "T", "/", "<p>x</p>")
    check(f"page renders data-bg {v} from the cookie",
          f'data-bg="{v}"' in html)
html = h.page({}, "T", "/", "<p>x</p>")
check("page defaults to data-bg theme",
      'data-bg="theme"' in html)

# --- The layer sits behind content and hides for the theme ---
check("background layer is fixed, behind content, and click-through",
      "#bg-layer{position:fixed;inset:0;z-index:-1;pointer-events:none;overflow:hidden;background:#000}" in css)
check("theme background hides the layer",
      "#bg-layer.off{display:none}" in css)
check("an active background clears the body background (or Chromium\'s propagated body background would cover the layer)",
      ':root[data-bg]:not([data-bg="theme"]) body{background:transparent}' in css)
check("page pre-paints the html background for active backgrounds",
      'style="background:#000"' in h.page({"cookie": "theta_ui=theta.auto.grid.plus.shards"}, "T", "/", "<p>x</p>")
      and 'style="background:#000"' in h.page({"cookie": "theta_ui=theta.auto.grid.plus.gemini"}, "T", "/", "<p>x</p>")
      and 'style="background' not in h.page({}, "T", "/", "<p>x</p>"))
check("Gemini background is a slow drifting aurora gradient",
      "#bg-layer.bg-gemini{background-color:#000;background-image:radial-gradient(1500px 900px at 70% 10%,rgba(23,60,170,.12),transparent 70%),radial-gradient(1300px 800px at 10% 45%,rgba(16,185,129,.09),transparent 70%),radial-gradient(800px 500px at 85% 25%,rgba(124,58,237,.07),transparent 70%);animation:bgGemini 48s ease-in-out infinite alternate}" in css
      and "@keyframes bgGemini" in css)
check("reduced motion freezes the Gemini drift",
      "@media (prefers-reduced-motion: reduce){#bg-layer.bg-gemini{animation:none}}" in css)

# --- The engine: canvas modes, collisions, live swap, reduced motion ---
check("engine builds the layer and watches the background attribute",
      'layer.id = "bg-layer"' in js
      and 'root.dataset.bg' in js
      and 'attributeName === "data-bg"' in js)
check("engine draws shards with wall and shard collisions",
      "initShards" in js and "drawShards" in js
      and "Math.hypot(dx, dy)" in js
      and "a.vx -= p * nx" in js)
check("engine draws twinkling stars",
      "initStars" in js and "drawStars" in js
      and "Math.sin(t * st.s + st.p)" in js)
check("shards render real 3D glass first (raw WebGL, no library), 2D canvas as fallback",
      "getContext(\"webgl\"" in js and "DEPTH_TEST" in js and "TRIANGLES" in js
      and "data-engine" in js and "initShards3D" in js and "dispose3D" in js and "ensure3D" in js)
check("shards are many small bright fragments that glint as they tumble",
      "initShards" in js and "drawShards" in js
      and "W * H / 1800" in js
      and "rnd(2.5, 4)" in js and "rnd(1, 2.5)" in js
      and "rnd(-.5, .5)" in js and "rnd(.85, 1)" in js
      and "Math.pow(Math.random(), 0.6)" in js
      and "Math.random() < 0.75" in js
      and "rnd(1.5, 3)" in js and "rnd(3, 4.5)" in js and "Math.pow(Math.random(), 0.35)" in js and "a.r < 2.5" in js and "0.01 + al * 0.04" in js
      and "Math.sin(sh.rot * 2 + sh.p)" in js
      and 'rgba(215,230,255,' in js and 'rgba(255,255,255,' in js
      and "TINTS" not in js
      and "addColorStop" in js
      and "d *= 0.45" in js and "rnd(.8, 1.4)" in js and "0.35 + 0.65 * lit" in js and "1.0 + sh.z / 300.0" in js
      and "rnd(120, 250)" in js and "rnd(-250, -100)" in js and "rnd(0.5, 0.9)" in js and "rnd(6, 8)" in js and "rnd(1.0, 1.5)" in js and "pl < 0.08 && cluster" in js and "d *= 0.35" in js and "sh.z > 100 ? 0.5" in js and "slice(0, 320)" in js and "massPts" in js and "gl.POINTS" in js and "gl_PointSize" in js and "smoothstep(0.15, 0.0" in js and "smoothstep(-0.15, 0.15, rp.y)" in js and "sin(3.0 * ang" in js and "rimBand" in js and "rnd(1.6, 3.2)" in js and "attribute float aZ" in js and "(massPts.length + fgPts.length) * 7" in js and "fgPts" in js and "rnd(2.0, 3.7)" in js and "rimG" in js and "Math.sin(3 * a" in js and "smoothstep(1.0, 0.55, dd) * 0.8" in js and "mp.s * 5 * pts.dpr" in js and "rp.y * 5.0" in js and "(massPts.length + fgPts.length) * 7" in js and "ctx.ellipse" in js and "W * H / 750" in js and "(0.8 + Math.pow(Math.random(), 0.3) / 5)" in js and "/ 3 * 0.6" in js and "H * 0.3" in js and "Math.random() + Math.random() + Math.random()" in js and "H * 0.2" in js
      and "OES_standard_derivatives" in js and "vBary" in js and "edgeGlow" in js and "pow(nl, 4.0)" in js and "0.35 + fres * 0.45" in js and "(0.16 + fres * 0.6)" in js and "0.04 + al * 0.18" in js
      and "al * 0.35" in js and "7 + Math.floor(Math.random() * 5)" in js)
check("engine animates with rAF and freezes under reduced motion",
      "requestAnimationFrame" in js
      and 'matchMedia("(prefers-reduced-motion: reduce)")' in js
      and "if (!reduced) raf = requestAnimationFrame" in js)
check("the UI script saves the background as the fifth cookie segment",
      '[root.dataset.theme, root.dataset.mode, root.dataset.layout, (root.dataset.glassstyle || "plus"), (root.dataset.bg || "theme")].join(".")' in js)

# --- Settings offers the choice ---
settings = h.settings_page({})
check("settings offers all five backgrounds",
      all(f'data-pref="bg" data-val="{v}"' in settings
          for v in ("theme", "shards", "stars", "black", "gemini")))

# --- The README documents the option ---
check("README documents backgrounds as separate from themes",
      "## Backgrounds" in readme and "data-bg" in readme
      and "Shards" in readme and "Gemini" in readme)

print("backgrounds: all checks passed")
