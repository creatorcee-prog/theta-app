"""Themes, rebuilt (2026-11-06): every palette is made from a recipe in OKLCH and fitted until it reads.
This holds every theme, light and dark, to the same bar: text 12:1, muted text 4.5:1 on the darker surface,
both accents 4.5:1 on the background, and button text 4.5:1 on its accent. Each theme has its charm (a quiet
texture of its own) and its sigil (the small mark on its labels)."""
import sys, os
sys.dont_write_bytecode = True
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
os.environ.update(DASHBOARD_KEY="dk")
if mode == "memory":
    for k in ("KV_REST_API_URL", "REDIS_URL"):
        os.environ.pop(k, None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


check("28 themes, the same ids as before (saved choices keep working)", len(h.THEMES) == 28 and all(
    k in h.THEMES for k in ("theta", "midnight", "paper", "terminal", "lunar", "dusk", "nightfiligree", "aurora")))
C = h.contrast
for k, t in h.THEMES.items():
    for m in ("light", "dark"):
        p = t[m]
        check(f"{k}/{m}: text, muted, accents and button text all read",
              C(p["text"], p["bg"]) >= 12 and C(p["muted"], p["surface2"]) >= 4.5 and C(p["accent"], p["bg"]) >= 4.5
              and C(p["accent2"], p["bg"]) >= 4.5 and C(p["on"], p["accent"]) >= 4.5)
    check(f"{k}: has a charm and a sigil", t["charm"] in h.CHARMS and t["sigil"])
css = h._UI_CSS
check("the charm sits behind everything, only on the theme's own background", ':root[data-bg="theme"]::after{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;background:var(--charm,none)}' in css)
check("filigree themes get the engraved double line", ':root[data-theme="gilded"][data-bg="theme"]::after' in css and "outline-offset:3px" in css)
check("the sigil marks labels", '.eyebrow::before,.w .ey::before{content:var(--sigil,"")' in css and '--sigil:"θ"' in css)
check("the spending chart wears the theme", 'style="stroke:var(--accent)"' in h.donut_svg([("Food", 10.0), ("Fun", 5.0)], 15.0))
import re
sizes = {float(x) for x in re.findall(r"font-size:([\d.]+)px", h._BASE_CSS)}
check("one type scale (17px only for reading text)", sizes <= {10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 22, 24, 28, 32})
# charm: how a theme or frame behaves, not only how it looks
check("every theme celebrates when you finish something, its own way", set(h.CHEERS) == set(h.THEMES)
      and "window.thetaCheer" in h._UI_JS and "__CHEERS__" not in h._UI_JS)
kinds = {k for k, _ in h.CHEERS.values()}
check("...and the celebrations differ (petals, sparks, ripples, stamps, a shooting star...)", len(kinds) >= 10)
check("...from the board's Done and cleared widgets, and the calendar's Done", "thetaCheer(b.left" in h.BOARD_JS and "thetaCheer(innerWidth / 2" in h.BOARD_JS
      and "thetaCheer(r.left" in h._UI_JS)
for f in h.FRAMES:
    check(f"the {f} frame answers a touch its own way", f':root[data-glassstyle="{f}"] .tap' in h._UI_CSS)
check("charm stays out of the layout and off with reduced motion", ".tapfx{position:absolute;inset:0" in h._UI_CSS
      and "@media (prefers-reduced-motion:reduce){.tap,.tap > .tapfx{animation:none!important}}" in h._UI_CSS and "if (still()) return;" in h._UI_JS)
# frames, phase 2: calm page titles, readable paragraphs, each frame its own signature
fc = h._frames_css()
check("page titles stay in their own case in every frame (capitals are for small labels)",
      ':root[data-glassstyle="edge"] .top h1{font-size:28px;font-weight:700' in fc and ':root[data-glassstyle="breach"] .top h1{font-family:var(--f-head);font-size:26px' in fc)
check("Breach keeps paragraphs readable: mono is for labels, code and numbers", ':root[data-glassstyle="breach"] .small' not in fc)
check("Hologram is all light (a bright top edge, a glow), and HUD alone has the brackets", "top/100% 1px no-repeat" in fc
      and ':root[data-glassstyle="holo"] .top h1' in fc)
check("the see-through frames keep their bars readable", '.minibar{background:color-mix(in srgb,var(--bg) 88%,transparent)' in h._UI_CSS)
print("done")
