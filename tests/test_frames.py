"""2026-11-04: Theta opens pages in the app (the open tool), the avatar turns toward the cursor and the
phone's tilt, and five new frames plus seven sci-fi color schemes. No live network."""
import sys, os, json, re
sys.dont_write_bytecode = True
os.environ.update(DASHBOARD_KEY="dk", NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


# ---- the open tool
check("open is one of Theta's tools", "open" in h.head_tools())
check("open: a page", h.open_place("open money") == ("/money", "Money"))
check("open: the exact part wins over the page", h.open_place("the widget settings")[0] == "/settings#phone")
check("open: plural words", h.open_place("show me my notifications")[0] == "/settings#notifs")
check("open: nothing it doesn't know, and never a web address", h.open_place("https://evil.example") is None
      and h.open_place("") is None)
h._REQ.nav = None
r = h._tool_open("calendar", "theta")
check("open: says what it opens", "Calendar" in r)
extra = h.reply_extra()
check("the page rides on Theta's reply once", extra.get("nav") == {"url": "/calendar", "label": "Calendar"} and "nav" not in h.reply_extra())
check("open: unknown says what it can open", "I can open:" in h._tool_open("the moon", "theta") and not getattr(h._REQ, "nav", None))
check("every place is a page that exists", all(re.fullmatch(r"/[a-z]*(#[a-z]+)?", u) for u, _ in h.OPEN_PLACES.values()))
for u in {u.split("#")[0] for u, _ in h.OPEN_PLACES.values()}:
    code = h.handle("GET", u, {}, {"x-dashboard-key": "dk"}, b"")[0]
    check(f"{u} opens", code == 200)
sett = h.handle("GET", "/settings", {}, {"x-dashboard-key": "dk"}, b"")[2].decode()
for frag in {u.split("#")[1] for u, _ in h.OPEN_PLACES.values() if "#" in u and u.startswith("/settings")}:
    check(f"Settings has #{frag}", f'id="{frag}"' in sett)
stage = h._STAGE_JS
check("the page waits for Theta to finish talking, then Theta flies to the corner", "TH.talking()" in stage
      and "x.nav && x.nav.url" in stage and "a.click()" in stage and "talking: () => state === \"speaking\"" in h._HEAD_JS)
check("what was already in the chat never moves you", "navFirst" in stage)
check("the opened part lights up", ".card:target" in h._UI_CSS)

# ---- the avatar looks at you
check("one shared look: cursor or finger first, then the phone's tilt", "window.thetaLook" in h._UI_JS
      and "deviceorientation" in h._UI_JS and "requestPermission" in h._UI_JS)
check("the Theta page avatar turns with it", "thetaLook.at(lookC[0], lookC[1])" in h._HEAD_JS and "look[0] * 0.75" in h._HEAD_JS)
check("the corner avatar does too", "thetaLook.at(r.left" in h._UI_JS)
check("reduced motion: it holds still", "if (still) return [0, 0]" in h._UI_JS)

# ---- frames and schemes
check("seven frames", list(h.FRAMES) == ["plus", "liquid", "edge", "breach", "hud", "console", "holo"])
for f in ("edge", "breach", "hud", "console", "holo"):
    check(f"{f} has its CSS", f':root[data-glassstyle="{f}"] .card' in h._UI_CSS)
check("a frame is kept in the cookie", h.ui_prefs({"cookie": "theta_ui=redline.dark.grid.holo.black"})[:4] == ("redline", "dark", "grid", "holo"))
check("an unknown frame falls back", h.ui_prefs({"cookie": "theta_ui=theta.dark.grid.nope.theme"})[3] == "plus")
check("every frame is in Settings", all(f'data-pref="glassstyle" data-val="{f}"' in sett for f in h.FRAMES))
check("the hologram tilts with the phone", "liquid|holo" in h._UI_JS and "rotateY(calc(var(--shine-x,0) * 4deg))" in h._UI_CSS)
new = ["redline", "datalog", "breach", "scanner", "amber", "mission", "hologram"]
check("seven new schemes", all(n in h.THEMES for n in new))
check("each new scheme in Settings, with Theta in its colors", all(f'data-pref="theme" data-val="{n}"' in sett for n in new))
for n in new:
    st = h.theme_stage({"cookie": f"theta_ui={n}.dark.grid.plus.theme"})
    check(f"{n}: Theta wears the scheme's light", st["calm"] == h.THEMES[n]["dark"]["accent2"])
check("the CSS braces balance", h._UI_CSS.count("{") == h._UI_CSS.count("}"))
print("done")
