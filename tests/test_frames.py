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
check("the hologram tilts with the phone", "liquid|holo" in h._UI_JS and "rotateY(calc(var(--shine-x,0) * 0.6deg))" in h._UI_CSS)
new = ["redline", "datalog", "breach", "scanner", "amber", "mission", "hologram"]
check("seven new schemes", all(n in h.THEMES for n in new))
check("each new scheme in Settings, with Theta in its colors", all(f'data-pref="theme" data-val="{n}"' in sett for n in new))
for n in new:
    st = h.theme_stage({"cookie": f"theta_ui={n}.dark.grid.plus.theme"})
    check(f"{n}: Theta wears the scheme's light", st["calm"] == h.THEMES[n]["dark"]["accent2"])
check("the CSS braces balance", h._UI_CSS.count("{") == h._UI_CSS.count("}"))
print("done")

# ---- fonts (2026-11-04, later)
import os as _os
check("eleven open-licensed fonts, each weight on disk", len(h.FONTS) == 11 and all(
    _os.path.isfile(_os.path.join(h._PARTS_DIR, "fonts", f"{k}-{w}.woff2")) for k, v in h.FONTS.items() for w in v[2]))
code, kind, data = h.handle("GET", "/fonts/rajdhani-700.woff2", {}, {}, b"")[:3]
check("a font is served, as a real woff2", code == 200 and kind == "font/woff2" and data[:4] == b"wOF2")
check("nothing else is served from /fonts/", h.handle("GET", "/fonts/..%2Findex-400.woff2", {}, {}, b"")[0] != 200
      and h.handle("GET", "/fonts/nope-400.woff2", {}, {}, b"")[0] != 200)
check("every face the CSS asks for exists", all(_os.path.isfile(_os.path.join(h._PARTS_DIR, "fonts", f + ".woff2"))
      for f in re.findall(r"url\(/fonts/([a-z0-9-]+)\.woff2\)", h._UI_CSS)))
check("each frame brings its fonts; Edge is Rajdhani with Orbitron labels",
      ':root[data-glassstyle="edge"]{--f-body:"Rajdhani"' in h._UI_CSS and '--f-label:"Orbitron"' in h._UI_CSS)
check("a picked font beats the frame's", ':root:root[data-type="michroma"]{--f-body:"Michroma"' in h._UI_CSS)
check("the font is kept in the cookie, frame's own by default", h.ui_type({"cookie": "theta_ui=theta.dark.grid.edge.theme.oxanium"}) == "oxanium"
      and h.ui_type({"cookie": "theta_ui=theta.dark.grid.edge.theme"}) == "frame" and h.ui_type({"cookie": "theta_ui=a.b.c.d.e.evil"}) == "frame")
sett = h.handle("GET", "/settings", {}, {"x-dashboard-key": "dk"}, b"")[2].decode()
check("every font in Settings, shown in itself", all(f'data-pref="type" data-val="{k}"' in sett for k in h.FONT_PICKS)
      and 'style="font-family:&quot;Rajdhani&quot;' in sett and 'data-type="frame"' in sett)
check("the CSS braces still balance", h._UI_CSS.count("{") == h._UI_CSS.count("}"))
print("fonts done")

# ---- each frame arrives its own way (2026-11-04, later)
css = h._UI_CSS
for f, name in {"plus": "in-bubble", "liquid": "in-liquid", "edge": "in-glitch", "breach": "in-print",
                "hud": "in-lock", "console": "in-type", "holo": "in-project"}.items():
    check(f"{f}: its own entrance ({name})", f':root[data-glassstyle="{f}"]{{--in:{name};' in css and f"@keyframes {name}" in css)
check("nothing an entrance sets outlasts it (fill backwards only)", "var(--in,pagein) var(--in-dur,.42s) var(--in-ease,cubic-bezier(.2,.8,.2,1)) backwards" in css)
check("the whole page moves per frame too", ':root[data-glassstyle="holo"]::view-transition-old(root)' in css
      and ':root[data-glassstyle="edge"]::view-transition-new(root)' in css and ':root[data-glassstyle="liquid"]::view-transition-new(root)' in css)
ui = h._UI_JS
check("headings decode: Edge from binary, Breach from hex, Console types", 'edge: "01"' in ui and '"BD", "55", "1C", "E9"' in ui
      and 'fr === "console"' in ui and "!h.children.length" in ui and 'h.setAttribute("aria-label", text)' in ui)
check("reduced motion: headings stay still", "if (still || !(fr in SETS" in ui)
check("the CSS braces still balance (entrances)", css.count("{") == css.count("}"))
print("entrances done")

# ---- frame sounds (picked 2026-11-04 in the Frame Sounds page)
ui = h._UI_JS
picks = {"plus": "Fizz", "liquid": "Gloop", "edge": "Binary chirp", "breach": "Hex print", "hud": "Target lock",
         "console": "Typewriter", "holo": "Projector hum"}
check("a sound for every frame, the ones picked", all(f"// {name}" in ui for name in picks.values()) and set(picks) == set(h.FRAMES))
check("made live with Web Audio, no sound files", "window.thetaSfx" in ui and "createOscillator" in ui and ".mp3" not in ui)
check("plays from the tap that opens a page (iPhone needs a tap)", "a tap that opens another page of the app plays the frame's sound" in ui
      and 'u.pathname.startsWith("/api/")' in ui)
check("picking a frame plays its sound", 'if (k === "glassstyle" && window.thetaSfx) thetaSfx.play(v)' in ui)
check("off, or reduced motion, keeps it quiet", '"theta:sfx", "on") === "on" && !matchMedia("(prefers-reduced-motion: reduce)")' in ui)
sett = h.handle("GET", "/settings", {}, {"x-dashboard-key": "dk"}, b"")[2].decode()
check("Settings: sounds on or off, volume, and a Hear it button", 'data-sfx="on"' in sett and 'id="sfx-vol"' in sett and 'id="sfx-test"' in sett)
print("sounds done")

# ---- the bottom bar in each frame (2026-11-04, later)
css = h._UI_CSS
for f in ("edge", "breach", "hud", "console", "holo"):
    check(f"{f}: chips, message box, send and tab bar take its shape", all(f':root[data-glassstyle="{f}"] {sel}' in css
          for sel in (".minichips a{", ".minibox,", ".minibox .btn.send,", ".tabbar a")))
check("Glass+ and Liquid Glass keep their round pills", ':root[data-glassstyle="plus"] .minibox' not in css and ".minibox{display:flex;align-items:center;gap:8px;background:var(--surface2);border:1px solid var(--border);border-radius:999px" in css)
home = h.handle("GET", "/", {}, {"x-dashboard-key": "dk"}, b"")[2].decode()
check("the bar says who answers", ('placeholder="Message Theta\u2026"' in home) == h.head_on() and "Message the crew" in h.minibar_html("/") or h.head_on())
print("bar done")
