"""Liquid Glass option for the Glass UI (presentation PR).

A fourth theta_ui cookie segment (theme.mode.layout.glassstyle,
default "plus") renders data-glassstyle on the page; Settings
swaps Glass+ and Liquid Glass live. Liquid restyles the .glass
surfaces and own-message bubbles with a specular gloss,
stronger blur, and edge light from inset shadows only -- never
borders, so bubbles stay borderless. It does not touch the
Aurora theme's separate bare data-glass treatment.
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


# --- The cookie carries the glass style, defaulting to Glass+ ---
check("ui_prefs parses the fourth cookie segment",
      h.ui_prefs({"cookie": "theta_ui=theta.dark.grid.liquid"}) == ("theta", "dark", "grid", "liquid", "theme"))
check("three-segment cookies default to Glass+",
      h.ui_prefs({"cookie": "theta_ui=theta.dark.grid"}) == ("theta", "dark", "grid", "plus", "theme"))
check("no cookie defaults to Glass+",
      h.ui_prefs({}) == ("theta", "auto", "grid", "plus", "theme"))
check("an unknown glass value defaults to Glass+",
      h.ui_prefs({"cookie": "theta_ui=theta.auto.grid.frosted"})[3] == "plus")

# --- The page renders the attribute the CSS keys on ---
html = h.page({"cookie": "theta_ui=theta.auto.grid.liquid"}, "T", "/", "<p>x</p>")
check("page renders data-glassstyle from the cookie",
      'data-glassstyle="liquid"' in html)
html = h.page({}, "T", "/", "<p>x</p>")
check("page defaults to data-glassstyle plus",
      'data-glassstyle="plus"' in html)

# --- Liquid rules: gloss, stronger blur, edge light, no borders ---
check("liquid restyles .glass surfaces",
      ':root[data-glassstyle="liquid"] .glass{background:linear-gradient(135deg,color-mix(in srgb,white 16%,transparent),color-mix(in srgb,white 2%,transparent) 45%),var(--surface);box-shadow:inset calc(var(--shine-x,0)*2px) calc(1px + var(--shine-y,0)*2px) 0 rgba(255,255,255,.45),inset calc(var(--shine-x,0)*-2px) calc(-1px + var(--shine-y,0)*-2px) 0 rgba(255,255,255,.12),inset 1px 0 0 rgba(255,255,255,.12),0 12px 32px rgba(0,0,0,.28)}' in css)
check("liquid blur beats Glass+ blur under backdrop-filter",
      ':root[data-glassstyle="liquid"] .glass{background:linear-gradient(135deg,color-mix(in srgb,white 16%,transparent),color-mix(in srgb,white 2%,transparent) 45%,color-mix(in srgb,var(--accent) 10%,transparent)),color-mix(in srgb,var(--surface) 58%,transparent);-webkit-backdrop-filter:blur(32px) saturate(190%);backdrop-filter:blur(32px) saturate(190%)}' in css)
check("liquid restyles own bubbles with no border",
      ':root[data-glassstyle="liquid"] .msg.mine .mbody{background:linear-gradient(135deg,color-mix(in srgb,white 16%,transparent),color-mix(in srgb,white 2%,transparent) 45%),var(--surface);box-shadow:inset calc(var(--shine-x,0)*2px) calc(1px + var(--shine-y,0)*2px) 0 rgba(255,255,255,.45),inset calc(var(--shine-x,0)*-2px) calc(-1px + var(--shine-y,0)*-2px) 0 rgba(255,255,255,.12),0 12px 32px rgba(0,0,0,.28)}' in css
      and ':root[data-glassstyle="liquid"] .msg.mine .mbody{background:linear-gradient(135deg,color-mix(in srgb,white 16%,transparent),color-mix(in srgb,white 2%,transparent) 45%,color-mix(in srgb,var(--accent) 10%,transparent)),color-mix(in srgb,var(--surface) 58%,transparent);-webkit-backdrop-filter:blur(32px) saturate(190%);backdrop-filter:blur(32px) saturate(190%)}' in css)

# --- Settings offers the swap, and the cookie saves it ---
settings = h.settings_page({})
check("settings offers Glass+ and Liquid Glass",
      'data-pref="glassstyle" data-val="plus"' in settings
      and 'data-pref="glassstyle" data-val="liquid"' in settings)
check("the UI script saves the glass style as the fourth cookie segment",
      '[root.dataset.theme, root.dataset.mode, root.dataset.layout, (root.dataset.glassstyle || "plus"), (root.dataset.bg || "theme")].join(".")' in js)

# --- The README documents the option ---
check("README documents the glass style option",
      "## Glass style" in readme and "Liquid Glass" in readme
      and "data-glassstyle" in readme)

# --- Liquid reaches every surface except images ---
check("liquid restyles cards, windows, and menus",
      ':root[data-glassstyle="liquid"] .card,:root[data-glassstyle="liquid"] .win,:root[data-glassstyle="liquid"] .kpi,:root[data-glassstyle="liquid"] .sw,:root[data-glassstyle="liquid"] .lo,:root[data-glassstyle="liquid"] .lrow,:root[data-glassstyle="liquid"] #chat-menu{background:linear-gradient(135deg,color-mix(in srgb,white 16%,transparent),color-mix(in srgb,white 2%,transparent) 45%,color-mix(in srgb,var(--accent) 10%,transparent)),color-mix(in srgb,var(--surface) 58%,transparent);-webkit-backdrop-filter:blur(32px) saturate(190%);backdrop-filter:blur(32px) saturate(190%);box-shadow:inset calc(var(--shine-x,0)*2px) calc(1px + var(--shine-y,0)*2px) 0 rgba(255,255,255,.45),inset calc(var(--shine-x,0)*-2px) calc(-1px + var(--shine-y,0)*-2px) 0 rgba(255,255,255,.12),0 12px 32px rgba(0,0,0,.28)}' in css)
check("liquid restyles composer, fields, controls, and code",
      ':root[data-glassstyle="liquid"] .box,:root[data-glassstyle="liquid"] .field,:root[data-glassstyle="liquid"] .seg,:root[data-glassstyle="liquid"] .fchip,:root[data-glassstyle="liquid"] .minibox,:root[data-glassstyle="liquid"] .md pre{background:linear-gradient(135deg,color-mix(in srgb,white 16%,transparent),color-mix(in srgb,white 2%,transparent) 45%,color-mix(in srgb,var(--accent) 10%,transparent)),color-mix(in srgb,var(--surface2) 58%,transparent);-webkit-backdrop-filter:blur(32px) saturate(190%);backdrop-filter:blur(32px) saturate(190%);box-shadow:inset calc(var(--shine-x,0)*2px) calc(1px + var(--shine-y,0)*2px) 0 rgba(255,255,255,.45),inset calc(var(--shine-x,0)*-2px) calc(-1px + var(--shine-y,0)*-2px) 0 rgba(255,255,255,.12)}' in css)
check("buttons and chips keep their colors, edge light only",
      ':root[data-glassstyle="liquid"] .btn,:root[data-glassstyle="liquid"] .seg button,:root[data-glassstyle="liquid"] .chip{box-shadow:inset calc(var(--shine-x,0)*2px) calc(1px + var(--shine-y,0)*2px) 0 rgba(255,255,255,.35),inset calc(var(--shine-x,0)*-2px) calc(-1px + var(--shine-y,0)*-2px) 0 rgba(255,255,255,.10)}' in css)
liq = css[css.index("Liquid Glass everywhere"):css.index(".is-loading", css.index("Liquid Glass everywhere"))]
check("liquid everywhere touches no images",
      ".att" not in liq and " img" not in liq and ".av" not in liq)
check("liquid corners use a squircle mask over the radius fallback",
      "mask-border:url(\"data:image/png;base64," in css
      and "-webkit-mask-box-image:url(\"data:image/png;base64," in css
      and "30 fill / 18px stretch" in css
      and "30 fill / 18px / 0 stretch" in css
      and "30 fill / 20px / 0 stretch" in css)
check("squircle masks keep their middle (fill), or Safari shows a hole",
      "30 fill / 18px stretch" in css
      and "30 fill / 18px / 0 stretch" in css
      and "30 fill / 20px / 0 stretch" in css)

print("liquidglass: all checks passed")
