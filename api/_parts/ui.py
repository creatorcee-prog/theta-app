"""The app's look: themes, CSS, the shared page script and the chat script.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- The app's look: color schemes, layouts and pages. Pages render in
# the theme, mode and layout saved in the theta_ui cookie (Settings).
# Color schemes. Each has a light and a dark palette; the page follows the
# device unless a mode is picked. glow: how strongly the accents tint the
# page background (0-1). glass: frosted, see-through cards.
def _pal(bg, surface, surface2, border, text, muted, accent, accent2, on):
    return {"bg": bg, "surface": surface, "surface2": surface2, "border": border, "text": text,
            "muted": muted, "accent": accent, "accent2": accent2, "on": on}


# ---- Themes, rebuilt (2026-11-06): each is a recipe, not 18 hand-picked colors. A tint hue (how much
# of it the grounds carry), two accents (hue, chroma), a charm (a quiet texture that is the theme's own)
# and a sigil (the small mark on its labels). The palettes are made in OKLCH, so the steps between
# background, surfaces and borders look even in every theme, and each color is fitted until it reads:
# text 13:1 on the background, muted text 4.8:1 on the darker surface, accents 4.6:1 (light) / 6:1 (dark),
# and button text 4.5:1 on its accent. tests/test_themes.py holds every theme to that.
import math as _math
def oklch_to_srgb(L, C, h):
    a, b = C * _math.cos(_math.radians(h)), C * _math.sin(_math.radians(h))
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return r, g, bl
def _enc(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
def hexc(L, C, h):
    """OKLCH -> sRGB hex, chroma reduced until it fits the gamut."""
    for _ in range(60):
        r, g, b = oklch_to_srgb(L, C, h)
        if all(-0.0005 <= x <= 1.0005 for x in (r, g, b)): break
        C *= 0.94
    return "#" + "".join(f"{round(min(1, max(0, _enc(min(1, max(0, x))))) * 255):02x}" for x in (r, g, b))
def lum(hx):
    v = [int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    v = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in v]
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _fit(L, C, h, bg, need, step, lo=0.2, hi=0.97):
    while lo <= L <= hi:
        c = hexc(L, C, h)
        if contrast(c, bg) >= need: return c, L
        L += step
    return hexc(min(max(L, lo), hi), C, h), L
def _build(r):
    th, tl, td = r["tint"], r.get("tl", .012), r.get("td", .025)
    out = {}
    # light
    bg = hexc(.975, tl, th); s1 = hexc(.995, tl * .4, th); s2 = hexc(.952, tl * 1.2, th); bd = hexc(.9, tl * 1.6, th)
    tx, _ = _fit(.25, tl * 2.2, th, bg, 13, -.01); mu, _ = _fit(.52, tl * 2, th, s2, 4.8, -.01)
    ah, ac = r["acc"][:2]; a2h, a2c = r["acc2"][:2]
    if r.get("ink") == "both": ac_ = tx  # Paper: the accent is the ink itself
    else: ac_, _ = _fit(.56, ac, ah, bg, 4.6, -.01)
    a2, _ = _fit(.55, a2c, a2h, bg, 4.6, -.01)
    on = "#ffffff" if contrast("#ffffff", ac_) >= contrast(bg, ac_) else bg
    out["light"] = dict(bg=bg, surface=s1, surface2=s2, border=bd, text=tx, muted=mu, accent=ac_, accent2=a2, on=on)
    # dark
    Ld = r.get("Ld", .165)
    bg = hexc(Ld, td, th); s1 = hexc(Ld + .045, td * 1.05, th); s2 = hexc(Ld + .085, td * 1.1, th); bd = hexc(Ld + .16, td * 1.2, th)
    tx, _ = _fit(.93, td * .5, th, bg, 13, .01, hi=.99); mu, _ = _fit(.72, td * .9, th, s2, 4.8, .01)
    if r.get("ink"): ac_ = hexc(*r["dark_acc"]) if r.get("dark_acc") else tx
    else: ac_, _ = _fit(r["acc"][2] if len(r["acc"]) > 2 else .74, ac, ah, bg, 6, .01)
    a2, _ = _fit(r["acc2"][2] if len(r["acc2"]) > 2 else .78, a2c, a2h, bg, 6, .01)
    on = bg if contrast(bg, ac_) >= 4.5 else "#ffffff"
    out["dark"] = dict(bg=bg, surface=s1, surface2=s2, border=bd, text=tx, muted=mu, accent=ac_, accent2=a2, on=on)
    return out

# The recipes: tint hue (and how much of it the grounds carry), the two accents (hue, chroma[, dark lightness]),
# a charm (a quiet texture that's the theme's own) and a sigil (the small mark on its labels).
_RECIPES = {
 "theta":    dict(label="Theta", about="Indigo and cyan, the house colors", tint=278, td=.03, acc=(280, .19), acc2=(210, .13), glow=.45, charm="orbit", sigil="θ"),
 "midnight": dict(label="Midnight", about="Royal blue night with a few stars", tint=262, td=.07, Ld=.2, acc=(255, .17), acc2=(300, .13), glow=.55, charm="stars", sigil="✦"),
 "nebula":   dict(label="Nebula", about="Purple and pink on charcoal dust", tint=300, td=.03, acc=(305, .2), acc2=(350, .15), glow=.6, charm="dust", sigil="✧"),
 "aurora":   dict(label="Aurora Glass", about="Frosted glass over moving light", tint=280, td=.04, acc=(205, .14), acc2=(320, .16), glow=1.2, glass=True, charm="aurora", sigil="◇"),
 "graphite": dict(label="Graphite", about="Charcoal with coral and amber, fine grain", tint=255, tl=.004, td=.008, Ld=.22, acc=(12, .17), acc2=(62, .15), glow=.2, charm="grain", sigil="■"),
 "lobby":    dict(label="Lobby", about="Chat-app gray, blurple and green", tint=265, tl=.006, td=.012, Ld=.21, acc=(276, .17), acc2=(152, .14), glow=0, charm="none", sigil="#"),
 "forest":   dict(label="Forest", about="Pine green and goldenrod, contour lines", tint=155, td=.03, acc=(150, .15), acc2=(85, .14), glow=.35, charm="topo", sigil="▲"),
 "ember":    dict(label="Ember", about="Campfire orange and rose, a few sparks", tint=45, td=.03, acc=(50, .17), acc2=(10, .16), glow=.45, charm="embers", sigil="✶"),
 "ocean":    dict(label="Ocean", about="Teal and sky blue, slow waves", tint=205, td=.035, acc=(185, .12), acc2=(240, .13), glow=.4, charm="waves", sigil="≈"),
 "paper":    dict(label="Paper", about="Ink on ruled paper, almost no color", tint=90, tl=.012, td=.006, Ld=.19, acc=(90, .0), acc2=(62, .15), ink="both", glow=0, charm="ruled", sigil="¶"),
 "sakura":   dict(label="Sakura", about="Cherry blossom pink and violet, falling petals", tint=350, td=.03, acc=(355, .17), acc2=(295, .14), glow=.5, charm="petals", sigil="❀"),
 "terminal": dict(label="Terminal", about="Phosphor green, monospace, scan lines", tint=145, tl=.01, td=.02, Ld=.13, acc=(145, .2), acc2=(205, .12), glow=.2, mono=True, charm="scan", sigil="›"),
 "redline":  dict(label="Redline", about="Hot red on black, cyan highlights", tint=20, td=.025, Ld=.14, acc=(25, .2), acc2=(200, .13), glow=.35, charm="slash", sigil="▶"),
 "datalog":  dict(label="Data Log", about="Teal readouts on deep blue", tint=225, td=.04, Ld=.16, acc=(195, .12), acc2=(205, .1), glow=.3, charm="grid", sigil="▣"),
 "breach":   dict(label="Breach", about="Acid yellow-green on black", tint=115, td=.015, Ld=.14, acc=(118, .19, .88), acc2=(155, .15), glow=.25, charm="scan", sigil="⌁"),
 "scanner":  dict(label="Scanner", about="Warning red with yellow tags", tint=30, td=.015, Ld=.14, acc=(28, .2), acc2=(95, .17, .9), glow=.3, charm="hazard", sigil="!"),
 "amber":    dict(label="Amber HUD", about="Signal orange on gunmetal, ruler ticks", tint=240, tl=.006, td=.012, Ld=.18, acc=(58, .17), acc2=(80, .16), glow=.25, charm="ticks", sigil="◢"),
 "mission":  dict(label="Mission Control", about="Gold and blue data on deep night", tint=255, td=.025, Ld=.15, acc=(78, .14), acc2=(250, .14), glow=.2, charm="grid", sigil="◎"),
 "hologram": dict(label="Hologram", about="White light in the dark, red for warnings", tint=220, tl=.006, td=.01, Ld=.16, acc=(32, .18), acc2=(230, .04, .93), glow=.15, charm="scan", sigil="◈"),
 "gilded":   dict(label="Gilded Void", about="Gold lines on smoky dusk", tint=80, td=.015, Ld=.18, acc=(85, .12), acc2=(92, .07), glow=.3, charm="filigree", sigil="❖"),
 "lattice":  dict(label="Cyan Lattice", about="Glowing cyan lattice on deep blue", tint=250, td=.06, Ld=.2, acc=(225, .13), acc2=(215, .09), glow=.5, charm="lattice", sigil="◇"),
 "bloom":    dict(label="Violet Bloom", about="Silver petals on royal violet", tint=295, td=.1, Ld=.22, acc=(300, .17), acc2=(300, .06), glow=.55, charm="petals", sigil="✿"),
 "neonrift": dict(label="Neon Rift", about="Magenta and teal circuits", tint=290, td=.05, Ld=.17, acc=(325, .23), acc2=(180, .14), glow=.6, charm="circuit", sigil="⌬"),
 "verdant":  dict(label="Verdant Ember", about="Amber light over dark jade", tint=165, td=.035, Ld=.19, acc=(65, .15), acc2=(82, .12), glow=.4, charm="topo", sigil="❦"),
 "lunar":    dict(label="Lunar Red", about="White ornaments on deep red", tint=22, tl=.02, td=.085, Ld=.22, acc=(22, .19), acc2=(32, .14), ink="dark", dark_acc=(.95, .02, 40), glow=.2, charm="filigree", sigil="☾"),
 "bloodsign":dict(label="Blood Sign", about="Red glow on near-black", tint=18, td=.03, Ld=.13, acc=(22, .21), acc2=(38, .16), glow=.4, charm="grain", sigil="◆"),
 "nightfiligree": dict(label="Night Filigree", about="Pale gold on midnight navy", tint=268, td=.045, Ld=.17, acc=(85, .11), acc2=(88, .06), glow=.3, charm="filigree", sigil="✧"),
 "dusk":     dict(label="Nebula Dusk", about="Pink nebula, sky-blue light", tint=290, td=.07, Ld=.2, acc=(355, .18), acc2=(235, .12), glow=.7, charm="stars", sigil="✦"),
}


THEMES = {k: {"label": r["label"], "about": r["about"], "glow": r.get("glow", 0), "charm": r.get("charm", "none"),
              "sigil": r.get("sigil", ""), **({"glass": True} if r.get("glass") else {}), **({"mono": True} if r.get("mono") else {}),
              **_build(r)} for k, r in _RECIPES.items()}


# ---- Frames (Settings -> Frame): the shape of every surface, separate from the colors. Glass+ and
# Liquid Glass were the first two; five more (2026-11-04) are drawn from sci-fi screens:
#   edge     cut corners, a lit edge and spaced capitals (game menus in red and cyan)
#   breach   square boxes with solid title tags and mono type (a hacking screen)
#   hud      dark panels held by corner brackets, warning-tick titles (a control-room HUD)
#   console  hairlines, mono labels, dense rows over a faint grid (a mission-control dashboard)
#   holo     see-through light panels with bright corners and faint scan lines (a hologram)
FRAMES = {"plus": ("Glass+", "Frosted bars and bubbles"), "liquid": ("Liquid Glass", "Gloss, deep blur, edge light"),
          "edge": ("Edge", "Cut corners and a lit edge"), "breach": ("Breach", "Square boxes, solid title tags"),
          "hud": ("HUD", "Corner brackets on dark panels"), "console": ("Console", "Hairlines and mono data"),
          "holo": ("Hologram", "See-through light with scan lines"),
          "ornate": ("Filigree", "Fine double lines, engraved capitals"),
          # Theta frames (2026-11-06): every card made of Theta's own dots (the Dot UI Lab's Generation 2). Grouped under
          # one "Theta" button in Settings, with a picker for which.
          "grain": ("Theta \u00b7 Grain", "A halftone that prints in, then keeps a grain at the edges"),
          "press": ("Theta \u00b7 Press", "A halftone printed row by row, dense where the light lands"),
          "lines": ("Theta \u00b7 Lines", "A constellation: dots and the lines between them"),
          "nebula": ("Theta \u00b7 Nebula", "A swarm crowding the edges, calm inside"),
          "settle": ("Theta \u00b7 Settle", "A neat grid at rest that comes alive when Theta does")}
THETA_FRAMES = ("grain", "press", "lines", "nebula", "settle")


def _brackets(color, size="16px", w="2px"):
    """Four L-shaped corner brackets as background layers (no pseudo-elements, so nothing else breaks)."""
    g = f"linear-gradient({color},{color})"
    return ",".join(f"{g} {pos}/{a} {b} no-repeat" for pos in ("left top", "right top", "left bottom", "right bottom")
                    for a, b in ((size, w), (w, size)))


def _frames_css():
    F = lambda name, rules: "\n".join(
        ",".join(f':root[data-glassstyle="{name}"] {x.strip()}' for x in sel.split(",")) + "{" + body + "}"
        for sel, body in rules)
    panel = ".card,.win,.kpi"
    cut = lambda n: (f"clip-path:polygon(0 0,calc(100% - {n}) 0,100% {n},100% 100%,{n} 100%,0 calc(100% - {n}))")
    caps = "text-transform:uppercase;letter-spacing:.09em"
    mono = "font-family:var(--f-mono)"; head = "font-family:var(--f-head)"; label = "font-family:var(--f-label)"
    out = [F("edge", [
        (panel, "border-radius:0;border:1px solid color-mix(in srgb,var(--accent) 45%,transparent);" + cut("14px")
         + ";background:linear-gradient(180deg,color-mix(in srgb,var(--accent) 9%,transparent),transparent 46px),var(--surface);"
         "box-shadow:inset 3px 0 0 var(--accent)"),
        (".card h2,.win h2,.card h3", caps + ";font-weight:700;color:var(--accent)"),
        (".top h1", "font-size:28px;font-weight:700;letter-spacing:.01em"),
        (".btn", "border-radius:0;" + cut("8px") + ";" + caps + ";font-size:14px"),
        (".seg,.seg button,.field,.box,.chip,.sw,.lo,.lrow", "border-radius:0"),
        (".msg.mine .mbody", "border-radius:0;border:1px solid color-mix(in srgb,var(--accent) 40%,transparent);" + cut("10px")),
        (".tabbar", "border-top:1px solid color-mix(in srgb,var(--accent) 55%,transparent)"),
        (".tabbar a.on", "text-shadow:0 0 10px color-mix(in srgb,var(--accent) 70%,transparent)"),
    ]), F("breach", [
        (panel, "border-radius:0;border:1px solid color-mix(in srgb,var(--accent) 55%,transparent);"
         "background:color-mix(in srgb,var(--surface) 70%,transparent);box-shadow:inset 0 3px 0 var(--accent)"),
        (".card h2,.win h2", "display:inline-block;background:var(--accent);color:var(--on);padding:2px 10px;font-size:15px;"
         + caps + ";" + head + ";font-weight:700"),
        (".card h3,.eyebrow", label), ("code,.kpi .v,.big", mono),
        (".top h1", head + ";font-size:26px;letter-spacing:.01em"),
        (".btn", "border-radius:0;" + caps + ";" + head + ";font-size:13px"),
        (".seg,.seg button,.field,.box,.chip,.sw,.lo,.lrow,.msg.mine .mbody", "border-radius:0"),
        (".msg.mine .mbody", "border:1px solid color-mix(in srgb,var(--accent) 50%,transparent)"),
        (".tabbar", "border-top:1px solid var(--accent)"),
    ]), F("hud", [
        (panel, "border-radius:4px;border:1px solid color-mix(in srgb,var(--text) 10%,transparent);background:"
         + _brackets("var(--accent)") + ",linear-gradient(180deg,color-mix(in srgb,var(--text) 4%,transparent),transparent),var(--surface)"),
        (".card h2,.win h2", caps + ";font-size:16px;font-weight:700"),
        (".card h2::before,.win h2::before", 'content:"";display:inline-block;width:0;height:0;margin-right:8px;vertical-align:1px;'
         "border-left:6px solid transparent;border-right:6px solid transparent;border-bottom:10px solid var(--accent)"),
        (".btn", "border-radius:3px;" + caps + ";font-size:13px;box-shadow:inset 0 -2px 0 rgba(0,0,0,.25)"),
        (".seg,.field,.box,.chip,.sw,.lo,.lrow", "border-radius:4px"),
        (".msg.mine .mbody", "border-radius:4px;background:" + _brackets("var(--accent)", "10px", "2px") + ",var(--surface)"),
    ]), F("console", [
        (panel, "border-radius:2px;border:1px solid var(--border);box-shadow:none;background:var(--surface)"),
        (".card h2,.win h2,.card h3", caps + ";" + head + ";font-size:13px;font-weight:700;color:var(--muted)"),
        (".top h1", head + ";font-size:22px;letter-spacing:.02em"),
        (".eyebrow,.small,.chip", label), ("code", mono),
        (".btn,.seg,.seg button,.field,.box,.chip,.sw,.lo,.lrow,.msg.mine .mbody", "border-radius:2px"),
        (".btn", caps + ";" + head + ";font-size:13px"),
        ("body::before", "background:linear-gradient(color-mix(in srgb,var(--text) 5%,transparent) 1px,transparent 1px) 0 0/100% 32px,"
         "linear-gradient(90deg,color-mix(in srgb,var(--text) 5%,transparent) 1px,transparent 1px) 0 0/32px 100%,var(--glowbg),var(--bgfall,none)"),
    ]), F("holo", [
        (panel, "border-radius:8px;border:1px solid color-mix(in srgb,var(--text) 24%,transparent);background:"
         "linear-gradient(90deg,transparent,color-mix(in srgb,var(--text) 70%,transparent) 50%,transparent) top/100% 1px no-repeat"
         ",linear-gradient(160deg,color-mix(in srgb,var(--text) 11%,transparent),color-mix(in srgb,var(--text) 2%,transparent) 60%);"
         "-webkit-backdrop-filter:blur(10px) saturate(130%);backdrop-filter:blur(10px) saturate(130%);"
         "box-shadow:0 0 22px color-mix(in srgb,var(--text) 10%,transparent),inset 0 0 18px color-mix(in srgb,var(--text) 6%,transparent)"),  # no gyro tilt (2026-11-06)
        (".card h2,.win h2", "text-shadow:0 0 12px color-mix(in srgb,var(--text) 45%,transparent);" + caps),
        (".top h1", "text-shadow:0 0 18px color-mix(in srgb,var(--text) 35%,transparent);font-weight:600;letter-spacing:.01em"),
        # faint scan lines, like a projected image (2026-11-04)
        (".card::before,.win::before,.kpi::before", 'content:"";position:absolute;inset:0;pointer-events:none;border-radius:inherit;'
         "background:repeating-linear-gradient(0deg,color-mix(in srgb,var(--text) 5%,transparent) 0 1px,transparent 1px 3px);"
         "animation:holoscan 8s linear infinite"),
        (".card,.win,.kpi", "position:relative"),
        (".card h2,.win h2", "font-size:16px"),
        (".top h1", "font-size:22px"),
        (".btn", "border-radius:4px;" + caps + ";font-size:13px;box-shadow:0 0 14px color-mix(in srgb,var(--accent) 45%,transparent)"),
        (".seg,.field,.box,.chip,.sw,.lo,.lrow", "border-radius:4px"),
        (".msg.mine .mbody", "border-radius:6px;border:1px solid color-mix(in srgb,var(--text) 28%,transparent);background:"
         + _brackets("color-mix(in srgb,var(--text) 85%,transparent)", "9px", "1.5px") + ",color-mix(in srgb,var(--text) 6%,transparent)"),
    ])]
    out.append(F("ornate", [
        (panel, "border-radius:3px;border:1px solid color-mix(in srgb,var(--accent) 50%,transparent);outline:1px solid color-mix(in srgb,var(--accent) 22%,transparent);"
         "outline-offset:-6px;background:radial-gradient(120% 70% at 50% 0%,color-mix(in srgb,var(--accent) 8%,transparent),transparent 62%),var(--surface);"
         "box-shadow:0 12px 30px rgba(0,0,0,.35)"),
        (".card h2,.win h2,.top h1", caps + ";letter-spacing:.14em;" + head),
        (".card h2::before,.win h2::before", 'content:"\\25C6";color:var(--accent);font-size:.6em;margin-right:9px;vertical-align:.25em'),
        (".btn", "border-radius:0;background:transparent;color:var(--text);border:0;border-bottom:1px solid var(--accent);" + caps + ";letter-spacing:.12em;font-size:13px"),
        (".field,.box,.minibox", "border-radius:0;border:0;border-bottom:1px solid color-mix(in srgb,var(--accent) 60%,transparent);background:color-mix(in srgb,var(--surface) 40%,transparent)"),
        (".seg,.seg button,.sw,.lo,.lrow,.chip", "border-radius:3px"),
        (".msg.mine .mbody", "border-radius:3px;border:1px solid color-mix(in srgb,var(--accent) 45%,transparent);outline:1px solid color-mix(in srgb,var(--accent) 18%,transparent);outline-offset:-4px"),
    ]))
    out.append(':root[data-glassstyle="console"]{--pad:14px;--gap:10px}')
    out.append("@keyframes holoscan{to{background-position:0 24px}}"
               '@media (prefers-reduced-motion:reduce){:root[data-glassstyle="holo"] .card::before{animation:none}}')
    # Where a section was opened (Theta's open tool, or a link to #part), it lights up for a moment.
    out.append(".card:target,section:target{scroll-margin-top:calc(env(safe-area-inset-top) + 70px);animation:targetflash 1.8s ease-out}"
               "@keyframes targetflash{0%,30%{outline:2px solid var(--accent);outline-offset:4px}100%{outline:2px solid transparent;outline-offset:10px}}")
    return "\n".join(out)


# ---- Fonts (2026-11-04). All SIL Open Font License, shipped in api/_parts/fonts (served at /fonts/, cached
# for good); a page downloads only the ones it uses. Rajdhani is the UI font of the game whose menus the
# Edge and Breach frames come from, and Orbitron its small-label font (per Fonts In Use). The rest are free
# look-alikes for the other screens. size-adjust evens out how big each one reads next to the system font.
_SYS = '-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Inter,Roboto,system-ui,sans-serif'
_MONO = 'ui-monospace,"SF Mono",Menlo,Consolas,monospace'
FONTS = {  # id: (label, about, weights, size-adjust %, fallback)
    "rajdhani": ("Rajdhani", "Narrow and technical: the red game menus", (400, 500, 600, 700), 112, _SYS),
    "orbitron": ("Orbitron", "Wide and geometric: small sci-fi labels", (500, 700), 86, _SYS),
    "chakra-petch": ("Chakra Petch", "Square with clipped corners: control panels", (400, 600, 700), 100, _SYS),
    "oxanium": ("Oxanium", "Squared-off and clean", (400, 600, 700), 100, _SYS),
    "exo-2": ("Exo 2", "Soft futuristic, easy to read", (400, 600, 700), 100, _SYS),
    "michroma": ("Michroma", "Extended capitals: hologram labels", (400,), 80, _SYS),
    "audiowide": ("Audiowide", "Racing-style rounded wide", (400,), 88, _SYS),
    "saira-condensed": ("Saira Condensed", "Tall and condensed: HUD readouts", (500, 700), 112, _SYS),
    "space-grotesk": ("Space Grotesk", "Quirky modern grotesk", (400, 700), 100, _SYS),
    "share-tech-mono": ("Share Tech Mono", "Terminal mono: the hacking screen", (400,), 100, _MONO),
    "jetbrains-mono": ("JetBrains Mono", "Coder's mono: dashboards", (400, 700), 96, _MONO),
    "cinzel": ("Cinzel", "Engraved capitals: ornate game menus", (500, 700), 92, _SYS),
}
# Each frame's own fonts: (body, headings, small labels, mono).
FRAME_FONTS = {"edge": ("rajdhani", "rajdhani", "orbitron", "share-tech-mono"),
               "breach": ("rajdhani", "share-tech-mono", "share-tech-mono", "share-tech-mono"),
               "hud": ("chakra-petch", "chakra-petch", "saira-condensed", "jetbrains-mono"),
               "console": ("space-grotesk", "jetbrains-mono", "jetbrains-mono", "jetbrains-mono"),
               "holo": ("exo-2", "michroma", "michroma", "share-tech-mono"),
               "ornate": ("exo-2", "cinzel", "cinzel", "jetbrains-mono")}
FONT_PICKS = {"frame": "Frame's own", "system": "System"} | {k: v[0] for k, v in FONTS.items()}


def _fstack(fid):
    return f'"{FONTS[fid][0]}",{FONTS[fid][4]}'


def _fonts_css():
    out = [f'@font-face{{font-family:"{label}";src:url(/fonts/{fid}-{w}.woff2) format("woff2");font-weight:{w};'
           f'font-style:normal;font-display:swap;size-adjust:{adj}%}}'
           for fid, (label, _, weights, adj, _) in FONTS.items() for w in weights]
    out.append(f':root{{--f-body:{_SYS};--f-head:var(--f-body);--f-label:var(--f-head);--f-mono:{_MONO}}}'
               "body{font-family:var(--f-body)}h1,h2,h3,.btn,.seg button{font-family:var(--f-head)}.eyebrow{font-family:var(--f-label)}")
    for fr, (b, h_, l, m) in FRAME_FONTS.items():
        out.append(f':root[data-glassstyle="{fr}"]{{--f-body:{_fstack(b)};--f-head:{_fstack(h_)};--f-label:{_fstack(l)};--f-mono:{_fstack(m)}}}')
    for fid in FONTS:  # a font you pick wins over the frame's (:root twice outranks the frame rule)
        mono = FONTS[fid][4] == _MONO
        out.append(f':root:root[data-type="{fid}"]{{--f-body:{_fstack(fid)};--f-head:{_fstack(fid)};--f-label:{_fstack(fid)}'
                   + (f';--f-mono:{_fstack(fid)}' if mono else "") + "}")
    out.append(f':root:root[data-type="system"]{{--f-body:{_SYS};--f-head:{_SYS};--f-label:{_SYS};--f-mono:{_MONO}}}')
    return "\n".join(out)


MODES = {"auto": "Match device", "light": "Light", "dark": "Dark"}
LAYOUTS = {
    "grid": ("Grid", "Tiles side by side, like a dashboard"),
    "feed": ("Feed", "One big card at a time, like a social feed"),
    "magazine": ("Magazine", "A headline window, then rows you swipe"),
    "compact": ("Compact", "A dense list with thumbnails, like a bank app"),
}
_STATE_COLORS = {"light": {"good": "#15803d", "warn": "#b45309", "bad": "#c81e1e"},
                 "dark": {"good": "#4ade80", "warn": "#fbbf24", "bad": "#f87171"}}


# ---- Light, not bloom (2026-11-06). Every glow is drawn the way light falls off: a small hot core that runs
# toward white, a steep drop, then a long faint tail that reaches nothing. In the dark the lights add onto the
# page (screen), and the page itself falls from the theme's color to true black away from the light, so
# nothing fades into "a darker version of the same color".
_FALL = (0, .025, .06, .11, .18, .28, .42, .6, .8, 1)


def _light(shape, at, color, alpha, hot=.4, core=.07):
    """A radial light: `shape` (e.g. "900px 700px" or "60% 45%") centered `at`, in `color`, `alpha` at the center.
    Falloff 1/(1+(d/core)^2), windowed to reach 0 at the edge; the core whitens by up to `hot`."""
    stops = []
    for d in _FALL:
        f = (1 / (1 + (d / core) ** 2)) * (1 - d) ** 2
        a = round(alpha * f, 4)
        w = round(hot * 100 * f * f)
        c = f"color-mix(in oklab,{color},white {w}%)" if w else color
        stops.append(f"color-mix(in srgb,{c} {round(a * 100, 2)}%,transparent) {round(d * 100)}%")
    return f"radial-gradient({shape} at {at},{','.join(stops)})"


def _theme_vars(t, mode):
    p, glow = t[mode], t.get("glow", 0)
    v = {f"--{k}": val for k, val in p.items()}
    v.update({f"--{k}": val for k, val in _STATE_COLORS[mode].items()})
    v["--shadow"] = ("0 1px 2px rgba(16,24,40,.05),0 6px 18px rgba(16,24,40,.06)" if mode == "light"
                     else "0 1px 2px rgba(0,0,0,.35),0 8px 24px rgba(0,0,0,.25)")
    if glow:  # a key light in the theme's accent from the top left, a weaker fill in its second accent from the right
        k = .5 if mode == "dark" else .3
        layers = [_light("1100px 900px", "-8% -14%", "var(--accent)", min(.9, k * glow)),
                  _light("900px 800px", "108% 4%", "var(--accent2)", min(.7, k * .7 * glow), hot=.25)]
        if t.get("glass"):
            layers += [_light("900px 800px", "72% 108%", "#ff7a3d", min(.6, k * .8 * glow), hot=.3),
                       _light("800px 700px", "8% 96%", "#22c55e", min(.5, k * .5 * glow), hot=.2)]
        v["--glowbg"] = ",".join(layers)
    else:
        v["--glowbg"] = "none"
    # a surface lit from above: a touch brighter where the light lands, shading toward black underneath
    v["--lit"] = ("linear-gradient(180deg,color-mix(in srgb,white 5%,transparent),transparent 38%,color-mix(in srgb,#000 24%,transparent))"
                  if mode == "dark" else "linear-gradient(180deg,color-mix(in srgb,white 55%,transparent),transparent 42%,color-mix(in srgb,#000 3%,transparent))")
    # in the dark, the page falls off to black away from the light (not to a darker shade of its own color)
    v["--bgfall"] = ("radial-gradient(140% 95% at 22% -12%,transparent 0%,color-mix(in srgb,#000 38%,transparent) 48%,"
                     "color-mix(in srgb,#000 78%,transparent) 78%,#000 100%)" if mode == "dark" else "none")
    return ";".join(f"{k}:{val}" for k, val in v.items()) + f";color-scheme:{mode}"


def _p3(hexcolor, alpha=None, push=1.35):
    """sRGB hex -> Display P3, chroma pushed past what sRGB can express.

    Same hue family, more saturated: the color is converted into P3 space,
    then each channel is pushed away from luminance before encoding, so a
    P3 display shows a wider version of the accent instead of the same
    color in different coordinates. SDR rules never see these values.
    """
    h = hexcolor.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]
    x = 0.4123908 * lin[0] + 0.3575843 * lin[1] + 0.1804808 * lin[2]
    y = 0.2126390 * lin[0] + 0.7151687 * lin[1] + 0.0721923 * lin[2]
    z = 0.0193308 * lin[0] + 0.1191948 * lin[1] + 0.9505322 * lin[2]
    pr = 2.4934969 * x - 0.9313836 * y - 0.4027107 * z
    pg = -0.8294890 * x + 1.7626641 * y + 0.0236247 * z
    pb = 0.0358458 * x - 0.0761724 * y + 0.9568845 * z
    lum = 0.2126 * pr + 0.7152 * pg + 0.0722 * pb
    p3lin = [min(1.0, max(0.0, lum + (c - lum) * push)) for c in (pr, pg, pb)]
    enc = [c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055 for c in p3lin]
    enc = [min(1.0, max(0.0, c)) for c in enc]
    if alpha is None:
        return "color(display-p3 %.4f %.4f %.4f)" % (enc[0], enc[1], enc[2])
    return "color(display-p3 %.4f %.4f %.4f / %s)" % (enc[0], enc[1], enc[2], alpha)


# Each theme's charm: one quiet texture behind everything, drawn in its own colors at a few percent, so it
# reads as character, never as noise. Shown with the theme's own background (not over a picture or Spotlight).
def _mix(c, pct):
    return f"color-mix(in srgb,{c} {pct}%,transparent)"


_DOT = "radial-gradient({w} {w} at {x} {y},{c},transparent)"
CHARMS = {
    "none": "none",
    # Theta: faint orbits around the top-right corner, where Theta sits when minimized
    "orbit": f"repeating-radial-gradient(circle at 104% -6%,transparent 0 58px,{_mix('var(--accent)', 9)} 58px 59px,transparent 59px 118px)",
    "stars": ",".join(_DOT.format(w=w, x=x, y=y, c=_mix("var(--text)", a)) + " 0 0/380px 380px" for w, x, y, a in
                      (("1.5px", "8%", "12%", 55), ("1px", "23%", "64%", 40), ("2px", "41%", "28%", 35), ("1px", "57%", "83%", 45),
                       ("1.5px", "72%", "16%", 50), ("1px", "88%", "52%", 40), ("1px", "34%", "92%", 30), ("1.5px", "94%", "88%", 35))),
    "dust": f"radial-gradient(40vmax 30vmax at 85% 15%,{_mix('var(--accent)', 10)},transparent 70%),"
            f"radial-gradient(35vmax 25vmax at 10% 80%,{_mix('var(--accent2)', 8)},transparent 70%)",
    "aurora": "none",  # the glow is its charm
    "grain": "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E"
             "%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 .5 "
             "0 0 0 0 .5 0 0 0 0 .5 0 0 0 .06 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
    "topo": f"repeating-radial-gradient(ellipse 70% 45% at 78% 22%,transparent 0 34px,{_mix('var(--accent)', 7)} 34px 35px),"
            f"repeating-radial-gradient(ellipse 50% 35% at 12% 88%,transparent 0 30px,{_mix('var(--accent)', 5)} 30px 31px)",
    "embers": ",".join(_DOT.format(w=w, x=x, y=y, c=_mix(c, a)) + " 0 0/300px 300px" for w, x, y, c, a in
                       (("2px", "14%", "86%", "var(--accent)", 60), ("1.5px", "31%", "70%", "var(--accent2)", 50), ("2.5px", "63%", "92%", "var(--accent)", 45),
                        ("1.5px", "79%", "74%", "var(--accent)", 55), ("1px", "48%", "58%", "var(--accent2)", 40))),
    "waves": f"radial-gradient(ellipse 60px 16px at 50% 100%,transparent 72%,{_mix('var(--accent)', 9)} 73% 78%,transparent 79%) 0 0/120px 28px",
    "ruled": f"repeating-linear-gradient(180deg,transparent 0 31px,{_mix('var(--text)', 6)} 31px 32px)",
    "petals": ",".join(f"radial-gradient(ellipse {a} {b} at {x} {y},{_mix(c, o)},transparent) 0 0/340px 340px" for a, b, x, y, c, o in
                       (("6px", "3.5px", "12%", "20%", "var(--accent)", 32), ("4px", "2.5px", "38%", "66%", "var(--accent2)", 28),
                        ("5px", "3px", "67%", "34%", "var(--accent)", 26), ("4px", "2.5px", "86%", "80%", "var(--accent)", 30))),
    "scan": f"repeating-linear-gradient(180deg,{_mix('var(--text)', 3)} 0 1px,transparent 1px 3px)",
    "slash": f"repeating-linear-gradient(-45deg,{_mix('var(--accent)', 16)} 0 2px,transparent 2px 9px) right top/150px 44px no-repeat",
    "grid": f"linear-gradient({_mix('var(--accent)', 5)} 1px,transparent 1px) 0 0/44px 44px,"
            f"linear-gradient(90deg,{_mix('var(--accent)', 5)} 1px,transparent 1px) 0 0/44px 44px",
    "hazard": f"repeating-linear-gradient(-45deg,{_mix('var(--accent2)', 55)} 0 9px,transparent 9px 18px) left top/100% 4px no-repeat",
    "ticks": f"repeating-linear-gradient(180deg,{_mix('var(--accent)', 30)} 0 1px,transparent 1px 12px) left top/7px 100% no-repeat,"
             f"repeating-linear-gradient(180deg,{_mix('var(--accent)', 45)} 0 1px,transparent 1px 60px) left top/14px 100% no-repeat",
    "filigree": "none",  # a fine double line around the screen (below)
    "lattice": f"repeating-linear-gradient(45deg,{_mix('var(--accent)', 5)} 0 1px,transparent 1px 34px),"
               f"repeating-linear-gradient(-45deg,{_mix('var(--accent)', 5)} 0 1px,transparent 1px 34px)",
    "circuit": f"radial-gradient(circle,{_mix('var(--accent2)', 22)} 1.5px,transparent 2px) 0 0/48px 48px,"
               f"linear-gradient({_mix('var(--accent)', 5)} 1px,transparent 1px) 0 0/48px 48px,"
               f"linear-gradient(90deg,{_mix('var(--accent)', 5)} 1px,transparent 1px) 0 0/48px 48px",
}
def _charm_base():
    fil = ",".join(f':root[data-theme="{k}"][data-bg="theme"]::after' for k, t in THEMES.items() if t.get("charm") == "filigree")
    return (':root[data-bg="theme"]::after{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;background:var(--charm,none)}'
            # filigree: a fine double line around the screen, like an engraved plate
            + fil + "{inset:max(8px,env(safe-area-inset-top,0px)) 8px max(8px,env(safe-area-inset-bottom,0px));border:1px solid "
            + _mix("var(--accent)", 30) + ";outline:1px solid " + _mix("var(--accent)", 14) + ";outline-offset:3px;border-radius:4px}"
            # the sigil: each theme's small mark before its labels
            + '.eyebrow::before,.w .ey::before{content:var(--sigil,"");color:var(--accent);margin-right:.45em;font-weight:400;letter-spacing:0}'
            + "@media (prefers-reduced-transparency:reduce){:root::after{display:none}}")


def _charm_vars(t):
    return f"--charm:{CHARMS.get(t.get('charm', 'none'), 'none')}" + (f';--sigil:"{t["sigil"]}"' if t.get("sigil") else "")


def theme_css():
    out = []
    for name, t in THEMES.items():
        sel = f':root[data-theme="{name}"]'
        out.append(f"{sel}{{{_theme_vars(t, 'light')};{_charm_vars(t)}}}")
        out.append(f'{sel}[data-mode="dark"]{{{_theme_vars(t, "dark")}}}')
        out.append(f'@media (prefers-color-scheme:dark){{{sel}:not([data-mode="light"]){{{_theme_vars(t, "dark")}}}}}')
        # HDR: Display P3 accents on P3 displays; the SDR rules above are untouched.
        _li = f'--accent:{_p3(t["light"]["accent"])};--accent2:{_p3(t["light"]["accent2"])}'
        _dk = f'--accent:{_p3(t["dark"]["accent"])};--accent2:{_p3(t["dark"]["accent2"])}'
        out.append(f'@media (color-gamut:p3){{{sel}{{{_li}}}{sel}[data-mode="dark"]{{{_dk}}}}}')
        out.append(f'@media (color-gamut:p3) and (prefers-color-scheme:dark){{{sel}:not([data-mode="light"]){{{_dk}}}}}')
    out.append(_charm_base())
    return "\n".join(out)


def _hdr_css():
    """Wide-gamut + high-dynamic-range overrides, emitted after _BASE_CSS.

    Gemini curtain stops in Display P3 (same geometry and peak alphas as the
    SDR stops), and a highlight boost where the display reports high dynamic
    range: brighter Gemini curtains and stronger liquid edge light. SDR
    displays never match these media queries, so they see today's CSS.
    """
    b = "@media (color-gamut:p3){#bg-layer.bg-gemini::before{background-image:"
    b += ("radial-gradient(50% 95% at 65% -10%," + _p3("#2563eb", ".85") + ",transparent 70%),"
          "radial-gradient(40% 85% at 30% -5%," + _p3("#22d3ee", ".55") + ",transparent 70%)}")
    b += "#bg-layer.bg-gemini::after{background-image:"
    b += ("radial-gradient(45% 90% at 35% -10%," + _p3("#10b981", ".70") + ",transparent 70%),"
          "radial-gradient(40% 80% at 15% -5%," + _p3("#be9628", ".85") + ",transparent 70%)}}")
    _in1 = "inset calc(var(--shine-x,0)*2px) calc(1px + var(--shine-y,0)*2px) 0 rgba(255,255,255,.85)"
    _in2 = "inset calc(var(--shine-x,0)*-2px) calc(-1px + var(--shine-y,0)*-2px) 0 rgba(255,255,255,.35)"
    _drop = "0 12px 32px rgba(0,0,0,.28)"
    _liq = ':root[data-glassstyle="liquid"] '
    _a = ["card", "win", "kpi", "sw", "lo", "lrow", "#chat-menu", "dialog.sheet",
          ".msg.mine .mbody", ".msg-acts .btn", ".md .codeblock"]
    _c = ["box", "field", "seg", "fchip", "minibox", ".md pre"]
    _d = [".btn", ".seg button", ".chip"]
    b += ("@media (dynamic-range:high){"
          "#bg-layer.bg-gemini::before,#bg-layer.bg-gemini::after{filter:brightness(1.12) saturate(1.2)}"
          + ",".join(_liq + x for x in _a) + "{box-shadow:" + _in1 + "," + _in2 + "," + _drop + "}"
          + _liq + ".glass{box-shadow:" + _in1 + "," + _in2
          + ",inset 1px 0 0 rgba(255,255,255,.18)," + _drop + "}"
          + ",".join(_liq + x for x in _c) + "{box-shadow:" + _in1 + "," + _in2 + "}"
          + ",".join(_liq + x for x in _d) + "{box-shadow:"
          + "inset calc(var(--shine-x,0)*2px) calc(1px + var(--shine-y,0)*2px) 0 rgba(255,255,255,.45)"
          + ",inset calc(var(--shine-x,0)*-2px) calc(-1px + var(--shine-y,0)*-2px) 0 rgba(255,255,255,.16)}}")
    return b


_BASE_CSS = r'''
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;--r:16px;--r-sm:12px;--pad:18px;--gap:14px;--glass-blur:22px;--tabh:calc(60px + env(safe-area-inset-bottom))}
body{margin:0;background:var(--bg);color:var(--text);min-height:100dvh;
 font:16px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Inter,Roboto,system-ui,sans-serif;
 -webkit-font-smoothing:antialiased;-webkit-tap-highlight-color:transparent}
body::before{content:"";position:fixed;inset:0;z-index:-1;background:var(--glowbg),var(--bgfall,none);pointer-events:none}
:root[data-font="mono"] body{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:14px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
h1,h2,h3{margin:0;letter-spacing:-.018em;line-height:1.2}
h1{font-size:28px;font-weight:700}
h2{font-size:20px;font-weight:650}
h3{font-size:15px;font-weight:650}
p{margin:.4em 0}
code{font:12.5px ui-monospace,Menlo,monospace;background:var(--surface2);padding:1px 5px;border-radius:6px}
button,input,select,textarea{font:inherit;color:inherit}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.muted{color:var(--muted)}
.small{font-size:13px}
.eyebrow{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 4px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}

/* Shell: tab bar on phones, sidebar from 900px */
.rail{display:none}
.main{padding:calc(env(safe-area-inset-top) + 16px) 16px calc(var(--tabh) + 28px);max-width:1180px;margin:0 auto;min-width:0}
.tabbar{position:fixed;left:0;right:0;bottom:0;z-index:40;display:flex;justify-content:space-around;
 padding:6px 4px calc(env(safe-area-inset-bottom) + 6px);height:var(--tabh);
border-top:1px solid var(--border)}
.tabbar a{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;font-size:11px;
 font-weight:650;color:var(--muted);text-decoration:none;border-radius:12px}
.tabbar a svg{width:24px;height:24px}
.tabbar a.on{color:var(--accent)}
body.typing .tabbar{display:none}
@media (min-width:900px){
 .app{display:grid;grid-template-columns:248px minmax(0,1fr)}
 .rail{display:flex;flex-direction:column;gap:2px;position:sticky;top:0;height:100dvh;overflow-y:auto;padding:20px 12px;
  border-right:1px solid var(--border)}
 .tabbar{display:none}
 .main{padding:30px 34px 56px;width:100%}
}
.brand{display:flex;align-items:center;gap:10px;font-weight:820;font-size:22px;letter-spacing:-.03em;padding:2px 10px 16px;color:var(--text)}
.brand:hover{text-decoration:none}
.rail nav{display:flex;flex-direction:column;gap:2px}
.rail nav a{display:flex;align-items:center;gap:12px;padding:9px 12px;border-radius:12px;color:var(--muted);font-weight:650;text-decoration:none}
.rail nav a svg{width:20px;height:20px}
.rail nav a:hover{background:var(--surface2);color:var(--text)}
.rail nav a.on{background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--accent)}
.rail .label{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);padding:18px 12px 6px}
.crewlink{display:flex;align-items:center;gap:10px;padding:5px 10px;border-radius:12px;color:var(--text);font-size:14px;font-weight:560}
.crewlink:hover{background:var(--surface2);text-decoration:none}
.crewlink .act{margin-left:auto;font-size:11px;color:var(--muted);max-width:84px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* Avatars */
.av{display:block;flex:none;border-radius:30%}
.avw{position:relative;display:inline-flex;flex:none}
.dot{position:absolute;right:-2px;bottom:-2px;width:11px;height:11px;border-radius:50%;background:var(--muted);border:2px solid var(--surface)}
.dot.on{background:var(--good)}

/* Building blocks */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:var(--pad);box-shadow:var(--shadow)}details.card summary{cursor:pointer}
:root[data-glass] .card,:root[data-glass] .win,:root[data-glass] .kpi,:root[data-glass] .sw{-webkit-backdrop-filter:blur(24px) saturate(160%);backdrop-filter:blur(24px) saturate(160%)}
.stack{display:flex;flex-direction:column;gap:var(--gap)}
.top{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;margin:2px 0 20px;flex-wrap:wrap}
.top.tight{flex-wrap:nowrap;align-items:center}
.top.tight .btn{flex:none}
.note:empty{display:none}
@media (max-width:520px){.top h1{font-size:28px}.top .btn.rr span{display:none}.top .btn.rr{padding:11px}}
.top h1{font-size:32px}
.sect{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:30px 0 12px}
.sect a{font-weight:650;font-size:14px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;border:0;border-radius:var(--r-sm);padding:10px 15px;font-weight:650;
 background:var(--accent);color:var(--on);cursor:pointer;text-decoration:none;transition:transform .12s,filter .12s;white-space:nowrap}
.btn:hover{filter:brightness(1.07);text-decoration:none}
.btn:active{transform:scale(.97)}
.btn.ghost{background:var(--surface2);color:var(--text);border:1px solid var(--border)}
.btn.small{padding:6px 11px;font-size:14px;border-radius:12px}
.btn:disabled{opacity:.55;cursor:default}
.btn svg{width:18px;height:18px}
/* Message action buttons (card Submit, doc Copy/Edit/Save, server buttons) are glass,
   not accent: the surface treatment in both modes, so they read as controls, not calls. */
.msg-acts .btn{background:var(--surface);color:var(--text);border:1px solid var(--border)}
@supports (backdrop-filter:blur(1px)){
 .msg-acts .btn{background:color-mix(in srgb,var(--surface) 72%,transparent);-webkit-backdrop-filter:blur(var(--glass-blur)) saturate(160%);backdrop-filter:blur(var(--glass-blur)) saturate(160%)}}
.chip{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:4px 11px;font-size:13px;font-weight:650;
 background:var(--surface2);color:var(--muted);border:1px solid var(--border);text-decoration:none;white-space:nowrap}
.chip.on{background:var(--accent);color:var(--on);border-color:transparent}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.note{font-size:14px;color:var(--muted);min-height:18px}
.list{list-style:none;margin:0;padding:0}
.list li{padding:10px 0;border-bottom:1px solid var(--border)}
.list li:last-child{border-bottom:0}
.foot{margin-top:36px;font-size:12px;color:var(--muted)}
.empty{color:var(--muted);font-size:14px;padding:6px 0}

/* KPI tiles with rings */
.smart{margin:0 0 16px}.sc-track{display:flex;gap:12px;overflow-x:auto;scroll-snap-type:x mandatory;scrollbar-width:none;
 -webkit-overflow-scrolling:touch;overscroll-behavior-x:contain}.sc-track::-webkit-scrollbar{display:none}
.sc{flex:0 0 100%;scroll-snap-align:start;min-height:132px;box-sizing:border-box;display:flex;flex-direction:column;gap:6px;padding:16px 18px;
 border-radius:24px;background:var(--surface);border:1px solid var(--border);color:var(--text);text-decoration:none}
.sc:hover{text-decoration:none}.sc:active{transform:scale(.985)}
.sc-e{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.03em}
.sc-e svg{width:16px;height:16px}.sc-t{font-size:22px;font-weight:700;line-height:1.2;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.sc-s{color:var(--muted);font-size:14px;margin-top:auto}
.sc.warn .sc-e{color:var(--warn)}.sc.bad .sc-e{color:var(--bad)}
.sc-dots{display:flex;justify-content:center;gap:6px;margin-top:8px}.sc-dots i{width:6px;height:6px;border-radius:50%;background:var(--border)}
.sc-dots i.on{background:var(--accent)}
@media (min-width:900px){.sc{flex-basis:calc(50% - 6px)}}
.kpis{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
@media (min-width:760px){.kpis{grid-template-columns:repeat(4,minmax(0,1fr))}}
.kpi{display:flex;align-items:center;gap:12px;padding:14px;background:var(--surface);border:1px solid var(--border);border-radius:var(--r);
 box-shadow:var(--shadow);color:var(--text);min-width:0}
a.kpi:hover{text-decoration:none;border-color:color-mix(in srgb,var(--accent) 50%,var(--border))}
.kpi .v{font-size:22px;font-weight:700;letter-spacing:-.02em;line-height:1.1}
.kpi .l{font-size:12px;color:var(--muted);font-weight:600}
.kpi .s{font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kpi > div{min-width:0}
.ring{flex:none;display:block}
.ico{flex:none;width:44px;height:44px;border-radius:12px;display:grid;place-items:center;background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--accent)}
.ico svg{width:22px;height:22px}

/* Windows (agent and story cards) */
.wins{display:grid;gap:12px;grid-template-columns:repeat(2,minmax(0,1fr))}
@media (min-width:760px){.wins{grid-template-columns:repeat(auto-fill,minmax(212px,1fr));gap:14px}}
.win{position:relative;display:flex;flex-direction:column;min-width:0;background:var(--surface);border:1px solid var(--border);
 border-radius:var(--r);overflow:hidden;color:var(--text);box-shadow:var(--shadow);transition:transform .16s,border-color .16s}
.win:hover{text-decoration:none;transform:translateY(-2px);border-color:color-mix(in srgb,var(--accent) 45%,var(--border))}
.win:active{transform:scale(.985)}
.pic{position:relative;aspect-ratio:16/10;overflow:hidden;background:var(--surface2);flex:none}
.pic img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block}
/* Glass: a soft shine that follows the cursor (or the phone's tilt) over a darkened edge */
.pic::after{content:"";position:absolute;inset:0;z-index:1;pointer-events:none;transition:background-position .2s;
 background:radial-gradient(90% 75% at var(--gx,28%) var(--gy,18%),rgba(255,255,255,.26),rgba(255,255,255,.06) 38%,transparent 62%),
 radial-gradient(140% 120% at 50% 45%,transparent 58%,rgba(0,0,0,.34))}
@media (prefers-reduced-motion:reduce){.pic::after{background:radial-gradient(140% 120% at 50% 45%,transparent 58%,rgba(0,0,0,.3))}}
.ph{position:absolute;inset:0;display:grid;place-items:center;background:linear-gradient(135deg,var(--c1),var(--c2))}
.ph svg{width:34%;max-width:72px;height:auto;opacity:.92}
.ph::after{content:"";position:absolute;inset:0;background:radial-gradient(circle at 85% 10%,rgba(255,255,255,.22),transparent 45%)}
.tag{position:absolute;left:8px;top:8px;z-index:2;background:var(--bad);color:#fff;font-size:11px;font-weight:700;letter-spacing:.06em;
 text-transform:uppercase;padding:3px 8px;border-radius:999px}
.win .body{display:flex;flex-direction:column;gap:5px;padding:10px 12px 13px;flex:1;min-width:0}
.who{display:flex;align-items:center;gap:6px;font-size:12px;font-weight:650;color:var(--muted);min-width:0}
.who span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.who .nm{flex:none}
.who .src{min-width:0;font-weight:560}
@media (max-width:520px){.wins:not(.swipe) .who .src{display:none}}
.pic img.fit{object-fit:contain;background:#fff;padding:6px}
.who .t{margin-left:auto;font-weight:520;flex:none}
.who img{width:18px;height:18px;border-radius:6px}
.win .title{font-weight:650;font-size:15px;line-height:1.25;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.win .sub{font-size:13px;color:var(--muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.swipe .win .sub{-webkit-line-clamp:1}
.logo{width:14px;height:14px;border-radius:3px;vertical-align:-2px;margin-right:4px;flex:none}
.who > .logo{margin-right:0}
.cov{margin-top:auto;padding-top:6px;font-size:11px;color:var(--muted);font-weight:600}
.covbar{display:flex;gap:2px;height:5px;border-radius:999px;overflow:hidden;margin-bottom:4px;background:var(--surface2)}
.covbar i{display:block;min-width:4px}
:root[data-layout="compact"] .cov span{display:none}
:root[data-layout="compact"] .cov{padding-top:3px}

/* The sheet a window opens into */
dialog.sheet{border:0;padding:0;margin:auto auto 0;width:100%;max-width:640px;max-height:88dvh;border-radius:24px 24px 0 0;
 background:var(--surface);color:var(--text);box-shadow:0 -12px 40px rgba(0,0,0,.3);overflow:hidden;display:flex;flex-direction:column}
dialog.sheet:not([open]){display:none}
:root[data-glass] dialog.sheet{background:color-mix(in srgb,var(--bg) 82%,transparent);-webkit-backdrop-filter:blur(28px);backdrop-filter:blur(28px)}
@media (min-width:760px){dialog.sheet{margin:auto;border-radius:24px;max-height:84dvh}}
dialog.sheet::backdrop{background:rgba(0,0,0,.45)}
dialog.sheet[open]{animation:up .22s cubic-bezier(.2,.8,.2,1)}
@keyframes up{from{transform:translateY(40px);opacity:.4}}
.sheet .grab{width:38px;height:5px;border-radius:8px;background:var(--border);margin:8px auto 0;flex:none}
.sheet .x{position:absolute;right:12px;top:12px;z-index:3;width:34px;height:34px;border-radius:50%;border:0;cursor:pointer;
 background:rgba(0,0,0,.45);color:#fff;font-size:20px;line-height:34px;text-align:center}
.sheet .scroll{overflow-y:auto;padding-bottom:calc(env(safe-area-inset-bottom) + 18px)}
.sheet .pic{aspect-ratio:16/9;border-radius:0}
.sheet .in{padding:16px 20px 4px;display:flex;flex-direction:column;gap:10px}
.sheet h2{font-size:22px;line-height:1.25}
.sheet .text{color:var(--text);font-size:15px;line-height:1.5}
.sheet .covlist{display:grid;gap:6px;font-size:14px}
.sheet .covlist b{display:inline-block;min-width:44px}
.sheet .acts{display:flex;flex-wrap:wrap;gap:8px;padding-top:4px}
.sheet .remind{display:grid;gap:8px}
.pf{--s1:#2a78d6;--s2:#eb6834;display:grid;gap:8px}
:root[data-mode="dark"] .pf{--s1:#3987e5;--s2:#d95926}
@media (prefers-color-scheme:dark){:root:not([data-mode="light"]) .pf{--s1:#3987e5;--s2:#d95926}}
.pf-legend{display:flex;gap:14px;font-size:13px;color:var(--muted)}
.pf i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.pf i.s1{background:var(--s1)}.pf i.s2{background:var(--s2)}
#pf-chart{position:relative}#pf-chart svg{width:100%;height:auto;display:block;touch-action:pan-y}
#pf-chart text{font-size:11px;fill:var(--muted)}#pf-chart .pf-lab{fill:var(--text);font-weight:600}
.pf-g{stroke:var(--border);stroke-width:1}.pf-l{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.pf-l.s1{stroke:var(--s1)}.pf-l.s2{stroke:var(--s2)}.pf-x{stroke:var(--muted);stroke-width:1;opacity:0}
.pf-tip{position:absolute;top:0;pointer-events:none;opacity:0;background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:6px 9px;font-size:12px;line-height:1.5;white-space:nowrap;transition:opacity .12s}
.pf-t{width:100%;border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums}
.pf-t th,.pf-t td{text-align:left;padding:6px 4px;border-bottom:1px solid var(--border);white-space:nowrap}
.pf-t th{color:var(--muted);font-weight:600;font-size:12px}.pf-t .up{color:var(--good,#16a34a)}.pf-t .down{color:var(--bad)}
.sheet .remind .brow{align-items:center;gap:10px}
.sheet .remind form{padding:5px 5px 5px 14px}
.sheet .remind input{flex:1;min-width:0;border:0;background:transparent;outline:none;padding:8px 0;font:inherit;font-size:16px;color:inherit}

/* Unread dots */
.unread{position:relative}
.tabbar a.unread svg{overflow:visible}
.tabbar a.unread::after{content:"";position:absolute;top:5px;left:calc(50% + 7px);width:9px;height:9px;border-radius:50%;
 background:var(--bad);border:2px solid var(--bg)}
.rail nav a.unread::after,.chans a.unread::after{content:"";margin-left:auto;width:8px;height:8px;border-radius:50%;background:var(--bad);flex:none}
body.chatpage .rail nav a.unread::after{position:absolute;top:6px;right:6px;margin:0}
.chip.unread::after{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--bad);margin-left:2px}

/* Quick feedback: every tap shows at once; a bar runs while the next page loads */
a,button,.sw,.lo,.chip{touch-action:manipulation}
.tabbar a:active,.rail nav a:active,.chip:active,.sw:active,.lo:active,.crewlink:active,.mrow:active,.seg button:active{transform:scale(.95);transition:transform .06s}
.tabbar a,.rail nav a,.chip,.sw,.lo,.crewlink,.mrow,.seg button{transition:transform .14s}
#loadbar{position:fixed;top:0;left:0;height:3px;width:0;z-index:100;background:linear-gradient(90deg,var(--accent),var(--accent2));
 box-shadow:0 0 8px var(--accent);transition:width 2.5s cubic-bezier(.1,.7,.2,1),opacity .3s;pointer-events:none}
#loadbar.go{width:85%}
.nav-wait body::before{content:"";position:fixed;top:0;left:0;height:3px;width:100%;z-index:9999;pointer-events:none;
 background:linear-gradient(90deg,transparent,var(--accent),transparent);background-size:40% 100%;background-repeat:no-repeat;
 animation:navwait 1s linear infinite}
@keyframes navwait{from{background-position:-40% 0}to{background-position:140% 0}}
@media (prefers-reduced-motion:reduce){.nav-wait body::before{animation:none;background:var(--accent);opacity:.7}}

/* Feed: one column of big cards */
:root[data-layout="feed"] .wins{grid-template-columns:minmax(0,1fr);max-width:640px}
:root[data-layout="feed"] .pic{aspect-ratio:16/9}
:root[data-layout="feed"] .win .title{font-size:20px}
:root[data-layout="feed"] .win .sub{font-size:14px;-webkit-line-clamp:3}
:root[data-layout="feed"] .win .body{padding:12px 16px 16px;gap:7px}

/* Magazine: a hero window, then swipeable rows */
:root[data-layout="magazine"] .wins:not(.swipe) > .win:first-child{grid-column:1/-1}
:root[data-layout="magazine"] .wins:not(.swipe) > .win:first-child .pic{aspect-ratio:4/3}
@media (min-width:760px){:root[data-layout="magazine"] .wins:not(.swipe) > .win:first-child .pic{aspect-ratio:auto;height:clamp(260px,30vw,400px)}}
:root[data-layout="magazine"] .wins:not(.swipe) > .win:first-child .body{position:absolute;left:0;right:0;bottom:0;z-index:2;
 padding:60px 18px 18px;background:linear-gradient(transparent,rgba(0,0,0,.82));color:#fff}
:root[data-layout="magazine"] .wins:not(.swipe) > .win:first-child .who,
:root[data-layout="magazine"] .wins:not(.swipe) > .win:first-child .sub{color:rgba(255,255,255,.86)}
:root[data-layout="magazine"] .wins:not(.swipe) > .win:first-child .title{font-size:24px;-webkit-line-clamp:3}
:root[data-layout="magazine"] .wins.swipe{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;padding-bottom:6px;
 margin:0 -16px;padding-left:16px;padding-right:16px;scroll-padding:16px;scrollbar-width:none}
:root[data-layout="magazine"] .wins.swipe::-webkit-scrollbar{display:none}
:root[data-layout="magazine"] .wins.swipe > .win{flex:0 0 min(74%,270px);scroll-snap-align:start}
@media (min-width:900px){:root[data-layout="magazine"] .wins.swipe{margin:0;padding-left:0;padding-right:0}}

/* Compact: a list with thumbnails */
:root[data-layout="compact"] .wins{grid-template-columns:minmax(0,1fr);gap:0;background:var(--surface);border:1px solid var(--border);
 border-radius:var(--r);overflow:hidden;box-shadow:var(--shadow)}
@media (min-width:1000px){:root[data-layout="compact"] .wins{grid-template-columns:repeat(2,minmax(0,1fr))}}
:root[data-layout="compact"] .win{flex-direction:row;align-items:center;border:0;border-bottom:1px solid var(--border);border-radius:0;
 box-shadow:none;background:transparent;-webkit-backdrop-filter:none;backdrop-filter:none}
:root[data-layout="compact"] .win:hover{transform:none;background:var(--surface2)}
:root[data-layout="compact"] .pic{width:60px;height:60px;aspect-ratio:auto;margin:10px 0 10px 12px;border-radius:12px}
:root[data-layout="compact"] .tag{left:3px;top:3px;font-size:10px;padding:2px 5px}
:root[data-layout="compact"] .ph svg{width:46%}
:root[data-layout="compact"] .win .body{padding:10px 14px;gap:3px}
:root[data-layout="compact"] .win .title{font-size:15px;-webkit-line-clamp:1}
:root[data-layout="compact"] .win .sub{-webkit-line-clamp:1}

/* Chat (Discord-style): icon strip | channels | messages | members */
body.chatpage .main{padding:0;max-width:none}
@media (min-width:900px){
 body.chatpage .app{grid-template-columns:76px minmax(0,1fr)}
 body.chatpage .rail{padding:14px 10px;align-items:center}
 body.chatpage .rail .brand{padding:2px 0 12px;font-size:0;gap:0}
 body.chatpage .rail nav a{padding:10px;justify-content:center}
 body.chatpage .rail nav a span,body.chatpage .rail .label,body.chatpage .crewlink .act{display:none}
 body.chatpage .crewlink{font-size:0;gap:0;padding:5px}
 body.chatpage .rail .crewlink:first-of-type{margin-top:14px;border-top:1px solid var(--border);padding-top:14px;border-radius:0}
}
@media (max-width:620px){.meta .tier{display:none}}
.chat{display:grid;grid-template-columns:minmax(0,1fr);height:calc(100dvh - var(--tabh))}
body.typing .chat{height:100dvh}
@media (min-width:900px){.chat{height:100dvh;grid-template-columns:230px minmax(0,1fr)}}
@media (min-width:1200px){.chat{grid-template-columns:230px minmax(0,1fr) 250px}}
.chans,.members{display:none}
@media (min-width:900px){.chans{display:flex;flex-direction:column;gap:2px;padding:20px 10px;border-right:1px solid var(--border);overflow-y:auto}}
@media (min-width:1200px){.members{display:block;padding:20px 12px;border-left:1px solid var(--border);overflow-y:auto}}
.chans .label,.members .label{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);padding:6px 10px}
.chans a{display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:12px;color:var(--muted);font-weight:620}
.chans a:hover{background:var(--surface2);color:var(--text);text-decoration:none}
.chans a.on{background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--text)}
.hash{font-weight:500;opacity:.65;font-size:18px;line-height:1}
.thread{display:flex;flex-direction:column;min-height:0;min-width:0}
.chathead{display:flex;align-items:center;gap:10px;padding:calc(env(safe-area-inset-top) + 10px) 14px 10px;border-bottom:1px solid var(--border);
 background:color-mix(in srgb,var(--bg) 80%,transparent);-webkit-backdrop-filter:blur(20px);backdrop-filter:blur(20px);min-width:0}
.chathead b{font-size:16px;white-space:nowrap}
.chathead .about{font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0}
.chathead .btn{flex:none}
@media (min-width:1200px){#members-btn{display:none}}
.chiprow{display:flex;gap:6px;overflow-x:auto;padding:8px 12px;border-bottom:1px solid var(--border);scrollbar-width:none;flex:none}
.chiprow::-webkit-scrollbar{display:none}
@media (min-width:900px){.chiprow{display:none}}
.msgs{flex:1;overflow-y:auto;padding:10px 0 6px;overscroll-behavior:contain;min-height:0}
.msg{display:grid;grid-template-columns:minmax(0,1fr);padding:8px 16px 6px}
.msg:hover{background:color-mix(in srgb,var(--surface2) 55%,transparent)}
.msg.cont{padding-top:1px}
.msg.cont .meta{display:none}
.msg.mine .mbody{width:fit-content;max-width:min(76ch,85%);margin-left:auto;background:var(--surface);border-radius:20px;padding:10px 14px;overflow-wrap:anywhere}
.msg.mine .meta{display:none}
@supports (backdrop-filter:blur(1px)){
 .msg.mine .mbody{background:color-mix(in srgb,var(--surface) 72%,transparent);-webkit-backdrop-filter:blur(var(--glass-blur)) saturate(160%);backdrop-filter:blur(var(--glass-blur)) saturate(160%)}}
.msg .mbody{font-size:17px}
#msgs ::selection{background:transparent}
.mbody{max-width:76ch}
.new{animation:pop .25s ease-out}
@keyframes pop{from{opacity:0;transform:translateY(4px)}}
.meta{display:flex;align-items:baseline;gap:8px;min-width:0}
.meta .name{font-weight:650;color:color-mix(in srgb,var(--n) 62%,var(--text))}
.meta .tier{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);border:1px solid var(--border);border-radius:6px;padding:0 4px}
.meta time{font-size:12px;color:var(--muted)}
.text{white-space:pre-wrap;overflow-wrap:anywhere}
.msg-acts{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.src-foot{display:flex;align-items:center;gap:8px;margin-top:8px;padding:4px 2px;background:none;border:0;cursor:pointer;color:var(--text);font-family:inherit;font-size:14px}
.src-stack{display:flex;align-items:center}
.src-stack>*{margin-left:-8px}.src-stack>*:first-child{margin-left:0}
.src-ic,.src-tile,.src-more{width:22px;height:22px;border-radius:50%;border:1px solid var(--border);background:var(--surface);flex:none;object-fit:cover}
.src-tile,.src-more{display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:var(--muted)}
.src-label{font-weight:600}
.src-dlg{padding:12px 16px 0;display:flex;flex-direction:column}
.src-dlg .scroll{min-height:0}
.src-head{display:flex;align-items:center;justify-content:space-between;padding:4px 0 10px}
.src-head .src-title{font-size:18px;font-weight:700}
.src-x{background:none;border:0;cursor:pointer;color:var(--muted);font-size:22px;line-height:1;padding:4px 8px}
.src-row{display:flex;gap:10px;align-items:flex-start;padding:10px 0;text-decoration:none;color:var(--text);border-top:1px solid var(--border)}
.src-row .src-ic,.src-row .src-tile{width:28px;height:28px}
.src-meta{min-width:0}
.src-host{font-size:12px;color:var(--muted)}
.src-row-title{font-weight:600;overflow-wrap:anywhere}
.src-snip{font-size:13px;color:var(--muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.rcal{margin-top:16px}.rstrip{display:flex;gap:12px;overflow-x:auto;scroll-snap-type:x proximity;padding:8px 6px 10px;scroll-padding-left:6px;scrollbar-width:none}
.rel{flex:none;width:112px;scroll-snap-align:start;color:inherit;text-decoration:none;text-align:center}
.rel .rpic{position:relative;aspect-ratio:2/3;border-radius:12px;overflow:hidden;background:var(--surface2);border:1px solid var(--border)}
.rel img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.rel .rdate{display:flex;justify-content:center;align-items:baseline;gap:6px;margin-top:6px;font-variant-numeric:tabular-nums}
.rel .rdate b{font-size:20px;font-weight:700}.rel .rdate span{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;border-left:1px solid var(--border);padding-left:6px}
.rel .rname{font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:1px}
.rel .rplat{font-size:11px;color:var(--muted);opacity:.8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rel.next{width:150px}.rel.next .rpic{border:2px solid var(--accent);box-shadow:0 0 0 4px color-mix(in srgb,var(--accent) 22%,transparent)}
.rel.mine .rpic{border-color:var(--accent)}.rel .rtag{position:absolute;right:0;top:8px;background:var(--accent);color:var(--on);font-size:10px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:2px 6px;border-radius:6px 0 0 6px}
.daily{margin:14px 0 4px}.dlist{list-style:none;margin:0;padding:0;display:grid;gap:2px}
.dlist li{display:flex;align-items:center;gap:10px;min-height:40px}.dcheck{display:flex;align-items:center;gap:10px;flex:1;cursor:pointer;min-width:0}
.dcheck input{width:22px;height:22px;accent-color:var(--accent);flex:none}
.dcheck input:checked+span{color:var(--muted);text-decoration:line-through}
.daily .dx{display:none;border:0;background:none;color:var(--muted);font-size:20px;cursor:pointer;padding:4px 8px}
.daily.editing .dx{display:block}.daily .dadd{display:none;padding:5px 5px 5px 14px}.daily.editing .dadd{display:flex}
.via{font-size:12px;font-weight:700;color:var(--n);border:1px solid color-mix(in srgb,var(--n) 45%,transparent);
 background:color-mix(in srgb,var(--n) 12%,transparent);border-radius:999px;padding:1px 8px;line-height:1.5}
.mem li{justify-content:space-between}.ok-t{color:var(--good);font-weight:600}.bad-t{color:var(--bad)}
#devices li.dev{display:block;padding:10px 0}#devices details summary{cursor:pointer;padding:4px 0}.mem .dx{border:0;background:none;color:var(--muted);font-size:20px;cursor:pointer;padding:4px 8px}
.daily .dadd input{flex:1;min-width:0;border:0;background:transparent;outline:none;padding:8px 0;font:inherit}
.linkbtn{border:0;background:none;color:var(--accent);font:inherit;cursor:pointer;padding:0}
/* Phones: iOS zooms the page when a field's text is under 16px, and the page then drifts. Keep fields at 16px and
   stop the page itself from sliding sideways (scrolling strips inside it still scroll). */
@media (pointer:coarse){input:not([type=checkbox]):not([type=radio]),textarea,select{font-size:16px!important}}
html,body{overflow-x:clip;max-width:100%}
.md>div:empty.md-gap{height:.5em}.md .md-h{font-weight:700;font-size:18px;margin-top:4px}
.md .md-list{margin:2px 0;padding-left:1.3em;white-space:normal}.md .md-list li{margin:2px 0}
.md .md-list.tasks{list-style:none;padding-left:0}.md li.task{display:flex;gap:8px;align-items:flex-start}
.md li.task input{margin-top:4px;flex-shrink:0;accent-color:var(--accent);width:18px;height:18px;cursor:pointer}
.md li.task>span{flex:1;min-width:0}
.md .md-scroll{overflow-x:auto;margin:6px 0;white-space:normal;border:1px solid var(--border);border-radius:var(--r-sm);background:var(--surface)}
.md .md-scroll{-webkit-overflow-scrolling:touch;max-width:100%}
.md .md-table{border-collapse:collapse;font-size:14px;line-height:1.4;font-variant-numeric:tabular-nums;width:100%}
.md .md-table th,.md .md-table td{border-bottom:1px solid var(--border);padding:9px 12px;text-align:left;vertical-align:top;overflow-wrap:break-word;word-break:normal;white-space:normal;min-width:5.5em}
.md .md-table tr:last-child td{border-bottom:0}
.md .md-table th{background:var(--surface2);font-weight:650}
.md pre{background:var(--surface2);border:1px solid var(--border);padding:9px 11px;border-radius:12px;overflow-x:auto;max-height:340px;overflow-y:auto;font-size:14px;margin:6px 0;white-space:pre}
.md code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em;background:var(--surface2);border-radius:6px;padding:0 4px}
.md pre code{background:none;padding:0}.md .md-img{max-width:100%;border-radius:12px;margin:6px 0;display:block}
.md .md-quote{border-left:3px solid var(--accent);padding:2px 0 2px 12px;color:var(--muted);margin:6px 0}
.md .codeblock{border:1px solid var(--border);border-radius:16px;background:var(--surface);color:var(--text);overflow:hidden;margin:6px 0}
@supports (backdrop-filter:blur(1px)){
 .md .codeblock{background:color-mix(in srgb,var(--surface) 72%,transparent);-webkit-backdrop-filter:blur(var(--glass-blur)) saturate(160%);backdrop-filter:blur(var(--glass-blur)) saturate(160%)}}
:root[data-glassstyle="liquid"] .md .codeblock{background:linear-gradient(135deg,color-mix(in srgb,white 32%,transparent),color-mix(in srgb,white 2%,transparent) 45%,color-mix(in srgb,var(--accent) 10%,transparent)),color-mix(in srgb,var(--surface) 30%,transparent);-webkit-backdrop-filter:blur(32px) saturate(190%);backdrop-filter:blur(32px) saturate(190%);box-shadow:inset calc(var(--shine-x,0)*2px) calc(1px + var(--shine-y,0)*2px) 0 rgba(255,255,255,.70),inset calc(var(--shine-x,0)*-2px) calc(-1px + var(--shine-y,0)*-2px) 0 rgba(255,255,255,.24),0 12px 32px rgba(0,0,0,.28);border:0}
/* The codeblock pre stays transparent inside the glass box: without this, the liquid
   .md pre rule would put a second liquid panel (and mask) inside it. */
:root[data-glassstyle="liquid"] .md.codeblock pre{background:transparent;color:var(--text);-webkit-backdrop-filter:none;backdrop-filter:none;box-shadow:none;-webkit-mask-box-image:none;mask-border:none}
.md .codeblock .chead{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-bottom:1px solid var(--border)}
.md .codeblock .chead .clabel{font-size:14px;font-weight:650;color:var(--muted)}
.md .codeblock .cbtn{display:grid;place-items:center;width:32px;height:32px;padding:0;border:0;background:transparent;color:var(--muted);cursor:pointer;border-radius:8px}
.md .codeblock .cbtn:hover{color:var(--text);background:var(--surface2)}
.md .codeblock .cbtn svg{width:18px;height:18px}
.md .codeblock .cbtn.is-success{color:#4ade80}
.md .codeblock .cbtn.is-error{color:#f87171}
.md .codeblock pre{border:0;border-radius:0;margin:0;background:transparent}
.md .doccard,.md .cfgcard,.md .quizcard{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:var(--pad);box-shadow:var(--shadow);margin:8px 0}
.md .doc-title{font-weight:700;font-size:18px;margin-bottom:8px}
.md .docbody{white-space:pre-wrap;overflow-wrap:anywhere}
.md .doccard textarea.field{margin:8px 0}
.md .cfgrow{display:flex;align-items:center;gap:10px;margin:10px 0}
.md .cfgrow label{flex:1;min-width:0}
.md .cfgrow select.field{flex:1;min-width:120px}
.md .cfgrow input[type=checkbox]{flex-shrink:0;accent-color:var(--accent);width:18px;height:18px;cursor:pointer}
.md .cfgstatus{margin-top:8px}
.md .codeblock .chead-acts{display:flex;gap:6px;align-items:center}
.msg .mbtn{display:grid;place-items:center;width:32px;height:32px;padding:0;border:0;background:transparent;color:var(--muted);cursor:pointer;border-radius:8px}
.msg .mbtn:hover{color:var(--text);background:var(--surface2)}
.msg .mbtn svg{width:18px;height:18px}
.msg .mbtn.is-success{color:#4ade80}
.msg .mbtn.is-error{color:#f87171}
.msg .mmenu{margin-top:6px;border:1px solid var(--border);border-radius:12px;overflow:hidden;box-shadow:0 8px 24px rgba(0,0,0,.18)}
.msg .mmenu-item{display:block;width:100%;text-align:left;padding:10px 12px;border:0;background:transparent;color:var(--text);font:inherit;cursor:pointer}
.msg .mmenu-item:hover{background:var(--surface2)}
.msg .mmenu-item + .mmenu-item{border-top:1px solid var(--border)}
.md .quizrow{display:flex;gap:8px;align-items:flex-start;padding:7px 0;cursor:pointer}
.md .quizrow input{margin-top:2px;accent-color:var(--accent);width:18px;height:18px;flex-shrink:0;cursor:pointer}
.md .flow{display:flex;flex-direction:column;margin:8px 0}
.md .fnode{background:var(--surface2);border:1px solid var(--border);border-radius:var(--r-sm);padding:10px 14px;font-weight:650;text-align:center}
.md .farrow{text-align:center;color:var(--muted);padding:4px 0}
.md .bar-row{display:flex;align-items:center;gap:10px;margin:6px 0}
.md .bar-lab{flex:0 0 120px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}
.md .bar-track{flex:1;background:var(--surface2);border-radius:999px;height:14px;overflow:hidden}
.md .bar-fill{height:100%;background:var(--accent);border-radius:999px}
.md .bar-val{font-variant-numeric:tabular-nums;font-size:14px;color:var(--muted)}
@media (pointer:coarse){.md .doccard .btn,.md .cfgcard .btn,.md .quizcard .btn,.md .codeblock .cbtn,.msg .mbtn{min-height:44px;min-width:44px}}
.caret{display:inline-block;width:7px;height:1.05em;vertical-align:-2px;margin-left:2px;border-radius:2px;background:var(--accent);animation:blink 1s steps(1) infinite}
@keyframes blink{50%{opacity:0}}
.text .at{background:color-mix(in srgb,var(--accent) 16%,transparent);color:var(--accent);border-radius:6px;padding:0 3px;font-weight:620}
.att{display:block;max-width:min(100%,440px);border-radius:12px;margin-top:6px;border:1px solid var(--border);background:#fff}
.evt{display:flex;gap:8px;align-items:flex-start;padding:4px 16px 4px 28px;color:var(--muted);font-size:14px}
.evt img{width:16px;height:16px;border-radius:6px;margin-top:2px;flex:none}
.evt span{overflow-wrap:anywhere}
.daysep{display:flex;align-items:center;gap:10px;margin:14px 16px 6px;font-size:12px;font-weight:700;color:var(--muted)}
.daysep::before,.daysep::after{content:"";flex:1;height:1px;background:var(--border)}
.composer{position:relative;padding:8px 12px calc(10px + env(safe-area-inset-bottom) * 0);flex:none}
#chat-send{width:44px;height:44px}
.working{display:flex;flex-direction:column;gap:6px;padding:2px 6px 8px;color:var(--accent);font-size:15px;font-weight:600}
.working[hidden]{display:none}
.working .wline{display:flex;align-items:center;gap:10px}
.working .wline .av{border-radius:8px}
.trail{display:flex;align-items:center;gap:4px;flex-wrap:wrap}
.trail .av{border-radius:6px;opacity:.9}
.trail .sep{color:var(--muted);font-size:11px;font-weight:600}
.trail:empty{display:none}
.msg .trail{margin:2px 0 4px}
.meta .tok{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
.working .wdots{display:inline-flex;gap:5px}
.working .wdots i{width:6px;height:6px;border-radius:50%;background:currentColor;animation:wdot 1.2s infinite ease-in-out}
.working .wdots i:nth-child(2){animation-delay:.2s}.working .wdots i:nth-child(3){animation-delay:.4s}
.working .elapsed{margin-left:auto;font-size:12px;color:var(--muted);font-weight:400}
@keyframes wdot{0%,80%,100%{opacity:.25;transform:translateY(0)}40%{opacity:1;transform:translateY(-2px)}}
@media (prefers-reduced-motion:reduce){.working .wdots i{animation:none;opacity:.7}}
.box{display:flex;align-items:flex-end;gap:8px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--r);padding:5px 5px 5px 14px}
.box:focus-within{border-color:color-mix(in srgb,var(--accent) 60%,var(--border))}
.box textarea{flex:1;border:0;background:transparent;resize:none;outline:none;max-height:168px;padding:8px 0;line-height:1.4;min-width:0}
.send{width:40px;height:40px;padding:0;border-radius:12px;flex:none}
.box:has(.pick){padding-left:5px}.pick{width:40px;height:40px;padding:0;border-radius:12px;flex:none;display:grid;place-items:center;cursor:pointer}
.attach{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 8px 4px}.attach[hidden]{display:none}a>.att{max-height:340px;width:auto}
.attp{position:relative;display:inline-block}.attp img{display:block;max-height:96px;max-width:160px;border-radius:12px;border:1px solid var(--border)}
.attp .dx,.attach .fchip .dx{position:absolute;top:-8px;right:-8px;width:24px;height:24px;border-radius:50%;border:1px solid var(--border);background:var(--surface);color:var(--text);cursor:pointer;line-height:1;padding:0}
.fchip{display:inline-flex;align-items:center;gap:8px;max-width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:12px;background:var(--surface2);text-decoration:none;color:var(--text);position:relative}
.attach .fchip{padding-right:30px}.fchip b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:220px}.fchip span{font-size:12px;color:var(--muted);flex:none}
#chat-menu{position:absolute;bottom:100%;left:12px;right:12px;max-height:280px;overflow-y:auto;margin:0 0 6px;padding:6px;list-style:none;
 background:var(--surface);border:1px solid var(--border);border-radius:12px;box-shadow:0 12px 32px rgba(0,0,0,.22);z-index:20}
:root[data-glass] #chat-menu{-webkit-backdrop-filter:blur(24px);backdrop-filter:blur(24px)}
#chat-menu li{display:flex;align-items:center;gap:10px;padding:7px 10px;border-radius:12px;cursor:pointer}
#chat-menu li[aria-selected="true"]{background:color-mix(in srgb,var(--accent) 14%,transparent)}
#chat-menu img{width:26px;height:26px;border-radius:8px}
#chat-menu .muted{font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mrow{display:flex;align-items:center;gap:10px;padding:6px 10px;border-radius:12px;color:var(--text);min-width:0}
.mrow:hover{background:var(--surface2);text-decoration:none}
.mrow b{font-weight:640;display:block}
.mrow .muted{font-size:12px;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mrow > span:last-child{min-width:0}
.members.open{display:block;position:fixed;top:0;right:0;bottom:0;width:min(86vw,300px);z-index:60;
 padding:calc(env(safe-area-inset-top) + 16px) 12px 20px;box-shadow:-12px 0 40px rgba(0,0,0,.3);overflow-y:auto}
.scrim{display:none;position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:55}
.scrim.open{display:block}

/* Settings */
.swatches{display:grid;grid-template-columns:repeat(auto-fill,minmax(148px,1fr));gap:10px}
.sw .globe{width:26px;height:26px;border-radius:50%;float:right;margin:0 0 4px 6px}
.sw{display:flex;flex-direction:column;justify-content:flex-start;width:100%;border:2px solid var(--border);border-radius:16px;padding:0;overflow:hidden;background:var(--surface);cursor:pointer;text-align:left;color:var(--text)}
.sw.on{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 28%,transparent)}
.sw .pv{display:grid;grid-template-columns:1fr 1fr;height:62px}
.sw .pv span{display:flex;flex-direction:column;justify-content:flex-end;gap:4px;padding:9px}
.sw .pv i{display:block;height:7px;border-radius:4px}
.sw .nm{display:block;padding:8px 10px 9px;font-weight:700;font-size:14px}
.sw .nm small{display:block;color:var(--muted);font-weight:500;font-size:12px;line-height:1.3;margin-top:1px}
.seg{display:inline-flex;background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:3px;gap:2px;flex-wrap:wrap}
.seg button{border:0;background:transparent;padding:7px 14px;border-radius:12px;font-weight:650;color:var(--muted);cursor:pointer}
.seg button.on{background:var(--surface);color:var(--text);box-shadow:0 1px 3px rgba(0,0,0,.16)}
.layouts{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}
.lo{display:flex;flex-direction:column;justify-content:flex-start;border:2px solid var(--border);border-radius:16px;background:var(--surface);padding:10px;cursor:pointer;text-align:left;color:var(--text)}
.lo.on{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 28%,transparent)}
.lo svg{display:block;width:100%;height:auto;margin-bottom:8px;color:var(--muted)}
.lo b{display:block;font-size:14px}
.lo small{display:block;color:var(--muted);font-size:12px;line-height:1.3}
.tbl{width:100%;border-collapse:collapse;font-size:14px}
.tbl th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);font-weight:700;padding:6px 8px;border-bottom:1px solid var(--border)}
.tbl td{padding:8px;border-bottom:1px solid var(--border);vertical-align:top;overflow-wrap:break-word}
.tbl tr:last-child td{border-bottom:0}
.scrollx{overflow-x:auto}
.grid2{display:grid;gap:14px}
.grid2 > .card{min-width:0}
.card li{overflow-wrap:break-word}
@media (min-width:1000px){.grid2{grid-template-columns:repeat(2,minmax(0,1fr))}}

/* Budget bars */
.bar{height:8px;border-radius:999px;background:var(--surface2);overflow:hidden;margin-top:6px}
.bar i{display:block;height:100%;border-radius:999px;background:var(--accent)}
.bar i.warn{background:var(--warn)}
.bar i.bad{background:var(--bad)}
.brow{display:flex;justify-content:space-between;gap:10px;font-weight:620}

/* Lenz's library */
.ltabs{display:flex;flex-wrap:nowrap;overflow-x:auto;max-width:100%;scrollbar-width:none}
.ltabs::-webkit-scrollbar{display:none}
.ltabs button{white-space:nowrap}
.ltabs i{font-style:normal;font-size:11px;opacity:.7;margin-left:3px}
.llist{list-style:none;margin:0 0 6px;padding:0;display:grid;gap:8px}
@media (min-width:1000px){.llist{grid-template-columns:repeat(2,minmax(0,1fr))}}
.lrow{display:flex;gap:12px;align-items:flex-start;background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:10px;min-width:0}
.lpic{position:relative;flex:none;width:54px;height:76px;border-radius:12px;overflow:hidden;display:grid;place-items:center;
 background:linear-gradient(135deg,var(--c1),var(--c2));color:#fff;font-weight:700;font-size:22px}
.lpic img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.lbody{flex:1;min-width:0;display:flex;flex-direction:column;gap:6px}
.ltitle{font-weight:700;line-height:1.25}
.lchips{display:flex;flex-wrap:wrap;gap:4px}
.lchips .chip{padding:2px 8px;font-size:12px}
.chip.rated{color:var(--warn);border-color:color-mix(in srgb,var(--warn) 40%,var(--border))}
.lacts{display:flex;gap:6px;flex-wrap:wrap}
.lrank{flex:none;width:28px;text-align:right;font-weight:700;font-size:18px;color:var(--muted);padding-top:24px}
.lgroup{margin:14px 0 8px}
.rategrid{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}
.rategrid .btn{font-size:18px;padding:12px 0}
.field{width:100%;border:1px solid var(--border);background:var(--surface2);color:var(--text);border-radius:var(--r-sm);padding:10px 12px;font:inherit}
select.field{width:auto;flex:1;min-width:120px}

/* Agent profile */
.hero{display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.hero .av{width:76px;height:76px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:14px}
.kv dt{color:var(--muted)}
.kv dd{margin:0}
.post{padding:12px 0;border-bottom:1px solid var(--border)}
.post:last-child{border-bottom:0}

/* Calendar */
.cal{border-collapse:separate;border-spacing:4px;width:100%;table-layout:fixed}
.cal th{font-size:11px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.06em;padding:2px}
.cal td{background:var(--surface);border:1px solid var(--border);border-radius:12px;vertical-align:top;height:78px;padding:5px;font-size:11px;overflow:hidden}
.cal td.out{opacity:.45}
.cal td.today{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
.cal .n{font-weight:700;font-size:13px;margin-bottom:2px}
.cal td.today .n{color:var(--accent)}
.cal .e{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;background:color-mix(in srgb,var(--accent) 14%,transparent);border-radius:6px;padding:1px 4px;margin-top:2px}
.cal .e.b{background:color-mix(in srgb,#f472b6 22%,transparent)}
.day{margin:16px 0 6px;font-weight:650}
.card > .day:first-child{margin-top:0}
@media (max-width:600px){
 .cal{border-spacing:3px}
 .cal td{height:52px;padding:4px 3px;border-radius:12px}
 .cal .e{display:inline-block;width:7px;height:7px;padding:0;margin:1px;border-radius:50%;font-size:0;background:var(--accent)}
 .cal .e.b{background:#f472b6}
 .cal td > div:not(.n):not(.e){font-size:10px;color:var(--muted)}
}
.tbl{min-width:620px}
.monthnav{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
/* Persistent mini chat bar above the tab bar (phones only) */
.minibar{position:fixed;left:0;right:0;bottom:var(--tabh);z-index:39;background:color-mix(in srgb,var(--surface) 92%,transparent);-webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);border-top:1px solid var(--border);padding:8px 12px}
.minichips{display:flex;gap:6px;overflow-x:auto;padding:0 0 8px;scrollbar-width:none}
.minichips::-webkit-scrollbar{display:none}
.minichips a{flex:none;font-size:13px;font-weight:600;color:var(--text);background:var(--surface2);border:1px solid var(--border);border-radius:999px;padding:6px 11px;text-decoration:none;white-space:nowrap}
.minibox{display:flex;align-items:center;gap:8px;background:var(--surface2);border:1px solid var(--border);border-radius:999px;padding:5px 5px 5px 16px}
.minibox input{flex:1;border:0;background:transparent;outline:none;font-size:16px;min-width:0;color:var(--text)}
.minibox .btn.send{width:38px;height:38px;border-radius:50%;padding:0;display:grid;place-items:center;flex:none}
.minibar-status{font-size:12px;color:var(--muted);text-align:center;padding:6px 4px 0}
@media (min-width:900px){.minibar{display:none}}
@media (max-width:899px){
 .minibar:focus-within .minichips{display:none}
 body.hasminibar .main{padding-bottom:calc(var(--tabh) + 138px)}
}
/* Home quick actions + attention */
.quickactions{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}
.quickactions a{font-weight:650;color:var(--text);background:var(--surface);border:1px solid var(--border);border-radius:999px;padding:9px 14px;text-decoration:none}
.attention{border-color:color-mix(in srgb,var(--warn) 55%,var(--border));margin:0 0 16px}
.attention li{margin:4px 0}
.attention a{font-weight:650}
/* Spending donut */
.donut{display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.donut .legend{flex:1;min-width:180px}
.donut .legend li{display:flex;align-items:center;gap:8px;margin:6px 0}
.donut .legend .sw{width:10px;height:10px;border-radius:3px;flex:none}
.donut .legend .amt{margin-left:auto;font-weight:650;white-space:nowrap}

/* Glass+ foundation: one shared glass surface (solid when blur is
   unsupported) plus reusable control states. States come last so they
   win ties against the component rules above. */
.glass{background:var(--surface)}
@supports (backdrop-filter:blur(1px)){
 .glass{background:color-mix(in srgb,var(--surface) 72%,transparent);-webkit-backdrop-filter:blur(var(--glass-blur)) saturate(160%);backdrop-filter:blur(var(--glass-blur)) saturate(160%)}}
/* Liquid Glass: the same surfaces with a specular gloss, stronger blur, and edge light.
   Edges come from inset shadows, never borders, so own-message bubbles stay borderless. */
:root[data-glassstyle="liquid"] .glass{background:linear-gradient(135deg,color-mix(in srgb,white 16%,transparent),color-mix(in srgb,white 2%,transparent) 45%),var(--surface);box-shadow:inset calc(var(--shine-x,0)*2px) calc(1px + var(--shine-y,0)*2px) 0 rgba(255,255,255,.70),inset calc(var(--shine-x,0)*-2px) calc(-1px + var(--shine-y,0)*-2px) 0 rgba(255,255,255,.24),inset 1px 0 0 rgba(255,255,255,.12),0 12px 32px rgba(0,0,0,.28)}
:root[data-glassstyle="liquid"] .msg.mine .mbody{background:linear-gradient(135deg,color-mix(in srgb,white 16%,transparent),color-mix(in srgb,white 2%,transparent) 45%),var(--surface);box-shadow:inset calc(var(--shine-x,0)*2px) calc(1px + var(--shine-y,0)*2px) 0 rgba(255,255,255,.70),inset calc(var(--shine-x,0)*-2px) calc(-1px + var(--shine-y,0)*-2px) 0 rgba(255,255,255,.24),0 12px 32px rgba(0,0,0,.28)}
@supports (backdrop-filter:blur(1px)){
 :root[data-glassstyle="liquid"] .glass{background:linear-gradient(135deg,color-mix(in srgb,white 32%,transparent),color-mix(in srgb,white 2%,transparent) 45%,color-mix(in srgb,var(--accent) 10%,transparent)),color-mix(in srgb,var(--surface) 30%,transparent);-webkit-backdrop-filter:blur(32px) saturate(190%);backdrop-filter:blur(32px) saturate(190%)}
 :root[data-glassstyle="liquid"] .msg.mine .mbody{background:linear-gradient(135deg,color-mix(in srgb,white 32%,transparent),color-mix(in srgb,white 2%,transparent) 45%,color-mix(in srgb,var(--accent) 10%,transparent)),color-mix(in srgb,var(--surface) 30%,transparent);-webkit-backdrop-filter:blur(32px) saturate(190%);backdrop-filter:blur(32px) saturate(190%)}}
/* Liquid Glass everywhere (except images): the same gloss, blur, and edge light on every
   surface and control. Buttons and chips keep their colors and get edge light only, so accent
   states survive. Pills, circles, and images are untouched. */
@supports (backdrop-filter:blur(1px)){
 :root[data-glassstyle="liquid"] .card,:root[data-glassstyle="liquid"] .win,:root[data-glassstyle="liquid"] .kpi,:root[data-glassstyle="liquid"] .sw,:root[data-glassstyle="liquid"] .lo,:root[data-glassstyle="liquid"] .lrow,:root[data-glassstyle="liquid"] #chat-menu{background:linear-gradient(135deg,color-mix(in srgb,white 32%,transparent),color-mix(in srgb,white 2%,transparent) 45%,color-mix(in srgb,var(--accent) 10%,transparent)),color-mix(in srgb,var(--surface) 30%,transparent);-webkit-backdrop-filter:blur(32px) saturate(190%);backdrop-filter:blur(32px) saturate(190%);box-shadow:inset calc(var(--shine-x,0)*2px) calc(1px + var(--shine-y,0)*2px) 0 rgba(255,255,255,.70),inset calc(var(--shine-x,0)*-2px) calc(-1px + var(--shine-y,0)*-2px) 0 rgba(255,255,255,.24),0 12px 32px rgba(0,0,0,.28)}
 :root[data-glassstyle="liquid"] .box,:root[data-glassstyle="liquid"] .field,:root[data-glassstyle="liquid"] .seg,:root[data-glassstyle="liquid"] .fchip,:root[data-glassstyle="liquid"] .minibox,:root[data-glassstyle="liquid"] .md pre{background:linear-gradient(135deg,color-mix(in srgb,white 32%,transparent),color-mix(in srgb,white 2%,transparent) 45%,color-mix(in srgb,var(--accent) 10%,transparent)),color-mix(in srgb,var(--surface2) 30%,transparent);-webkit-backdrop-filter:blur(32px) saturate(190%);backdrop-filter:blur(32px) saturate(190%);box-shadow:inset calc(var(--shine-x,0)*2px) calc(1px + var(--shine-y,0)*2px) 0 rgba(255,255,255,.70),inset calc(var(--shine-x,0)*-2px) calc(-1px + var(--shine-y,0)*-2px) 0 rgba(255,255,255,.24)}
 :root[data-glassstyle="liquid"] dialog.sheet{background:linear-gradient(135deg,color-mix(in srgb,white 32%,transparent),color-mix(in srgb,white 2%,transparent) 45%,color-mix(in srgb,var(--accent) 10%,transparent)),color-mix(in srgb,var(--bg) 70%,transparent);-webkit-backdrop-filter:blur(32px) saturate(190%);backdrop-filter:blur(32px) saturate(190%);box-shadow:inset calc(var(--shine-x,0)*2px) calc(1px + var(--shine-y,0)*2px) 0 rgba(255,255,255,.70),inset calc(var(--shine-x,0)*-2px) calc(-1px + var(--shine-y,0)*-2px) 0 rgba(255,255,255,.24),0 12px 32px rgba(0,0,0,.28)}
 :root[data-glassstyle="liquid"] .mrow:hover,:root[data-glassstyle="liquid"] .crewlink:hover{background:linear-gradient(135deg,color-mix(in srgb,white 16%,transparent),color-mix(in srgb,white 2%,transparent) 45%),color-mix(in srgb,var(--surface2) 30%,transparent);-webkit-backdrop-filter:blur(32px) saturate(190%);backdrop-filter:blur(32px) saturate(190%)}}
:root[data-glassstyle="liquid"] .btn,:root[data-glassstyle="liquid"] .seg button,:root[data-glassstyle="liquid"] .chip{box-shadow:inset calc(var(--shine-x,0)*2px) calc(1px + var(--shine-y,0)*2px) 0 rgba(255,255,255,.35),inset calc(var(--shine-x,0)*-2px) calc(-1px + var(--shine-y,0)*-2px) 0 rgba(255,255,255,.10)}
:root[data-glassstyle="liquid"] .msg-acts .btn{background:linear-gradient(135deg,color-mix(in srgb,white 32%,transparent),color-mix(in srgb,white 2%,transparent) 45%,color-mix(in srgb,var(--accent) 10%,transparent)),color-mix(in srgb,var(--surface) 30%,transparent);-webkit-backdrop-filter:blur(32px) saturate(190%);backdrop-filter:blur(32px) saturate(190%);box-shadow:inset calc(var(--shine-x,0)*2px) calc(1px + var(--shine-y,0)*2px) 0 rgba(255,255,255,.70),inset calc(var(--shine-x,0)*-2px) calc(-1px + var(--shine-y,0)*-2px) 0 rgba(255,255,255,.24);border:0}
/* G2/G3 continuous curvature in liquid mode: browsers have no native corner-shape, so the
   squircle comes from a 9-slice mask (fixed corners, stretching edges) over the existing
   border-radius fallback. The mask is a 100px PNG: Chromium stretches an SVG mask to the
   whole box instead of slicing it, while the PNG 9-slices correctly. Pills, circles,
   sheets, and bars keep their radius. */
:root[data-glassstyle="liquid"] .card,:root[data-glassstyle="liquid"] .win,:root[data-glassstyle="liquid"] .box,:root[data-glassstyle="liquid"] .kpi{-webkit-mask-box-image:url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAA2ElEQVR4nOzQQQ0AIAwAMULwb3lY2P1bCX0zc9i5hzVZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgazgAwAA///jFbNiAAAABklEQVQDADDLA8hlIfMvAAAAAElFTkSuQmCC") 30 fill / 18px stretch;mask-border:url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAA2ElEQVR4nOzQQQ0AIAwAMULwb3lY2P1bCX0zc9i5hzVZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgazgAwAA///jFbNiAAAABklEQVQDADDLA8hlIfMvAAAAAElFTkSuQmCC") 30 fill / 18px / 0 stretch}
:root[data-glassstyle="liquid"] .sw,:root[data-glassstyle="liquid"] .lo,:root[data-glassstyle="liquid"] .lrow{-webkit-mask-box-image:url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAA2ElEQVR4nOzQQQ0AIAwAMULwb3lY2P1bCX0zc9i5hzVZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgazgAwAA///jFbNiAAAABklEQVQDADDLA8hlIfMvAAAAAElFTkSuQmCC") 30 fill / 16px stretch;mask-border:url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAA2ElEQVR4nOzQQQ0AIAwAMULwb3lY2P1bCX0zc9i5hzVZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgazgAwAA///jFbNiAAAABklEQVQDADDLA8hlIfMvAAAAAElFTkSuQmCC") 30 fill / 16px / 0 stretch}
:root[data-glassstyle="liquid"] #chat-menu{-webkit-mask-box-image:url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAA2ElEQVR4nOzQQQ0AIAwAMULwb3lY2P1bCX0zc9i5hzVZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgazgAwAA///jFbNiAAAABklEQVQDADDLA8hlIfMvAAAAAElFTkSuQmCC") 30 fill / 14px stretch;mask-border:url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAA2ElEQVR4nOzQQQ0AIAwAMULwb3lY2P1bCX0zc9i5hzVZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgazgAwAA///jFbNiAAAABklEQVQDADDLA8hlIfMvAAAAAElFTkSuQmCC") 30 fill / 14px / 0 stretch}
:root[data-glassstyle="liquid"] .field,:root[data-glassstyle="liquid"] .fchip,:root[data-glassstyle="liquid"] .btn,:root[data-glassstyle="liquid"] .seg{-webkit-mask-box-image:url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAA2ElEQVR4nOzQQQ0AIAwAMULwb3lY2P1bCX0zc9i5hzVZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgazgAwAA///jFbNiAAAABklEQVQDADDLA8hlIfMvAAAAAElFTkSuQmCC") 30 fill / 12px stretch;mask-border:url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAA2ElEQVR4nOzQQQ0AIAwAMULwb3lY2P1bCX0zc9i5hzVZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgazgAwAA///jFbNiAAAABklEQVQDADDLA8hlIfMvAAAAAElFTkSuQmCC") 30 fill / 12px / 0 stretch}
:root[data-glassstyle="liquid"] .md pre{-webkit-mask-box-image:url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAA2ElEQVR4nOzQQQ0AIAwAMULwb3lY2P1bCX0zc9i5hzVZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgazgAwAA///jFbNiAAAABklEQVQDADDLA8hlIfMvAAAAAElFTkSuQmCC") 30 fill / 10px stretch;mask-border:url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAA2ElEQVR4nOzQQQ0AIAwAMULwb3lY2P1bCX0zc9i5hzVZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgazgAwAA///jFbNiAAAABklEQVQDADDLA8hlIfMvAAAAAElFTkSuQmCC") 30 fill / 10px / 0 stretch}
:root[data-glassstyle="liquid"] .msg.mine .mbody{-webkit-mask-box-image:url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAA2ElEQVR4nOzQQQ0AIAwAMULwb3lY2P1bCX0zc9i5hzVZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgazgAwAA///jFbNiAAAABklEQVQDADDLA8hlIfMvAAAAAElFTkSuQmCC") 30 fill / 20px stretch;mask-border:url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAA2ElEQVR4nOzQQQ0AIAwAMULwb3lY2P1bCX0zc9i5hzVZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgaxAViArkBXICmQFsgJZgazgAwAA///jFbNiAAAABklEQVQDADDLA8hlIfMvAAAAAElFTkSuQmCC") 30 fill / 20px / 0 stretch}
.is-loading{opacity:.6;pointer-events:none;cursor:wait}
.is-success{border-color:var(--good);color:var(--good)}
.is-error{border-color:var(--bad);color:var(--bad)}
.is-disabled{opacity:.55;pointer-events:none;cursor:default}
input:disabled,select:disabled,textarea:disabled{opacity:.55;cursor:default}

/* Animated backgrounds (Settings -> Background). Independent of themes: the
   layer sits behind all content (z-index -1) and is opaque, so the theme's
   own background never shows through it. Theme (the default) hides it. */
.theta-mini{position:fixed;top:calc(env(safe-area-inset-top,0px) + 10px);right:calc(env(safe-area-inset-right,0px) + 12px);z-index:60;
 width:48px;height:48px;border-radius:50%;display:block}
.theta-mini canvas{width:100%;height:100%;display:block;transform-origin:0 0}
body.has-mini header.top{padding-right:60px} /* room for Theta in the corner */
.theta-mini:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
#bg-layer{position:fixed;inset:0;z-index:-1;pointer-events:none;overflow:hidden;background:#000}
#bg-layer.off{display:none}
#bg-layer .bgpic{position:absolute;inset:0;background:center/cover no-repeat;opacity:0;transition:opacity 1.6s ease,transform 16s linear;transform:scale(1.04)}
#bg-layer .bgpic.on{opacity:1;transform:scale(1.1)}
#bg-layer.bg-image::after,#bg-layer.bg-spotlight::after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.55),rgba(0,0,0,.25) 35%,rgba(0,0,0,.65))}
#bg-layer.bg-spotlight .bgpic{filter:saturate(1.1)}
.spot-cap{position:fixed;left:max(12px,env(safe-area-inset-left,0px));top:calc(env(safe-area-inset-top,0px) + 10px);z-index:3;
 max-width:min(62vw,340px);display:flex;align-items:center;gap:8px;padding:5px 10px;border-radius:999px;background:rgba(0,0,0,.42);
 -webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);color:#fff;border:1px solid rgba(255,255,255,.14);opacity:0;font-size:12px;line-height:1.3}
.spot-cap.in{animation:spotin .7s ease forwards}
@keyframes spotin{from{opacity:0;transform:translateY(-6px)}to{opacity:.92;transform:none}}
.spot-cap .sp-why{display:none}
.spot-cap .sp-title{font-weight:650;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.spot-cap .sp-src{flex:none;font-size:12px;color:#cfe8ff;text-decoration:none;opacity:.9}
body:not(.headchat) .spot-cap{top:auto;bottom:calc(var(--tabh) + 150px)}
body.docked .spot-cap,body.has-panels .spot-cap,body.sheet-open .spot-cap{display:none}
@media (prefers-reduced-motion:reduce){#bg-layer .bgpic{transition:none;transform:none}}
:root[data-bg]:not([data-bg="theme"]) body{background:transparent}
#bg-layer canvas{width:100%;height:100%;display:block}
#bg-layer.bg-gemini{background-color:#0A080B;animation:geminiPulse 8s ease-in-out infinite alternate;animation-delay:var(--gdelay,0s)}
#bg-layer.bg-gemini::before{content:"";position:absolute;inset:0;pointer-events:none;background-image:radial-gradient(50% 95% at 65% -10%,rgba(37,99,235,.85),transparent 70%),radial-gradient(40% 85% at 30% -5%,rgba(34,211,238,.55),transparent 70%);opacity:0;animation:geminiBlueEnv 24s ease-in-out infinite,geminiDriftB 31s ease-in-out infinite alternate;animation-delay:var(--gdelay,0s),var(--gdelay,0s);transition:filter 1.4s ease-out}
#bg-layer.bg-gemini::after{content:"";position:absolute;inset:0;pointer-events:none;background-image:radial-gradient(45% 90% at 35% -10%,rgba(16,185,129,.70),transparent 70%),radial-gradient(40% 80% at 15% -5%,rgba(190,150,40,.85),transparent 70%);opacity:0;animation:geminiGoldEnv 24s ease-in-out infinite,geminiDriftG 37s ease-in-out infinite alternate;animation-delay:var(--gdelay,0s),var(--gdelay,0s);transition:filter 1.4s ease-out}
#bg-layer.bg-gemini.typing::before,#bg-layer.bg-gemini.typing::after{filter:brightness(1.4) saturate(1.25)}
@keyframes geminiBlueEnv{0%{opacity:0}12%{opacity:.9}25%{opacity:1}40%{opacity:.4}50%{opacity:0}60%{opacity:.4}75%{opacity:1}88%{opacity:.9}100%{opacity:0}}
@keyframes geminiGoldEnv{0%{opacity:0}25%{opacity:0}40%{opacity:.7}50%{opacity:1}60%{opacity:.7}75%{opacity:0}100%{opacity:0}}
@keyframes geminiDriftB{from{transform:translateX(-4%) skewX(-4deg) scale(1)}to{transform:translateX(6%) skewX(4deg) scale(1.08)}}
@keyframes geminiDriftG{from{transform:translateX(5%) skewX(4deg) scale(1.05)}to{transform:translateX(-6%) skewX(-4deg) scale(1.12)}}
@keyframes geminiPulse{0%{filter:hue-rotate(0deg)}100%{filter:hue-rotate(45deg)}}
@media (prefers-reduced-motion: reduce){#bg-layer.bg-gemini,#bg-layer.bg-gemini::before,#bg-layer.bg-gemini::after{animation:none}#bg-layer.bg-gemini::before,#bg-layer.bg-gemini::after{transition:none}#bg-layer.bg-gemini.typing::before,#bg-layer.bg-gemini.typing::after{filter:none}}
/* Backgrounds on pages: with a background active, Glass+ page surfaces turn
   translucent so the background shows through instead of hiding behind opaque
   cards. Theme state keeps today's solid look, and Liquid keeps its own 30%. */
:root[data-glassstyle="plus"][data-bg]:not([data-bg="theme"]) .card,:root[data-glassstyle="plus"][data-bg]:not([data-bg="theme"]) .win,:root[data-glassstyle="plus"][data-bg]:not([data-bg="theme"]) .kpi,:root[data-glassstyle="plus"][data-bg]:not([data-bg="theme"]) .sw,:root[data-glassstyle="plus"][data-bg]:not([data-bg="theme"]) .lo,:root[data-glassstyle="plus"][data-bg]:not([data-bg="theme"]) .lrow,:root[data-glassstyle="plus"][data-bg]:not([data-bg="theme"]) .sc,:root[data-glassstyle="plus"][data-bg]:not([data-bg="theme"]) .quickactions a{background:color-mix(in srgb,var(--surface) 45%,transparent)}
'''

_UI_JS_SRC = r'''
(() => {
  // Voice effects, shared by the Theta page (Theta's speech) and Settings (the voice samples): a clip is run
  // through the effect offline and comes back as a new WAV, so playback itself is never rerouted (Bluetooth,
  // glasses, the avatar's envelope all still work). Picked in either place; saved on this device.
  window.thetaFx = (() => {
    function impulse(ctx, secs, decay) { // a made-up room: noise that fades out
      const n = Math.floor(ctx.sampleRate * secs), b = ctx.createBuffer(2, n, ctx.sampleRate);
      for (let c = 0; c < 2; c++) { const d = b.getChannelData(c); for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, decay); }
      return b;
    }
    function wavOf(buf) { // 16-bit mono WAV
      const d = buf.getChannelData(0), n = d.length, out = new DataView(new ArrayBuffer(44 + n * 2)), sr = buf.sampleRate;
      const str = (o, t) => { for (let i = 0; i < t.length; i++) out.setUint8(o + i, t.charCodeAt(i)); };
      str(0, "RIFF"); out.setUint32(4, 36 + n * 2, true); str(8, "WAVEfmt "); out.setUint32(16, 16, true); out.setUint16(20, 1, true);
      out.setUint16(22, 1, true); out.setUint32(24, sr, true); out.setUint32(28, sr * 2, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true);
      str(36, "data"); out.setUint32(40, n * 2, true);
      let peak = 1e-6; for (let i = 0; i < n; i++) peak = Math.max(peak, Math.abs(d[i]));
      const g = peak > 0.98 ? 0.98 / peak : 1; // effects can add level: never clip
      for (let i = 0; i < n; i++) out.setInt16(44 + i * 2, Math.max(-1, Math.min(1, d[i] * g)) * 0x7fff, true);
      return new Blob([out], {type: "audio/wav"});
    }
    const FX = { // each builds wet = effect(src) into `out`; rate changes pitch and speed together
      robot(c, src, out) { const m = c.createGain(), o = c.createOscillator(); m.gain.value = 0; o.frequency.value = 55; o.connect(m.gain); o.start();
        src.connect(m); m.connect(out); },
      radio(c, src, out) { const hp = c.createBiquadFilter(), lp = c.createBiquadFilter(), pk = c.createBiquadFilter(), sh = c.createWaveShaper();
        hp.type = "highpass"; hp.frequency.value = 420; lp.type = "lowpass"; lp.frequency.value = 3000; pk.type = "peaking"; pk.frequency.value = 1600; pk.gain.value = 7;
        const k = new Float32Array(1024); for (let i = 0; i < 1024; i++) { const x = i / 512 - 1; k[i] = Math.tanh(2.2 * x); } sh.curve = k;
        src.connect(hp); hp.connect(pk); pk.connect(sh); sh.connect(lp); lp.connect(out); },
      jarvis(c, src, out) { // the Iron Man helper's sound: a light flange, presence, a small metal room
        const dl = c.createDelay(0.05), lfo = c.createOscillator(), dep = c.createGain(), fb = c.createGain(), hp = c.createBiquadFilter(), pr = c.createBiquadFilter(), rv = c.createConvolver(), rg = c.createGain();
        dl.delayTime.value = 0.006; lfo.frequency.value = 0.35; dep.gain.value = 0.0025; lfo.connect(dep); dep.connect(dl.delayTime); lfo.start(); fb.gain.value = 0.45;
        hp.type = "highpass"; hp.frequency.value = 140; pr.type = "peaking"; pr.frequency.value = 3200; pr.gain.value = 5;
        rv.buffer = impulse(c, 0.45, 3); rg.gain.value = 0.35;
        src.connect(hp); hp.connect(pr); pr.connect(dl); dl.connect(fb); fb.connect(dl); dl.connect(out); pr.connect(out); pr.connect(rv); rv.connect(rg); rg.connect(out); },
      hologram(c, src, out) { const hp = c.createBiquadFilter(), ec = c.createDelay(1), fb = c.createGain(), rv = c.createConvolver(), rg = c.createGain();
        hp.type = "highpass"; hp.frequency.value = 260; ec.delayTime.value = 0.12; fb.gain.value = 0.32; rv.buffer = impulse(c, 1.2, 2.5); rg.gain.value = 0.4;
        src.connect(hp); hp.connect(out); hp.connect(ec); ec.connect(fb); fb.connect(ec); ec.connect(out); hp.connect(rv); rv.connect(rg); rg.connect(out); },
      space(c, src, out) { const rv = c.createConvolver(); rv.buffer = impulse(c, 2.6, 2); src.connect(rv); rv.connect(out); },
      deep(c, src, out) { const ls = c.createBiquadFilter(); ls.type = "lowshelf"; ls.frequency.value = 220; ls.gain.value = 6; src.connect(ls); ls.connect(out); },
    };
    const FX_RATE = {deep: 0.9}, FX_TAIL = {space: 2.6, hologram: 1.4, jarvis: 0.6};
    async function render(blob, kind, amount) {
      const build = FX[kind];
      if (!build) return blob;
      try {
        const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext; if (!OAC) return blob;
        const buf = await blob.arrayBuffer();
        const audio = await new Promise((ok, no) => { const c0 = new OAC(1, 22050, 22050), r = c0.decodeAudioData(buf, ok, no); if (r && r.then) r.then(ok, no); });
        const rate = FX_RATE[kind] || 1, sr = audio.sampleRate, len = Math.ceil((audio.duration / rate + (FX_TAIL[kind] || 0.1)) * sr);
        const c = new OAC(1, len, sr), src = c.createBufferSource(), dry = c.createGain(), wet = c.createGain(), amt = Math.max(0.1, Math.min(1, (+amount || 60) / 100));
        src.buffer = audio; src.playbackRate.value = rate;
        dry.gain.value = kind === "deep" ? 1 - amt * 0.5 : 1 - amt * 0.85; wet.gain.value = amt;
        src.connect(dry); dry.connect(c.destination); build(c, src, wet); wet.connect(c.destination); src.start();
        return wavOf(await c.startRendering());
      } catch (e) { return blob; } // an effect is a nice-to-have: the plain voice plays if it fails
    }
    const get = (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } };
    const put = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };
    return {render, kind: () => get("theta:fx", "off"), amount: () => get("theta:fxAmt", "60"),
      set(kind, amount) { if (kind != null) put("theta:fx", kind); if (amount != null) put("theta:fxAmt", String(amount)); },
      apply: blob => render(blob, get("theta:fx", "off"), get("theta:fxAmt", "60"))};
  })();


  // Headings that write themselves, per frame: Edge decodes out of binary, Breach out of the breach screen's hex
  // codes, Console types. Plain-text headings only (nothing with markup inside), and never with reduced motion.
  (() => {
    const fr = document.documentElement.dataset.glassstyle, still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const SETS = {edge: "01", breach: ["BD", "55", "1C", "E9", "7A", "FF"]};
    if (still || !(fr in SETS || fr === "console")) return;
    const hs = [...document.querySelectorAll(".main h1, .main h2")].filter(h => !h.children.length && h.textContent.trim()).slice(0, 12);
    hs.forEach((h, i) => {
      const text = h.textContent, n = text.length, start = performance.now() + i * 50, dur = Math.min(700, 260 + n * 22);
      h.setAttribute("aria-label", text); h.style.minHeight = h.offsetHeight + "px";
      const pick = () => { const s = SETS[fr]; return Array.isArray(s) ? s[Math.random() * s.length | 0] : s[Math.random() * s.length | 0]; };
      function step(now) {
        const k = Math.max(0, Math.min(1, (now - start) / dur)), done = Math.floor(k * n);
        if (fr === "console") h.textContent = text.slice(0, done) + (k < 1 ? "█" : "");
        else { let out = text.slice(0, done), j = done; while (j < n) { if (text[j] === " ") { out += " "; j++; continue; } const c = pick(); out += c; j += c.length; } h.textContent = out.slice(0, n); }
        if (k < 1) requestAnimationFrame(step); else { h.textContent = text; h.removeAttribute("aria-label"); h.style.minHeight = ""; }
      }
      step(performance.now()); // scrambled from the first paint, never a flash of the real text first
    });
  })();


  // ---- Frame sounds (picked 2026-11-04 in the Frame Sounds page): each frame's entrance has a short sound,
  // made live with Web Audio (no files). iPhone only plays sound from a tap, and a new page starts without
  // one, so the sound plays from the tap that opens the page, while it loads and the transition runs.
  // Settings, Look: on or off, and volume (saved on this device).
  window.thetaSfx = (() => {
    let ctx = null, NOISE = null;
    const get = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } };
    const on = () => get("theta:sfx", "on") === "on" && !matchMedia("(prefers-reduced-motion: reduce)").matches;
    function ac() {
      const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return null;
      if (!ctx) ctx = new AC(); if (ctx.state === "suspended") ctx.resume().catch(() => {});
      return ctx;
    }
    function noise(c) { if (NOISE && NOISE.sampleRate === c.sampleRate) return NOISE; const n = c.sampleRate, b = c.createBuffer(1, n, n), d = b.getChannelData(0); for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1; return (NOISE = b); }
    function env(c, peak, t, a, d) { const g = c.createGain(); g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(peak, t + a); g.gain.exponentialRampToValueAtTime(0.0001, t + a + d); return g; }
    function tone(c, out, type, f0, f1, t, a, d, peak, filt) {
      const o = c.createOscillator(), g = env(c, peak, t, a, d); o.type = type; o.frequency.setValueAtTime(f0, t);
      if (f1 && f1 !== f0) o.frequency.exponentialRampToValueAtTime(f1, t + a + d * .8);
      let n = o; if (filt) { const f = c.createBiquadFilter(); f.type = filt[0]; f.frequency.value = filt[1]; o.connect(f); n = f; }
      n.connect(g); g.connect(out); o.start(t); o.stop(t + a + d + .05); return o;
    }
    function click(c, out, t, hz, peak, len) {
      const s = c.createBufferSource(), f = c.createBiquadFilter(), g = env(c, peak, t, .001, len || .012);
      s.buffer = noise(c); f.type = "bandpass"; f.frequency.value = hz; f.Q.value = 1.2; s.connect(f); f.connect(g); g.connect(out);
      s.start(t, Math.random() * .5); s.stop(t + (len || .012) + .02);
    }
    // the Theta frames: tiny pips rising as the dots stream in, gathering into a soft chord (each variant its own flavor)
    const swarm = (c, o, t, n, lo, chord) => { for (let i = 0; i < n; i++) { const s = t + i * (.22 / n) + Math.random() * .02, f = lo * (1 + i / n) * (1 + Math.random() * .08); tone(c, o, "sine", f, f * 1.06, s, .002, .03, .05 + .04 * Math.random()); }
      chord.forEach((f, i) => tone(c, o, "sine", f, f, t + .24 + i * .015, .03, .5, .07)); };
    const SOUND = { // the picks: frame -> (ctx, out, t)
      plus(c, o, t) { for (let i = 0; i < 7; i++) { const s = t + Math.random() * .32, f = 600 + Math.random() * 1000; tone(c, o, "sine", f, f * 1.8, s, .003, .035, .12 + Math.random() * .1); } }, // Fizz
      liquid(c, o, t) { const x = tone(c, o, "sine", 180, 420, t, .02, .34, .4, ["lowpass", 900]); const l = c.createOscillator(), d = c.createGain(); l.frequency.value = 17; d.gain.value = 45; l.connect(d); d.connect(x.frequency); l.start(t); l.stop(t + .4); }, // Gloop
      edge(c, o, t) { const h = c.createBiquadFilter(); h.type = "highpass"; h.frequency.value = 500; h.connect(o); for (let i = 0; i < 14; i++) { const f = Math.random() < .5 ? 880 : 1320; tone(c, h, "square", f, f, t + i * .02, .002, .014, .12); } }, // Binary chirp
      breach(c, o, t) { for (let i = 0; i < 7; i++) click(c, o, t + i * .07, 3500, .4, .008); tone(c, o, "sine", 1046, 1046, t + .5, .004, .12, .14); }, // Hex print
      hud(c, o, t) { tone(c, o, "sine", 1200, 1200, t, .003, .04, .2); tone(c, o, "sine", 1200, 1200, t + .12, .003, .04, .2); tone(c, o, "sine", 1600, 1600, t + .26, .004, .14, .24); }, // Target lock
      console(c, o, t) { let s = t; for (let i = 0; i < 9; i++) { click(c, o, s, 4200, .32, .006); click(c, o, s, 300, .18, .01); s += .035 + Math.random() * .03; } }, // Typewriter
      grain(c, o, t) { swarm(c, o, t, 16, 1400, [523, 659, 784]); }, // Dot swarm
      press(c, o, t) { for (let i = 0; i < 6; i++) click(c, o, t + i * .04, 2600, .18, .006); swarm(c, o, t + .1, 10, 1100, [440, 554, 659]); }, // Dot press
      lines(c, o, t) { swarm(c, o, t, 12, 1700, [587, 740, 880, 1175]); }, // Dot constellation
      nebula(c, o, t) { swarm(c, o, t, 22, 900, [392, 494, 587]); }, // Dot nebula
      settle(c, o, t) { swarm(c, o, t, 14, 1200, [523, 784]); tone(c, o, "sine", 1046, 1046, t + .62, .003, .08, .08); }, // Dot settle
      ornate(c, o, t) { [[880, .16, .7], [1320, .09, .55], [1760, .05, .4]].forEach(([f, p, d], i) => tone(c, o, "sine", f, f, t + i * .06, .004, d, p)); }, // Chime (not picked yet)
      holo(c, o, t) { const g = c.createGain(); g.gain.setValueAtTime(.0001, t); g.gain.exponentialRampToValueAtTime(.22, t + .3); g.gain.exponentialRampToValueAtTime(.0001, t + .5); const tr = c.createGain(), l = c.createOscillator(), ld = c.createGain(); l.frequency.value = 12; ld.gain.value = .5; tr.gain.value = .5; l.connect(ld); ld.connect(tr.gain); tr.connect(g); g.connect(o); [110, 220].forEach(f => { const x = c.createOscillator(); x.type = "triangle"; x.frequency.value = f; x.connect(tr); x.start(t); x.stop(t + .55); }); l.start(t); l.stop(t + .55); click(c, o, t + .5, 1500, .3, .015); }, // Projector hum
    };
    function play(frame, force) {
      if (!force && !on()) return false;
      const f = SOUND[frame || document.documentElement.dataset.glassstyle || "plus"]; if (!f) return false;
      try { const c = ac(); if (!c) return false; const out = c.createGain(); out.gain.value = Math.max(0, Math.min(1, +get("theta:sfxVol", "60") / 100)) * 1.2; out.connect(c.destination); f(c, out, c.currentTime + .01); return true; }
      catch (e) { return false; }
    }
    // the first touch anywhere wakes the audio up, so the first sound isn't late
    addEventListener("pointerdown", () => { if (on()) ac(); }, {once: true, capture: true, passive: true});
    // a tap that opens another page of the app plays the frame's sound (before anything can stop the click)
    document.addEventListener("click", e => {
      const a = e.target.closest && e.target.closest("a[href]");
      if (!a || e.metaKey || e.ctrlKey || e.shiftKey || (a.target && a.target !== "_self") || a.hasAttribute("download")) return;
      const u = new URL(a.href, location.href);
      if (u.origin !== location.origin || u.pathname.startsWith("/api/") || (u.pathname === location.pathname && u.search === location.search)) return;
      play();
    }, true);
    return {play, on, set(k, v) { try { localStorage.setItem(k === "vol" ? "theta:sfxVol" : "theta:sfx", String(v)); } catch (e) {} },
      volume: () => +get("theta:sfxVol", "60"), sounds: Object.keys(SOUND)};
  })();

  if (window.top !== window) document.addEventListener("click", e => {
    const a = e.target.closest && e.target.closest("a[href]"); if (!a) return;
    const u = new URL(a.href, location.href);
    if (u.origin === location.origin && u.pathname === "/head") { e.preventDefault(); window.top.location.href = u.pathname + u.search + u.hash; }
  }, true);
  // Where Theta looks: at your cursor (or finger) when it's moving, otherwise where you tilt the phone.
  // Each avatar reads window.thetaLook.at(its center) and gets -1..1 for x and y. The tilt is measured
  // from how you're holding the phone (that drifts back to neutral), so any angle you hold it at is "ahead".
  (() => {
    const L = {px: 0, py: 0, pAt: 0, gx: 0, gy: 0, base: null, on: false};
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const clamp = v => Math.max(-1, Math.min(1, v));
    addEventListener("pointermove", e => { L.px = e.clientX; L.py = e.clientY; L.pAt = performance.now(); }, {passive: true});
    addEventListener("pointerdown", e => { L.px = e.clientX; L.py = e.clientY; L.pAt = performance.now(); }, {passive: true});
    function onTilt(e) {
      if (e.beta == null || e.gamma == null) return;
      if (!L.base) L.base = [e.beta, e.gamma];
      L.base[0] += (e.beta - L.base[0]) * 0.004; L.base[1] += (e.gamma - L.base[1]) * 0.004;
      L.gx = clamp((e.gamma - L.base[1]) / 25); L.gy = clamp((e.beta - L.base[0]) / 25);
    }
    function start() {
      if (L.on || still || !window.DeviceOrientationEvent) return; L.on = true;
      const D = DeviceOrientationEvent;
      if (typeof D.requestPermission === "function")
        D.requestPermission().then(r => { if (r === "granted") addEventListener("deviceorientation", onTilt); }).catch(() => { L.on = false; });
      else addEventListener("deviceorientation", onTilt);
    }
    // iPhone asks for motion once, and only from a tap
    if (window.DeviceOrientationEvent && typeof DeviceOrientationEvent.requestPermission === "function") addEventListener("click", start, {once: true, capture: true});
    else start();
    window.thetaLook = {at(cx, cy) {
      if (still) return [0, 0];
      if (performance.now() - L.pAt < 2500)
        return [clamp((L.px - cx) / (innerWidth * 0.5)), clamp((L.py - cy) / (innerHeight * 0.5))];
      return [L.gx, L.gy];
    }};
  })();

  // Theta in the corner of every page (Urchin Pour, small): wears its last mood's color; a tap flies it
  // to the middle of the Theta page (that page plays the dock move in reverse).
  (() => {
    const a = document.querySelector(".theta-mini"); if (!a) return;
    const cv = a.querySelector("canvas"), g = cv.getContext("2d"), S = cv.width, N = 150, dots = [];
    for (let i = 0; i < N; i++) { const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = i * 2.39996; dots.push([Math.cos(th) * r, y, Math.sin(th) * r, Math.random()]); }
    let hex = "#4fd3ff";
    try { hex = localStorage.getItem("theta:moodColor") || (T[root.dataset.theme] || T.theta || {}).accent2 || hex; } catch (e) {}
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let light = false;
    setTimeout(() => { const m = getComputedStyle(document.body).backgroundColor.match(/\d+/g), layer = document.getElementById("bg-layer");
      light = !(layer && !layer.classList.contains("off")) && !!m && (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) > 150; }, 60);
    const pts = [], look = [0, 0];
    function draw(ms) {
      const r = a.getBoundingClientRect(), want = window.thetaLook ? thetaLook.at(r.left + r.width / 2, r.top + r.height / 2) : [0, 0];
      look[0] += (want[0] - look[0]) * 0.08; look[1] += (want[1] - look[1]) * 0.08;
      cv.style.transform = `translate(${(look[0] * 2.5).toFixed(2)}px,${(look[1] * 2.5).toFixed(2)}px)`;
      const t = ms / 1000 * (reduce ? 0.3 : 1), c = S / 2, R = S * 0.36, yaw = t * 0.5 + look[0] * 0.8, pit = 0.32 + look[1] * 0.6,
        cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pit), sp = Math.sin(pit);
      g.clearRect(0, 0, S, S); pts.length = 0;
      for (const [x, y, z, s] of dots) {
        const k = 1 + 0.05 * Math.sin(t * 1.4 + y * 4) + (s > 0.85 ? 0.12 * Math.abs(Math.sin(t * 2 + s * 30)) : 0);
        const x1 = x * cy - z * sy, z1 = x * sy + z * cy, y2 = y * cp - z1 * sp, z2 = y * sp + z1 * cp, pr = 3.2 / (3.2 + z2);
        pts.push([c + x1 * k * R * pr, c + y2 * k * R * pr, z2, pr]);
      }
      pts.sort((p, q) => q[2] - p[2]);
      g.globalCompositeOperation = light ? "source-over" : "lighter"; g.fillStyle = hex;
      for (const [px, py, z, pr] of pts) { g.globalAlpha = Math.max(0.15, Math.min(1, 0.65 - z * 0.55)); g.beginPath(); g.arc(px, py, S * 0.018 * pr * pr, 0, 7); g.fill(); }
      g.globalAlpha = 1; g.globalCompositeOperation = "source-over";
      const gr = g.createRadialGradient(c, c, 0, c, c, S * 0.2); gr.addColorStop(0, "#fff"); gr.addColorStop(0.3, hex); gr.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = gr; g.beginPath(); g.arc(c, c, S * 0.2, 0, 7); g.fill();
      requestAnimationFrame(draw);
    }
    requestAnimationFrame(draw);
    a.addEventListener("click", () => { try { sessionStorage.setItem("theta:fromCorner", "1"); } catch (e) {} });
  })();

  // Theme, mode and layout live in the theta_ui cookie so pages render
  // with them from the server (no flash). __THEMES__ is filled in by the hub.
  const T = __THEMES__;
  const root = document.documentElement;
  const KEY = new URLSearchParams(location.search).get("key") || "";
  window.THETA_H = {"Content-Type": "application/json", "x-dashboard-key": KEY};
  // The server set the login cookie with this response, so take the key out
  // of the address bar (and so out of screenshots, history and shared links).
  if (KEY) {
    const u = new URL(location.href);
    u.searchParams.delete("key");
    history.replaceState(null, "", u.pathname + u.search + u.hash);
  }
  // Face ID lock (window.THETA_LOCK, set when it's on for this device): going
  // to the background hides the page and tells the hub; coming back, the hub
  // says whether Face ID is needed, and if so the page reloads to the lock.
  if (window.THETA_LOCK) {
    const away = () => { root.classList.add("veiled");
      try { navigator.sendBeacon("/api/lock/away", new Blob(["{}"], {type: "application/json"})); } catch (_) {} };
    const back = async () => {
      try {
        const d = await (await fetch("/api/lock/status", {cache: "no-store"})).json();
        if (d.locked) { location.reload(); return; }
      } catch (_) { location.reload(); return; }
      root.classList.remove("veiled");
    };
    document.addEventListener("visibilitychange", () => document.hidden ? away() : back());
    window.addEventListener("pageshow", e => { if (e.persisted) back(); });
  }
  const dark = matchMedia("(prefers-color-scheme: dark)");
  const WIDE = matchMedia("(color-gamut: p3)").matches;
  // Shard blue tints in Display P3 on P3 displays; white is already at gamut max.
  function tintB(a) { return WIDE ? "color(display-p3 0.72 0.88 1 / " + a + ")" : "rgba(215,230,255," + a + ")"; }
  function metaColors() {
    const t = T[root.dataset.theme] || T.theta, m = root.dataset.mode;
    document.querySelectorAll('meta[name="theme-color"]').forEach(x => x.remove());
    const mk = (c, media) => {
      const el = document.createElement("meta");
      el.name = "theme-color"; el.content = c;
      if (media) el.media = media;
      document.head.append(el);
    };
    if (m === "auto") { mk(t.light, "(prefers-color-scheme: light)"); mk(t.dark, "(prefers-color-scheme: dark)"); }
    else mk(m === "dark" ? t.dark : t.light);
  }
  function save() {
    document.cookie = "theta_ui=" + [root.dataset.theme, root.dataset.mode, root.dataset.layout, (root.dataset.glassstyle || "plus"), (root.dataset.bg || "theme"), (root.dataset.type || "frame")].join(".")
      + ";path=/;max-age=31536000;samesite=lax";
  }
  function mark() {
    document.querySelectorAll("[data-pref]").forEach(b => {
      const on = root.dataset[b.dataset.pref] === b.dataset.val;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    });
  }
  function setPref(k, v) {
    if (k === "theme") {
      const t = T[v];
      if (!t) return;
      root.dataset.theme = v;
      if (t.glass) root.setAttribute("data-glass", ""); else root.removeAttribute("data-glass");
      if (t.mono) root.dataset.font = "mono"; else delete root.dataset.font;
    } else {
      root.dataset[k] = v;
      if (k === "glassstyle" && window.thetaSfx) thetaSfx.play(v); // picking a frame plays its sound
    }
    metaColors(); save(); mark();
  }
  window.thetaPref = setPref;
  document.addEventListener("click", e => {
    const b = e.target.closest("[data-pref]");
    if (b) { e.preventDefault(); setPref(b.dataset.pref, b.dataset.val); }
  });
  mark();
  if (dark.addEventListener) dark.addEventListener("change", metaColors);

  // "Run a round" (Home and Settings)
  document.querySelectorAll("[data-run-round]").forEach(btn => btn.onclick = async () => {
    const out = document.getElementById(btn.dataset.runRound);
    btn.disabled = true;
    if (out) out.textContent = "Running every agent's job. This can take up to a minute...";
    try {
      const d = await (await fetch("/api/round", {method: "POST", headers: THETA_H, body: JSON.stringify({force: true})})).json();
      if (!d.ok) throw new Error(d.error);
      const failed = Object.entries(d.ran || {}).filter(([, r]) => !r.ok).map(([a]) => a);
      if (out) out.textContent = "Done" + (failed.length ? " (" + failed.join(", ") + " failed; see #command)" : "") + ". Refreshing...";
      setTimeout(() => location.reload(), 900);
    } catch (err) {
      if (out) out.textContent = "Round failed: " + err.message;
      btn.disabled = false;
    }
  });

  // A bar shows at once when a tap opens another page, so a slow server
  // never looks like a missed tap.
  document.addEventListener("click", e => {
    const a = e.target.closest && e.target.closest("a[href]");
    if (!a || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || a.target || a.hasAttribute("download")) return;
    const u = new URL(a.href, location.href);
    if (u.origin !== location.origin || (u.pathname === location.pathname && u.search === location.search)) return;
    setTimeout(() => { if (!e.defaultPrevented) root.classList.add("nav-wait"); }, 0);
  });
  addEventListener("pageshow", () => root.classList.remove("nav-wait"));

  // Smart stack: the dots follow the card in view.
  document.querySelectorAll(".smart").forEach(st => {
    const track = st.querySelector(".sc-track"), dots = st.querySelectorAll(".sc-dots i");
    if (!track || !dots.length) return;
    track.addEventListener("scroll", () => {
      const i = Math.round(track.scrollLeft / (track.firstElementChild.offsetWidth + 12));
      dots.forEach((d, j) => d.classList.toggle("on", j === i));
    }, {passive: true});
  });

  // Glass shine on window pictures: follows the cursor over a picture, or
  // the phone's tilt when that's switched on (iPhone asks once, on a tap).
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let shineFrame = 0;
  function shine(el, x, y) {
    cancelAnimationFrame(shineFrame);
    shineFrame = requestAnimationFrame(() => { el.style.setProperty("--gx", x + "%"); el.style.setProperty("--gy", y + "%"); });
  }
  if (!still) {
    document.addEventListener("pointermove", e => {
      if (e.pointerType !== "mouse") return;
      const pic = e.target.closest && e.target.closest(".pic");
      if (!pic) return;
      const r = pic.getBoundingClientRect();
      shine(pic, Math.round((e.clientX - r.left) / r.width * 100), Math.round((e.clientY - r.top) / r.height * 100));
    });
    document.addEventListener("pointerout", e => {
      const pic = e.target.closest && e.target.closest(".pic");
      if (pic && !pic.contains(e.relatedTarget)) { pic.style.removeProperty("--gx"); pic.style.removeProperty("--gy"); }
    });
  }
  let tilt = false;
  try { tilt = localStorage.getItem("theta_tilt") === "on"; } catch (_) {}
  // Tilt moves the shine on the pictures in view only: setting it on the whole
  // page made iPhones restyle every blurred card ~60 times a second, and taps lagged.
  const shinePics = new Set();
  const io = "IntersectionObserver" in window ? new IntersectionObserver(es => es.forEach(x =>
    x.isIntersecting ? shinePics.add(x.target) : shinePics.delete(x.target))) : null;
  const watchPics = () => io && document.querySelectorAll(".pic").forEach(p => io.observe(p));
  let lastTilt = 0, tx = -1, ty = -1;
  function onTilt(e) {
    if (e.gamma == null || document.hidden) return;
    const now = performance.now();
    if (now - lastTilt < 50) return;  // 20 updates a second is plenty
    const x = Math.round(Math.max(0, Math.min(100, 50 + e.gamma * 1.6))), y = Math.round(Math.max(0, Math.min(100, 50 + (e.beta - 45) * 1.2)));
    if (Math.abs(x - tx) < 2 && Math.abs(y - ty) < 2) return;  // too small to see
    lastTilt = now; tx = x; ty = y;
    cancelAnimationFrame(shineFrame);
    shineFrame = requestAnimationFrame(() => shinePics.forEach(p => { p.style.setProperty("--gx", x + "%"); p.style.setProperty("--gy", y + "%"); }));
  }
  async function startTilt() {
    const D = window.DeviceOrientationEvent;
    if (!D || still) return false;
    if (typeof D.requestPermission === "function") {
      try { if ((await D.requestPermission()) !== "granted") return false; } catch (_) { return false; }
    }
    watchPics();
    addEventListener("deviceorientation", onTilt);
    return true;
  }
  if (tilt && !(window.DeviceOrientationEvent && typeof DeviceOrientationEvent.requestPermission === "function")) startTilt();
  else if (tilt) addEventListener("pointerdown", () => startTilt(), {once: true});  // iPhone: permission needs a tap
  function markTilt() { document.querySelectorAll("[data-tilt]").forEach(b => b.classList.toggle("on", (b.dataset.tilt === "on") === tilt)); }
  markTilt();
  document.addEventListener("click", async e => {
    const b = e.target.closest("[data-tilt]");
    if (!b) return;
    tilt = b.dataset.tilt === "on";
    if (tilt && !(await startTilt())) {
      tilt = false;
      const n = document.getElementById("tilt-note"); if (n) n.textContent = "Motion access wasn't allowed, so the shine follows taps only.";
    }
    if (!tilt) { removeEventListener("deviceorientation", onTilt); shinePics.forEach(p => { p.style.removeProperty("--gx"); p.style.removeProperty("--gy"); }); }
    try { localStorage.setItem("theta_tilt", tilt ? "on" : "off"); } catch (_) {}
    markTilt();
  });

  // Liquid Glass edge light follows the phone's gyro and the
  // cursor: the inset highlights shift with tilt or pointer.
  // Liquid mode only, throttled, and never with reduced
  // motion. Unlike the picture shine it is not gated on the
  // shine setting; iOS still needs one tap to allow motion,
  // and touch position covers a denied request.
  let edgeX = 0, edgeY = 0, edgeLast = 0, edgeFrame = 0, edgeGyroStarted = false;
  const edgeLiquid = () => (document.documentElement.dataset.glassstyle || "") === "liquid"; // the hologram stays still (2026-11-06)
  function edgeSet(x, y) {
    if (still || !edgeLiquid()) return;
    const now = performance.now();
    if (now - edgeLast < 50) return;
    x = Math.max(-1, Math.min(1, x)); y = Math.max(-1, Math.min(1, y));
    if (Math.abs(x - edgeX) < 0.05 && Math.abs(y - edgeY) < 0.05) return;
    edgeLast = now; edgeX = x; edgeY = y;
    cancelAnimationFrame(edgeFrame);
    edgeFrame = requestAnimationFrame(() => {
      document.documentElement.style.setProperty("--shine-x", edgeX.toFixed(2));
      document.documentElement.style.setProperty("--shine-y", edgeY.toFixed(2));
    });
  }
  document.addEventListener("pointermove", e => {
    if (e.pointerType !== "mouse") return;
    edgeSet(e.clientX / innerWidth * 2 - 1, e.clientY / innerHeight * 2 - 1);
  });
  document.addEventListener("touchmove", e => {
    const t = e.touches && e.touches[0]; if (!t) return;
    edgeSet(t.clientX / innerWidth * 2 - 1, t.clientY / innerHeight * 2 - 1);
  }, {passive: true});
  async function startEdgeGyro() {
    const D = window.DeviceOrientationEvent;
    if (!D || still) return false;
    if (typeof D.requestPermission === "function") {
      try { if ((await D.requestPermission()) !== "granted") return false; } catch (_) { return false; }
    }
    addEventListener("deviceorientation", e => {
      if (e.gamma == null || document.hidden) return;
      edgeSet(e.gamma / 45, (e.beta - 45) / 45);
    });
    return true;
  }
  if (!(window.DeviceOrientationEvent && typeof DeviceOrientationEvent.requestPermission === "function")) { edgeGyroStarted = true; startEdgeGyro(); }
  else addEventListener("pointerdown", () => { if (edgeGyroStarted || !edgeLiquid()) return; edgeGyroStarted = true; startEdgeGyro(); });

  // Animated backgrounds: Settings -> Background, independent of themes.
  // The layer sits behind all content (z-index -1); canvas modes draw one
  // frame immediately, then animate with rAF (which pauses while hidden).
  (function () {
    var root = document.documentElement;
    var layer = null, cv = null, ctx = null, raf = 0, mode = "", W = 0, H = 0;
    var reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    var rnd = function (a, b) { return a + Math.random() * (b - a); };
    function ensure() {
      if (layer) return;
      layer = document.createElement("div"); layer.id = "bg-layer";
      layer.style.setProperty("--gdelay", (-(Date.now() / 1000 % 24)).toFixed(2) + "s");
      cv = document.createElement("canvas"); layer.appendChild(cv);
      document.body.prepend(layer);
      ctx = cv.getContext("2d");
      addEventListener("resize", function () {
        size();
        if (mode === "stars") initStars();
        else if (mode === "shards") { if (webglOn) resize3D(); else initShards(); }
      });
    }
    function size() {
      var d = Math.min(devicePixelRatio || 1, 2);
      W = innerWidth; H = innerHeight;
      cv.width = Math.round(W * d); cv.height = Math.round(H * d);
      ctx.setTransform(d, 0, 0, d, 0, 0);
    }
    // Stars: fixed positions, twinkling alpha.
    var stars = [];
    // Stars (2026-11-06): the sky is made of Theta's dots. Depth (near stars bigger and brighter), a tint from Theta's
    // mood, a slow twinkle, and the same life as the avatar: while Theta speaks the stars near it brighten with its
    // voice, while it listens they lean toward it, while it thinks the sky turns slowly around it. window.thetaStars
    // hands the opening the stars to gather into Theta.
    var starHue = 195, starHueAt = -9, starLv = 0, starSpin = 0;
    function initStars() {
      stars = [];
      var n = Math.round(Math.min(420, Math.max(160, W * H / 2600)));
      for (var i = 0; i < n; i++) { var d = Math.random(); stars.push({x: Math.random() * W, y: Math.random() * H, d: d, r: .4 + 1.25 * d * d, p: Math.random() * 6.283, s: rnd(.4, 1.6), hue: (Math.random() - .5) * 40}); }
      window.thetaStars = {list: function () { return stars; }, size: function () { return [W, H]; }};
    }
    function starMoodHue() {
      var c = getComputedStyle(document.documentElement).getPropertyValue("--mood").trim() || getComputedStyle(document.documentElement).getPropertyValue("--accent2").trim();
      var m = c.match(/^#([0-9a-f]{6})$/i); if (!m) return starHue;
      var n = parseInt(m[1], 16), r = (n >> 16 & 255) / 255, g = (n >> 8 & 255) / 255, b = (n & 255) / 255, mx = Math.max(r, g, b), mn = Math.min(r, g, b), dd = mx - mn;
      if (!dd) return starHue; var h = mx === r ? ((g - b) / dd) % 6 : mx === g ? (b - r) / dd + 2 : (r - g) / dd + 4; return (h * 60 + 360) % 360;
    }
    function drawStars(t) {
      ctx.fillStyle = "#000"; ctx.fillRect(0, 0, W, H);
      if (t - starHueAt > 2) { starHue = starMoodHue(); starHueAt = t; }
      var TH = window.thetaHead, state = TH && TH.state ? TH.state() : "idle", lv = TH && TH.level ? TH.level() : 0;
      starLv += (lv - starLv) * .2; starSpin += (state === "thinking" ? .00035 : 0);
      var av = document.getElementById("head-av"), ax = W / 2, ay = H * .33;
      if (av) { var rr = av.getBoundingClientRect(); if (rr.width) { ax = rr.left + rr.width / 2; ay = rr.top + rr.height / 2; } }
      var cs = Math.cos(starSpin), sn = Math.sin(starSpin);
      ctx.globalCompositeOperation = "lighter";
      for (var i = 0; i < stars.length; i++) {
        var st = stars[i], x = st.x, y = st.y;
        if (starSpin) { var dx = x - ax, dy = y - ay; x = ax + dx * cs - dy * sn; y = ay + dx * sn + dy * cs; }
        var dist = Math.hypot(x - ax, y - ay), near = Math.max(0, 1 - dist / (Math.min(W, H) * .7));
        if (state === "listening") { x += (ax - x) / (dist || 1) * 6 * near; y += (ay - y) / (dist || 1) * 6 * near; }
        var tw = .5 + .5 * Math.sin(t * st.s + st.p), glow = state === "speaking" ? starLv * near * (.6 + .4 * Math.sin(dist * .05 - t * 6)) : 0;
        ctx.globalAlpha = Math.min(1, (.12 + .58 * st.d) * (.45 + .55 * tw) + glow * .6);
        ctx.fillStyle = "hsl(" + ((starHue + st.hue) % 360) + "," + Math.round(25 + 30 * st.d + 30 * glow) + "%," + Math.round(82 + 10 * glow) + "%)";
        ctx.beginPath(); ctx.arc(x, y, st.r * (1 + .6 * glow), 0, 6.283); ctx.fill();
      }
      ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over";
    }
    // Shards: many small bright glass fragments, drifting and tumbling.
    // They catch the light as they turn (brightness follows the tumble),
    // bounce off the walls, and bump into each other. A few larger hero
    // shards read as the bright glints; the rest are tiny slivers, white
    // with a pale blue tone on some, on pure black.
    var shards = [];
    var massPts = [];
    var fgPts = [];
    function initShards() {
      shards = [];
      var n = Math.round(Math.min(500, Math.max(300, W * H / 1800)));
      for (var i = 0; i < n; i++) {
        var cluster = Math.random() < 0.75;
        var hero = Math.random() < (cluster ? 0.15 : 0.03);
        var pl = Math.random();
        var near = pl < 0.08 && cluster, far = pl > 0.60;
        var r = near ? (hero ? rnd(6, 8) : rnd(5, 7))
          : far ? rnd(0.5, 0.9)
          : cluster ? (hero ? rnd(3, 4.5) : rnd(1.5, 3)) : (hero ? rnd(2.5, 4) : rnd(1, 2.5)), vs = [];
        var nv = near ? 7 + Math.floor(Math.random() * 3) : 7 + Math.floor(Math.random() * 5);
        for (var j = 0; j < nv; j++) vs.push({a: j / nv * 6.283 + rnd(near ? -.8 : -.5, near ? .8 : .5), d: r * (near ? rnd(.25, 1.25) : rnd(.35, 1.1))});
        var bm = hero ? rnd(.85, 1) : Math.random() < 0.6 ? rnd(.1, .3) : Math.random() < 0.75 ? rnd(.3, .6) : rnd(.6, .85);
        if (cluster) bm = Math.max(bm, rnd(.55, .9));
        // Dense cluster mass in the right third, densest at the edge,
        // thinning leftward like the reference.
        var sx = cluster ? W * (2 / 3 + Math.pow(Math.random(), 0.35) / 3)
          : W * Math.pow(Math.random(), 0.6);
        sx = Math.min(W - r, Math.max(r, sx));
        // Half the shards get a chipped notch: one vertex pulled hard
        // toward the center, so the silhouette reads broken, not drawn.
        if (near) {
          var c1 = Math.floor(Math.random() * nv), c2 = (c1 + 1 + Math.floor(Math.random() * (nv - 1))) % nv;
          vs[c1].d *= 0.35; vs[c2].d *= 0.45;
        } else if (Math.random() < 0.5) vs[Math.floor(Math.random() * nv)].d *= 0.45;
        var sy = cluster ? H * (0.5 + (Math.random() + Math.random() + Math.random() - 1.5) / 3 * 0.9) : rnd(r, H - r);
        sy = Math.min(H - r, Math.max(r, sy));
        shards.push({x: sx, y: sy, vx: rnd(-20, 20), vy: rnd(-16, 16), r: r, rot: Math.random() * 6.28, vr: rnd(-.6, .6), rx: Math.random() * 6.28, ry: Math.random() * 6.28, vrx: rnd(-.5, .5), vry: rnd(-.5, .5), z: near ? rnd(120, 250) : far ? rnd(-250, -100) : rnd(-100, 100), vs: vs, p: Math.random() * 6.28, hero: hero, bm: bm, st: near ? rnd(1.0, 1.5) : rnd(.8, 1.4), fe: Math.floor(Math.random() * nv), fe2: Math.floor(Math.random() * nv), blue: Math.random() < 0.25, cl: cluster});
      }
      // Burst-mass thicket: several hundred tiny faint specks packed
      // into the same right-edge band, overlapping the prism shards.
      massPts = [];
      var mn = Math.min(2400, Math.max(1400, W * H / 750));
      for (var mi = 0; mi < mn; mi++) {
        var mx = W * (0.8 + Math.pow(Math.random(), 0.3) / 5);
        var my = H * (0.5 + (Math.random() + Math.random() + Math.random() - 1.5) / 3 * 0.6);
        var mid = Math.random() < 0.07;
      massPts.push({x: Math.min(W - 1, Math.max(1, mx)), y: Math.min(H - 1, Math.max(1, my)), vx: rnd(-8, 8), vy: rnd(-6, 6), z: rnd(-100, 100), s: mid ? rnd(1.6, 3.2) : rnd(0.5, 2), a: mid ? (Math.random() < 0.3 ? rnd(0.5, 0.9) : rnd(0.25, 0.55)) : (Math.random() < 0.1 ? rnd(0.5, 0.9) : rnd(0.08, 0.35)), blue: Math.random() < 0.25, rot: Math.random() * 6.283});
      }
      // Sparse foreground tier: isolated near-plane shards in the
      // open field, clear of the dense column, so the eye has near
      // glass to judge distance against.
      fgPts = [];
      for (var fi = 0; fi < 14; fi++) {
        var fs = rnd(2.0, 3.7);
        fgPts.push({x: W * rnd(0.05, 0.6), y: rnd(fs * 4, H - fs * 4), vx: rnd(-8, 8), vy: rnd(-6, 6), z: rnd(120, 250), s: fs, a: rnd(0.35, 0.7), blue: Math.random() < 0.25, rot: Math.random() * 6.283});
      }
    }
    // Shared physics: drift, tumble on all axes, wall bounce,
    // collisions. The 2D painter and the 3D renderer both step this.
    function stepShards(dt) {
      for (var i = 0; i < shards.length; i++) {
        var a = shards[i];
        a.x += a.vx * dt; a.y += a.vy * dt; a.rot += a.vr * dt;
        a.rx += a.vrx * dt; a.ry += a.vry * dt;
        if (a.x < a.r) { a.x = a.r; a.vx = Math.abs(a.vx); }
        if (a.x > W - a.r) { a.x = W - a.r; a.vx = -Math.abs(a.vx); }
        if (a.y < a.r) { a.y = a.r; a.vy = Math.abs(a.vy); }
        if (a.y > H - a.r) { a.y = H - a.r; a.vy = -Math.abs(a.vy); }
        if (a.cl && a.y < H * 0.2) { a.y = H * 0.2; a.vy = Math.abs(a.vy); }
        if (a.cl && a.y > H * 0.8) { a.y = H * 0.8; a.vy = -Math.abs(a.vy); }
        for (var j = i + 1; j < shards.length; j++) {
          var b = shards[j];
          if (a.r < 2.5 || b.r < 2.5) continue;
          var dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy), min = a.r + b.r;
          if (d > 0 && d < min) {
            var nx = dx / d, ny = dy / d, ov = (min - d) / 2;
            a.x -= nx * ov; a.y -= ny * ov; b.x += nx * ov; b.y += ny * ov;
            var p = (a.vx - b.vx) * nx + (a.vy - b.vy) * ny;
            if (p > 0) { a.vx -= p * nx; a.vy -= p * ny; b.vx += p * nx; b.vy += p * ny; }
          }
        }
      }
      for (var mi = 0; mi < massPts.length; mi++) {
        var mp = massPts[mi];
        mp.x += mp.vx * dt; mp.y += mp.vy * dt;
        if (mp.x < 1) { mp.x = 1; mp.vx = Math.abs(mp.vx); }
        if (mp.x > W - 1) { mp.x = W - 1; mp.vx = -Math.abs(mp.vx); }
        if (mp.y < H * 0.3) { mp.y = H * 0.3; mp.vy = Math.abs(mp.vy); }
        if (mp.y > H * 0.7) { mp.y = H * 0.7; mp.vy = -Math.abs(mp.vy); }
      }
      for (var fi = 0; fi < fgPts.length; fi++) {
        var fp = fgPts[fi];
        fp.x += fp.vx * dt; fp.y += fp.vy * dt;
        if (fp.x < 1) { fp.x = 1; fp.vx = Math.abs(fp.vx); }
        if (fp.x > W - 1) { fp.x = W - 1; fp.vx = -Math.abs(fp.vx); }
        if (fp.y < 1) { fp.y = 1; fp.vy = Math.abs(fp.vy); }
        if (fp.y > H - 1) { fp.y = H - 1; fp.vy = -Math.abs(fp.vy); }
      }
    }
    function drawShards(dt) {
      ctx.fillStyle = "#000"; ctx.fillRect(0, 0, W, H);
      stepShards(dt);
      // Light is fixed in the world (top-left); shards tumble under it,
      // so edges light up selectively instead of glowing uniformly.
      var LX = -0.707, LY = -0.707;
      for (var k = 0; k < shards.length; k++) {
        var sh = shards[k];
        // Facets catch the light as the shard tumbles: brightness rides
        // the rotation, so glints sweep across the field.
        var g = 0.5 + 0.5 * Math.sin(sh.rot * 2 + sh.p);
        var al = (sh.hero ? 0.55 + 0.45 * g : 0.15 + 0.7 * g) * sh.bm;
        var pts = [];
        for (var m = 0; m < sh.vs.length; m++) {
          var v = sh.vs[m], lx = Math.cos(v.a) * v.d * sh.st, ly = Math.sin(v.a) * v.d;
          pts.push([sh.x + lx * Math.cos(sh.rot) - ly * Math.sin(sh.rot), sh.y + lx * Math.sin(sh.rot) + ly * Math.cos(sh.rot)]);
        }
        var trace = function() {
          ctx.beginPath();
          for (var q = 0; q < pts.length; q++) { if (q) ctx.lineTo(pts[q][0], pts[q][1]); else ctx.moveTo(pts[q][0], pts[q][1]); }
          ctx.closePath();
        };
        var ccx = 0, ccy = 0;
        for (var n = 0; n < pts.length; n++) { ccx += pts[n][0]; ccy += pts[n][1]; }
        ccx /= pts.length; ccy /= pts.length;
        // Body: light falls across it from the top-left and dies into
        // the dark — never a flat fill.
        var gr = ctx.createLinearGradient(sh.x + LX * sh.r, sh.y + LY * sh.r, sh.x - LX * sh.r, sh.y - LY * sh.r);
        gr.addColorStop(0, sh.blue ? tintB(0.04 + al * 0.18) : "rgba(255,255,255," + (0.04 + al * 0.18) + ")");
        gr.addColorStop(1, sh.blue ? "rgba(160,180,210," + (0.01 + al * 0.04) + ")" : "rgba(140,150,170," + (0.01 + al * 0.04) + ")");
        trace();
        ctx.fillStyle = gr;
        ctx.fill();
        // Two refractive facets at different angles to the light.
        var facet = function(f, a2) {
          var p1 = pts[f], p2 = pts[(f + 1) % pts.length];
          var ex = p2[0] - p1[0], ey = p2[1] - p1[1], el = Math.hypot(ex, ey) || 1;
          var nx = ey / el, ny = -ex / el;
          var mx = (p1[0] + p2[0]) / 2 - ccx, my = (p1[1] + p2[1]) / 2 - ccy;
          if (nx * mx + ny * my < 0) { nx = -nx; ny = -ny; }
          var lit = Math.max(0, nx * LX + ny * LY);
          ctx.beginPath();
          ctx.moveTo(p1[0], p1[1]);
          ctx.lineTo(p2[0], p2[1]);
          ctx.lineTo(ccx, ccy);
          ctx.closePath();
          ctx.fillStyle = sh.blue ? tintB(a2 * (0.35 + 0.65 * lit)) : "rgba(255,255,255," + (a2 * (0.35 + 0.65 * lit)) + ")";
          ctx.fill();
        };
        facet(sh.fe, al * 0.35);
        facet(sh.fe2, al * 0.18);
        // Rim: ONLY edges facing the light get stroked — the rest of
        // the outline falls dark, so no shard wears a uniform outline.
        ctx.beginPath();
        for (var e = 0; e < pts.length; e++) {
          var p1 = pts[e], p2 = pts[(e + 1) % pts.length];
          var ex = p2[0] - p1[0], ey = p2[1] - p1[1], el = Math.hypot(ex, ey) || 1;
          var nx = ey / el, ny = -ex / el;
          var mx = (p1[0] + p2[0]) / 2 - ccx, my = (p1[1] + p2[1]) / 2 - ccy;
          if (nx * mx + ny * my < 0) { nx = -nx; ny = -ny; }
          if (nx * LX + ny * LY > 0.15) { ctx.moveTo(p1[0], p1[1]); ctx.lineTo(p2[0], p2[1]); }
        }
        ctx.strokeStyle = sh.hero ? "rgba(255,255,255,1)" : "rgba(255,255,255," + Math.min(1, al + 0.3) + ")";
        ctx.lineWidth = sh.hero ? 1.5 : 1;
        ctx.stroke();
        // Hero glint: a hard specular catch as the facet turns to light.
        if (sh.hero && g > 0.75) {
          var bi = 0, bd = -2;
          for (var w = 0; w < pts.length; w++) {
            var dd = (pts[w][0] - sh.x) * LX + (pts[w][1] - sh.y) * LY;
            if (dd > bd) { bd = dd; bi = w; }
          }
          ctx.beginPath();
          ctx.arc(pts[bi][0], pts[bi][1], 1.5, 0, 6.283);
          ctx.fillStyle = "rgba(255,255,255,0.9)";
          ctx.fill();
        }
      }
      for (var mi = 0; mi < massPts.length; mi++) {
        var mp = massPts[mi];
        var depS = mp.z > 33 ? 1.35 : (mp.z < -33 ? 0.75 : 1.0);
        var depB = mp.z > 33 ? 1.3 : (mp.z < -33 ? 0.7 : 1.0);
        var depR = mp.z > 33 ? 1.5 : (mp.z < -33 ? 0.6 : 1.0);
        var ss = mp.s * depS, aa = mp.a * depB;
        var gx = -Math.sin(mp.rot), gy = Math.cos(mp.rot);
        var gg = ctx.createLinearGradient(mp.x - gx * ss, mp.y - gy * ss, mp.x + gx * ss, mp.y + gy * ss);
        gg.addColorStop(0, "rgba(115,128,158," + (aa * 0.56) + ")");
        gg.addColorStop(1, "rgba(115,128,158," + (aa * 1.04) + ")");
        ctx.fillStyle = gg;
        ctx.beginPath();
        for (var k = 0; k <= 24; k++) {
          var a = k / 24 * 6.283;
          var rr = 1 + 0.20 * Math.sin(3 * a + mp.rot) + 0.14 * Math.sin(5 * a + mp.rot * 1.7) + 0.08 * Math.sin(8 * a + mp.rot * 2.3);
          var lx = Math.cos(a) * ss * 2.5 * rr, ly = Math.sin(a) * ss * 1.0 * rr;
          var wx = mp.x + lx * Math.cos(mp.rot) - ly * Math.sin(mp.rot);
          var wy = mp.y + lx * Math.sin(mp.rot) + ly * Math.cos(mp.rot);
          if (k === 0) ctx.moveTo(wx, wy); else ctx.lineTo(wx, wy);
        }
        ctx.closePath();
        ctx.fill();
        var rimG = ctx.createLinearGradient(mp.x - gx * ss, mp.y - gy * ss, mp.x + gx * ss, mp.y + gy * ss);
        rimG.addColorStop(0, "rgba(115,128,158," + (aa * 0.15) + ")");
        rimG.addColorStop(1, mp.blue ? tintB(aa * 0.7 * depR) : "rgba(255,255,255," + (aa * 0.7 * depR) + ")");
        ctx.strokeStyle = rimG;
        ctx.lineWidth = Math.max(1, ss * 0.5);
        ctx.stroke();
        ctx.fillStyle = mp.blue ? tintB(aa) : "rgba(255,255,255," + aa + ")";
        ctx.beginPath();
        ctx.ellipse(mp.x, mp.y, ss * 0.375, ss * 0.15, mp.rot, 0, 6.283);
        ctx.fill();
      }
      for (var fi = 0; fi < fgPts.length; fi++) {
        var mp = fgPts[fi];
        var depS = mp.z > 33 ? 1.35 : (mp.z < -33 ? 0.75 : 1.0);
        var depB = mp.z > 33 ? 1.3 : (mp.z < -33 ? 0.7 : 1.0);
        var depR = mp.z > 33 ? 1.5 : (mp.z < -33 ? 0.6 : 1.0);
        var ss = mp.s * depS, aa = mp.a * depB;
        var gx = -Math.sin(mp.rot), gy = Math.cos(mp.rot);
        var gg = ctx.createLinearGradient(mp.x - gx * ss, mp.y - gy * ss, mp.x + gx * ss, mp.y + gy * ss);
        gg.addColorStop(0, "rgba(115,128,158," + (aa * 0.56) + ")");
        gg.addColorStop(1, "rgba(115,128,158," + (aa * 1.04) + ")");
        ctx.fillStyle = gg;
        ctx.beginPath();
        for (var k = 0; k <= 24; k++) {
          var a = k / 24 * 6.283;
          var rr = 1 + 0.20 * Math.sin(3 * a + mp.rot) + 0.14 * Math.sin(5 * a + mp.rot * 1.7) + 0.08 * Math.sin(8 * a + mp.rot * 2.3);
          var lx = Math.cos(a) * ss * 2.5 * rr, ly = Math.sin(a) * ss * 1.0 * rr;
          var wx = mp.x + lx * Math.cos(mp.rot) - ly * Math.sin(mp.rot);
          var wy = mp.y + lx * Math.sin(mp.rot) + ly * Math.cos(mp.rot);
          if (k === 0) ctx.moveTo(wx, wy); else ctx.lineTo(wx, wy);
        }
        ctx.closePath();
        ctx.fill();
        var rimG = ctx.createLinearGradient(mp.x - gx * ss, mp.y - gy * ss, mp.x + gx * ss, mp.y + gy * ss);
        rimG.addColorStop(0, "rgba(115,128,158," + (aa * 0.15) + ")");
        rimG.addColorStop(1, mp.blue ? tintB(aa * 0.7 * depR) : "rgba(255,255,255," + (aa * 0.7 * depR) + ")");
        ctx.strokeStyle = rimG;
        ctx.lineWidth = Math.max(1, ss * 0.5);
        ctx.stroke();
        ctx.fillStyle = mp.blue ? tintB(aa) : "rgba(255,255,255," + aa + ")";
        ctx.beginPath();
        ctx.ellipse(mp.x, mp.y, ss * 0.375, ss * 0.15, mp.rot, 0, 6.283);
        ctx.fill();
      }
    }
    // Shards in real 3D: actual prism geometry rendered with a small
    // raw-WebGL glass shader (fresnel rims + speculars from fixed
    // lights, real depth occlusion). No library, no network: the app
    // stays self-contained, and any WebGL failure leaves the 2D
    // painter in place, so Shards never breaks — it only gets flatter.
    var webgl = null, webglOn = false;
    // Column-major 4x4 helpers: enough for projection * model.
    function mMul(a, b) {
      var o = [];
      for (var c = 0; c < 4; c++) for (var r = 0; r < 4; r++) {
        o[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
      }
      return o;
    }
    function mPersp(fov, asp, nr, fr) {
      var f = 1 / Math.tan(fov / 2), d = nr - fr;
      return [f / asp, 0, 0, 0, 0, f, 0, 0, 0, 0, (fr + nr) / d, -1, 0, 0, 2 * fr * nr / d, 0];
    }
    function mTrans(x, y, z) { return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]; }
    function mRotX(a) { var c = Math.cos(a), s = Math.sin(a); return [1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1]; }
    function mRotY(a) { var c = Math.cos(a), s = Math.sin(a); return [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1]; }
    function mRotZ(a) { var c = Math.cos(a), s = Math.sin(a); return [c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]; }
    // A jagged prism: the shard's 2D outline extruded with slightly
    // uneven front/back faces, so every facet catches light differently.
    // Returns interleaved positions + flat face normals (non-indexed).
    function shardPrism(vs, st, th) {
      var pts = vs.map(function (v) { return [Math.cos(v.a) * v.d * st, Math.sin(v.a) * v.d]; });
      var cx = 0, cy = 0;
      for (var i = 0; i < pts.length; i++) { cx += pts[i][0]; cy += pts[i][1]; }
      cx /= pts.length; cy /= pts.length;
      var fz = [], bz = [];
      for (var i = 0; i < pts.length; i++) { fz.push(th / 2 + rnd(-0.4, 0.4) * th); bz.push(-th / 2 + rnd(-0.4, 0.4) * th); }
      var pos = [], nor = [], bar = [];
      var tri = function (a, b, c) {
        var ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2];
        var vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
        var nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
        var nl = Math.hypot(nx, ny, nz) || 1;
        pos.push(a[0], a[1], a[2], b[0], b[1], b[2], c[0], c[1], c[2]);
        for (var k = 0; k < 3; k++) nor.push(nx / nl, ny / nl, nz / nl);
        bar.push(1, 0, 0, 0, 1, 0, 0, 0, 1);
      };
      for (var i = 0; i < pts.length; i++) {
        var p = pts[i], q = pts[(i + 1) % pts.length], ni = (i + 1) % pts.length;
        tri([cx, cy, th / 2], [p[0], p[1], fz[i]], [q[0], q[1], fz[ni]]);
        tri([cx, cy, -th / 2], [q[0], q[1], bz[ni]], [p[0], p[1], bz[i]]);
        tri([p[0], p[1], fz[i]], [q[0], q[1], fz[ni]], [q[0], q[1], bz[ni]]);
        tri([p[0], p[1], fz[i]], [q[0], q[1], bz[ni]], [p[0], p[1], bz[i]]);
      }
      return {pos: pos, nor: nor, bar: bar};
    }
    function initShards3D() {
      var wcv = document.createElement("canvas");
      wcv.setAttribute("data-engine", "webgl");
      wcv.style.cssText = "position:absolute;inset:0;width:100%;height:100%;display:block";
      layer.appendChild(wcv);
      var d = Math.min(devicePixelRatio || 1, 2);
      wcv.width = Math.round(W * d); wcv.height = Math.round(H * d);
      var gl = wcv.getContext("webgl", {antialias: true, alpha: false, preserveDrawingBuffer: true});
      if (!gl) throw 0;
      var vs = "attribute vec3 position; attribute vec3 normal; attribute vec3 bary; uniform mat4 mvp; uniform mat4 model; varying vec3 vN; varying vec3 vW; varying vec3 vBary; void main() { vN = mat3(model) * normal; vec4 w = model * vec4(position, 1.0); vW = w.xyz; vBary = bary; gl_Position = mvp * vec4(position, 1.0); }";
      var fsBase = "precision mediump float; varying vec3 vN; varying vec3 vW; uniform vec3 tint; uniform vec3 cam; uniform float glow; void main() { vec3 N = normalize(vN) * (gl_FrontFacing ? 1.0 : -1.0); vec3 V = normalize(cam - vW); float fres = pow(1.0 - abs(dot(N, V)), 3.0); vec3 L1 = normalize(vec3(-0.6, 0.6, 1.0)); vec3 L2 = normalize(vec3(0.8, -0.3, 0.6)); float d1 = max(dot(reflect(-L1, N), V), 0.0); float d2 = max(dot(reflect(-L2, N), V), 0.0); float spec = pow(d1, 80.0) + pow(d1, 24.0) * 0.7 + pow(d2, 80.0) * 0.6; float a = clamp(0.35 + fres * 0.45 + spec, 0.0, 1.0) * glow; vec3 col = (tint * (0.16 + fres * 0.6) + vec3(1.0) * spec) * glow; "; 
      var fsEdge = "#extension GL_OES_standard_derivatives : enable\nprecision mediump float; varying vec3 vN; varying vec3 vW; varying vec3 vBary; uniform vec3 tint; uniform vec3 cam; uniform float glow; void main() { vec3 N = normalize(vN) * (gl_FrontFacing ? 1.0 : -1.0); vec3 V = normalize(cam - vW); float fres = pow(1.0 - abs(dot(N, V)), 3.0); vec3 L1 = normalize(vec3(-0.6, 0.6, 1.0)); vec3 L2 = normalize(vec3(0.8, -0.3, 0.6)); float d1 = max(dot(reflect(-L1, N), V), 0.0); float d2 = max(dot(reflect(-L2, N), V), 0.0); float spec = pow(d1, 80.0) + pow(d1, 24.0) * 0.7 + pow(d2, 80.0) * 0.6; float e = min(min(vBary.x, vBary.y), vBary.z); float line = 1.0 - smoothstep(0.0, fwidth(e) * 1.5, e); float nl = max(dot(N, L1), 0.0); float edgeGlow = pow(nl, 4.0); float a = clamp(0.35 + fres * 0.45 + spec + line * 0.2 * edgeGlow, 0.0, 1.0) * glow; vec3 col = (tint * (0.16 + fres * 0.6) + vec3(1.0) * spec + vec3(1.0) * line * 0.8 * edgeGlow) * glow; "; 
      var fs = fsBase + "gl_FragColor = vec4(col, a); }"; 
      var fsE = fsEdge + "gl_FragColor = vec4(col, a); }"; 
      var useEdge = !!gl.getExtension("OES_standard_derivatives");
      var sh = function (t, src) { var s = gl.createShader(t); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw 0; return s; };
      var prog = gl.createProgram();
      gl.attachShader(prog, sh(gl.VERTEX_SHADER, vs));
      gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, useEdge ? fsE : fs));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw 0;
      gl.useProgram(prog);
      var loc = {pos: gl.getAttribLocation(prog, "position"), nor: gl.getAttribLocation(prog, "normal"), bar: gl.getAttribLocation(prog, "bary"), mvp: gl.getUniformLocation(prog, "mvp"), model: gl.getUniformLocation(prog, "model"), tint: gl.getUniformLocation(prog, "tint"), cam: gl.getUniformLocation(prog, "cam"), glow: gl.getUniformLocation(prog, "glow")};
      gl.enable(gl.DEPTH_TEST);
      gl.depthMask(false);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.viewport(0, 0, wcv.width, wcv.height);
      var meshes = [];
      var list = shards.slice(0, 320);
      for (var i = 0; i < list.length; i++) {
        var s2 = list[i];
        var g = shardPrism(s2.vs, s2.st, Math.max(1, s2.r * 0.6));
        var buf = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, buf);
        var data = new Float32Array(g.pos.length + g.nor.length + g.bar.length);
        for (var k = 0; k < g.pos.length / 3; k++) {
          data[k * 9] = g.pos[k * 3]; data[k * 9 + 1] = g.pos[k * 3 + 1]; data[k * 9 + 2] = g.pos[k * 3 + 2];
          data[k * 9 + 3] = g.nor[k * 3]; data[k * 9 + 4] = g.nor[k * 3 + 1]; data[k * 9 + 5] = g.nor[k * 3 + 2];
          data[k * 9 + 6] = g.bar[k * 3]; data[k * 9 + 7] = g.bar[k * 3 + 1]; data[k * 9 + 8] = g.bar[k * 3 + 2];
        }
        gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
        meshes.push([s2, buf, g.pos.length / 3, s2.blue ? [0.84, 0.90, 1.0] : [1.0, 1.0, 1.0], s2.hero ? 1.8 : 1.0]);
      }
      var dist = (H / 2) / Math.tan(22.5 * Math.PI / 180);
      webgl = {gl: gl, prog: prog, loc: loc, meshes: meshes, wcv: wcv, dist: dist, proj: mPersp(45 * Math.PI / 180, W / H, 1, 5000), view: mTrans(0, 0, -dist)};
      try {
        var pvs = "attribute vec2 aXY; attribute float aSize; attribute float aAlpha; attribute float aBlue; attribute float aRot; attribute float aZ; varying float vA; varying float vB; varying float vR; varying float vZ; void main() { vA = aAlpha; vB = aBlue; vR = aRot; vZ = aZ; gl_PointSize = aSize * (aZ > 33.0 ? 1.35 : (aZ < -33.0 ? 0.75 : 1.0)); gl_Position = vec4(aXY, 0.0, 1.0); }";
        var pfs = "precision mediump float; varying float vA; varying float vB; varying float vR; varying float vZ; void main() { float depB = vZ > 33.0 ? 1.3 : (vZ < -33.0 ? 0.7 : 1.0); float depR = vZ > 33.0 ? 1.5 : (vZ < -33.0 ? 0.6 : 1.0); vec2 pc = gl_PointCoord - 0.5; float cc = cos(vR), ss = sin(vR); vec2 rp = vec2(pc.x * cc - pc.y * ss, pc.x * ss + pc.y * cc); vec2 ev = vec2(rp.x * 2.0, rp.y * 5.0); float ang = atan(ev.y, ev.x); float jag = 1.0 + 0.20 * sin(3.0 * ang + vR) + 0.14 * sin(5.0 * ang + vR * 1.7) + 0.08 * sin(8.0 * ang + vR * 2.3); float dd = length(ev) / jag; float body = smoothstep(1.0, 0.55, dd) * 0.8; float core = smoothstep(0.15, 0.0, dd); float fac = 0.7 + 0.6 * smoothstep(-0.15, 0.15, rp.y); vec3 coreCol = mix(vec3(1.0), vec3(0.84, 0.90, 1.0), vB); float rimBand = smoothstep(0.75, 0.92, dd) * (1.0 - smoothstep(0.92, 1.0, dd)); float rim = rimBand * smoothstep(-0.05, 0.15, rp.y) * depR; vec3 col = mix(mix(vec3(0.45, 0.5, 0.62), coreCol, core) * fac, coreCol, rim * 0.7); gl_FragColor = vec4(col, vA * depB * (body * fac + core * 0.2 + rim * 0.5)); }";
        var pprog = gl.createProgram();
        gl.attachShader(pprog, sh(gl.VERTEX_SHADER, pvs));
        gl.attachShader(pprog, sh(gl.FRAGMENT_SHADER, pfs));
        gl.linkProgram(pprog);
        if (!gl.getProgramParameter(pprog, gl.LINK_STATUS)) throw 0;
        webgl.pts = {prog: pprog, buf: gl.createBuffer(), loc: {xy: gl.getAttribLocation(pprog, "aXY"), size: gl.getAttribLocation(pprog, "aSize"), alpha: gl.getAttribLocation(pprog, "aAlpha"), blue: gl.getAttribLocation(pprog, "aBlue"), rot: gl.getAttribLocation(pprog, "aRot"), z: gl.getAttribLocation(pprog, "aZ")}, dpr: d};
      } catch (e) { webgl.pts = null; }
      cv.style.display = "none";
      webglOn = true;
    }
    function drawShards3D(dt) {
      stepShards(dt);
      var gl = webgl.gl, loc = webgl.loc;
      gl.clearColor(0, 0, 0, 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.useProgram(webgl.prog);
      gl.uniform3f(loc.cam, 0, 0, webgl.dist);
      for (var i = 0; i < webgl.meshes.length; i++) {
        var m = webgl.meshes[i], sh = m[0];
        var model = mMul(mTrans(sh.x - W / 2, -(sh.y - H / 2), sh.z), mMul(mRotX(sh.rx), mMul(mRotY(sh.ry), mRotZ(sh.rot))));
        gl.uniformMatrix4fv(loc.model, false, new Float32Array(model));
        gl.uniformMatrix4fv(loc.mvp, false, new Float32Array(mMul(webgl.proj, mMul(webgl.view, model))));
        gl.uniform3f(loc.tint, m[3][0], m[3][1], m[3][2]);
        var pf = sh.z > 100 ? 0.5 : sh.z < -100 ? 0.6 : 0.9;
        gl.uniform1f(loc.glow, m[4] * (1.0 + sh.z / 300.0) * pf);
        gl.bindBuffer(gl.ARRAY_BUFFER, m[1]);
        gl.enableVertexAttribArray(loc.pos);
        gl.vertexAttribPointer(loc.pos, 3, gl.FLOAT, false, 36, 0);
        gl.enableVertexAttribArray(loc.nor);
        gl.vertexAttribPointer(loc.nor, 3, gl.FLOAT, false, 36, 12);
        if (loc.bar >= 0) {
          gl.enableVertexAttribArray(loc.bar);
          gl.vertexAttribPointer(loc.bar, 3, gl.FLOAT, false, 36, 24);
        }
        gl.drawArrays(gl.TRIANGLES, 0, m[2]);
      }
      if (webgl.pts) {
        var pts = webgl.pts, f = 1 / Math.tan(22.5 * Math.PI / 180), asp = W / H;
        var pd = new Float32Array((massPts.length + fgPts.length) * 7);
        for (var pi = 0; pi < massPts.length; pi++) {
          var mp = massPts[pi], den = webgl.dist - mp.z;
          pd[pi * 7] = (f / asp * (mp.x - W / 2)) / den;
          pd[pi * 7 + 1] = (f * (-(mp.y - H / 2))) / den;
          pd[pi * 7 + 2] = mp.s * 5 * pts.dpr * (webgl.dist / den);
          pd[pi * 7 + 3] = mp.a;
          pd[pi * 7 + 4] = mp.blue ? 1 : 0;
          pd[pi * 7 + 5] = mp.rot;
          pd[pi * 7 + 6] = mp.z;
        }
        for (var fi = 0; fi < fgPts.length; fi++) {
          var mp = fgPts[fi], den = webgl.dist - mp.z, pi = massPts.length + fi;
          pd[pi * 7] = (f / asp * (mp.x - W / 2)) / den;
          pd[pi * 7 + 1] = (f * (-(mp.y - H / 2))) / den;
          pd[pi * 7 + 2] = mp.s * 5 * pts.dpr * (webgl.dist / den);
          pd[pi * 7 + 3] = mp.a;
          pd[pi * 7 + 4] = mp.blue ? 1 : 0;
          pd[pi * 7 + 5] = mp.rot;
          pd[pi * 7 + 6] = mp.z;
        }
        gl.useProgram(pts.prog);
        gl.bindBuffer(gl.ARRAY_BUFFER, pts.buf);
        gl.bufferData(gl.ARRAY_BUFFER, pd, gl.DYNAMIC_DRAW);
        gl.enableVertexAttribArray(pts.loc.xy);
        gl.vertexAttribPointer(pts.loc.xy, 2, gl.FLOAT, false, 28, 0);
        gl.enableVertexAttribArray(pts.loc.size);
        gl.vertexAttribPointer(pts.loc.size, 1, gl.FLOAT, false, 28, 8);
        gl.enableVertexAttribArray(pts.loc.alpha);
        gl.vertexAttribPointer(pts.loc.alpha, 1, gl.FLOAT, false, 28, 12);
        gl.enableVertexAttribArray(pts.loc.blue);
        gl.vertexAttribPointer(pts.loc.blue, 1, gl.FLOAT, false, 28, 16);
        gl.enableVertexAttribArray(pts.loc.rot);
        gl.vertexAttribPointer(pts.loc.rot, 1, gl.FLOAT, false, 28, 20);
        gl.enableVertexAttribArray(pts.loc.z);
        gl.vertexAttribPointer(pts.loc.z, 1, gl.FLOAT, false, 28, 24);
        gl.drawArrays(gl.POINTS, 0, massPts.length + fgPts.length);
      }
    }
    function resize3D() {
      var d = Math.min(devicePixelRatio || 1, 2);
      webgl.wcv.width = Math.round(W * d); webgl.wcv.height = Math.round(H * d);
      webgl.gl.viewport(0, 0, webgl.wcv.width, webgl.wcv.height);
      webgl.dist = (H / 2) / Math.tan(22.5 * Math.PI / 180);
      webgl.view = mTrans(0, 0, -webgl.dist);
      webgl.proj = mPersp(45 * Math.PI / 180, W / H, 1, 5000);
    }
    function dispose3D() {
      if (!webgl) return;
      for (var i = 0; i < webgl.meshes.length; i++) webgl.gl.deleteBuffer(webgl.meshes[i][1]);
      if (webgl.pts) { webgl.gl.deleteBuffer(webgl.pts.buf); webgl.gl.deleteProgram(webgl.pts.prog); }
      webgl.gl.getExtension("WEBGL_lose_context");
      var c = webgl.wcv;
      if (c && c.parentNode) c.parentNode.removeChild(c);
      webgl = null; webglOn = false;
      if (cv) cv.style.display = "";
    }
    function ensure3D() {
      if (webglOn || !layer) return;
      try {
        initShards3D();
        if (reduced) drawShards3D(0);
        else if (!raf) raf = requestAnimationFrame(function (t) { frame(t, t); });
      } catch (e) { dispose3D(); }
    }
    function frame(t, last) {
      var dt = Math.min(.05, (t - last) / 1000 || 0);
      if (mode === "stars") drawStars(t / 1000); else if (mode === "shards") { if (webglOn) drawShards3D(dt); else drawShards(dt); }
      if (mode === "stars" || mode === "shards") raf = requestAnimationFrame(function (nt) { frame(nt, t); });
    }
    // Your picture (Settings, Background): kept on this device, shown behind everything, dimmed a little.
    function pics() { var a = layer.querySelectorAll(".bgpic"); if (a.length) return a;
      for (var i = 0; i < 2; i++) { var d = document.createElement("div"); d.className = "bgpic"; layer.appendChild(d); } return layer.querySelectorAll(".bgpic"); }
    function showPicture() {
      var src = ""; try { src = localStorage.getItem("theta:bgimg") || ""; } catch (e) {}
      var p = pics(); p[0].style.backgroundImage = src ? 'url("' + src + '")' : ""; p[0].classList.add("on"); p[1].classList.remove("on");
    }
    // Spotlight: upcoming movies, shows and games you'd care about, one picture at a time, with where it was found.
    var spot = {items: [], i: 0, timer: 0, cap: null, front: 0};
    function stopSpot() { clearInterval(spot.timer); spot.timer = 0; if (spot.cap) { spot.cap.remove(); spot.cap = null; }
      if (layer) layer.querySelectorAll(".bgpic").forEach(function (d) { d.style.backgroundImage = ""; d.classList.remove("on"); }); }
    function spotShow() {
      var it = spot.items[spot.i % spot.items.length]; if (!it) return;
      var img = new Image(); img.onload = function () {
        var p = pics(), next = 1 - spot.front;
        p[next].style.backgroundImage = 'url("' + it.image + '")'; p[next].classList.add("on"); p[spot.front].classList.remove("on"); spot.front = next;
        if (spot.cap) {
          var when = it.date ? (it.days <= 0 ? "Out now" : it.days === 1 ? "Out tomorrow" : it.days < 45 ? "In " + it.days + " days" : new Date(it.date + "T12:00").toLocaleDateString(undefined, {month: "short", day: "numeric", year: "numeric"})) : "";
          spot.cap.querySelector(".sp-why").textContent = it.why + (when ? " \u00b7 " + when : "");
          var ti = spot.cap.querySelector(".sp-title"); ti.textContent = it.title + (when ? " \u00b7 " + when : ""); ti.title = it.why;
          var a = spot.cap.querySelector(".sp-src"); a.href = it.url; a.textContent = it.site.replace(/^(themoviedb\.org)$/, "TMDB") + " \u2197";
          a.setAttribute("aria-label", "Found on " + it.site);
          spot.cap.classList.remove("in"); void spot.cap.offsetWidth; spot.cap.classList.add("in");
        }
      };
      img.src = it.image; spot.i++;
    }
    function startSpot() {
      showPicture(); pics()[0].style.backgroundImage = "";
      if (window.top !== window) return; // inside the Theta page's sheet: the page behind already shows it
      if (!spot.cap) { spot.cap = document.createElement("div"); spot.cap.className = "spot-cap";
        spot.cap.innerHTML = '<span class="sp-why"></span><b class="sp-title"></b><a class="sp-src" target="_blank" rel="noopener"></a>';
        document.body.appendChild(spot.cap); }
      fetch("/api/spotlight", {headers: window.THETA_H || {}}).then(function (r) { return r.json(); }).then(function (d) {
        spot.items = (d && d.items) || []; spot.i = 0;
        if (!spot.items.length) { spot.cap.querySelector(".sp-title").textContent = "Nothing coming up yet"; spot.cap.querySelector(".sp-why").textContent = "Spotlight"; spot.cap.classList.add("in"); return; }
        spotShow(); if (!reduced) spot.timer = setInterval(function () { if (!document.hidden) spotShow(); }, 15000);
      }).catch(function () {});
    }
    function applyBg() {
      var v = root.dataset.bg || "theme";
      if (v === "theme") { dispose3D(); if (layer) layer.className = "off"; cancelAnimationFrame(raf); mode = ""; return; }
      ensure(); size();
      layer.className = "bg-" + v;
      cancelAnimationFrame(raf);
      stopSpot();
      if (v === "stars") { dispose3D(); mode = "stars"; initStars(); drawStars(0); }
      else if (v === "shards") { dispose3D(); mode = "shards"; initShards(); drawShards(0); ensure3D(); }
      else if (v === "image") { dispose3D(); mode = ""; showPicture(); return; }
      else if (v === "spotlight") { dispose3D(); mode = ""; startSpot(); return; }
      else { mode = ""; return; }
      if (!reduced) raf = requestAnimationFrame(function (t) { frame(t, t); });
    }
    new MutationObserver(function (ms) {
      for (var i = 0; i < ms.length; i++) if (ms[i].attributeName === "data-bg") applyBg();
    }).observe(root, {attributes: true});
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", applyBg);
    else applyBg();
    var typeTimer = 0;
    document.addEventListener("input", function (e) {
      if (e.target && e.target.id === "chat-msg" && layer) {
        layer.classList.add("typing");
        clearTimeout(typeTimer);
        typeTimer = setTimeout(function () { if (layer) layer.classList.remove("typing"); }, 1500);
      }
    });
  })();

  // A bar runs across the top while the next page loads.
  const bar = document.createElement("div");
  bar.id = "loadbar"; document.body.append(bar);
  addEventListener("pageshow", () => { bar.className = ""; bar.style.opacity = ""; });

  // Tapping a window opens its sheet: the whole text, where it came from and
  // who covered it. Its link still works without the script.
  const dlg = document.createElement("dialog");
  dlg.className = "sheet"; dlg.setAttribute("aria-label", "Details");
  document.body.append(dlg);
  dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });
  const el = (tag, cls, text) => { const x = document.createElement(tag); if (cls) x.className = cls; if (text) x.textContent = text; return x; };
  // Remi's sheet: Done for what's waiting, and a box to add a reminder.
  async function remPost(url, body) {
    const r = await fetch(url, {method: "POST", headers: window.THETA_H, body: JSON.stringify(body || {})});
    const d = await r.json().catch(() => ({}));
    if (!d.ok) throw new Error(d.error || "Couldn't reach Remi");
    return d;
  }
  function remindBox(rm) {
    const box = el("div", "remind"), note = el("p", "note");
    (rm.pending || []).forEach(([id, what]) => {
      const row = el("div", "brow"), b = el("button", "btn small", "Done");
      b.type = "button";
      b.onclick = async () => { b.disabled = true; try { await remPost("/api/reminders/" + id + "/done"); if (window.thetaCheer) { const r = b.getBoundingClientRect(); thetaCheer(r.left + r.width / 2, r.top + r.height / 2); } row.remove(); note.textContent = "Marked done: " + what; } catch (e) { note.textContent = e.message; b.disabled = false; } };
      row.append(el("span", "", what), b); box.append(row);
    });
    const f = el("form", "box"), inp = el("input"), add = el("button", "btn small", "Add");
    inp.placeholder = "8am every day take my meds until done"; inp.setAttribute("aria-label", "New reminder");
    inp.enterKeyHint = "done"; add.type = "submit"; f.append(inp, add);
    f.onsubmit = async e => {
      e.preventDefault(); const text = inp.value.trim(); if (!text) return;
      add.disabled = true; note.textContent = "Setting it...";
      try { const d = await remPost("/api/reminders", {text}); note.textContent = "Set: " + d.line; inp.value = ""; }
      catch (err) { note.textContent = err.message; }
      add.disabled = false;
    };
    box.append(el("h3", "", "Add a reminder"), f, note);
    return box;
  }
  function openSheet(w) {
    let d;
    try { d = JSON.parse(w.dataset.sheet); } catch (_) { return false; }
    const close = el("button", "x", "\u00d7");
    close.type = "button"; close.setAttribute("aria-label", "Close"); close.onclick = () => dlg.close();
    const scroll = el("div", "scroll"), inn = el("div", "in");
    scroll.append(w.querySelector(".pic").cloneNode(true));
    inn.append(w.querySelector(".who").cloneNode(true), el("h2", "", d.title));
    if (d.sub && d.sub !== d.text) inn.append(el("p", "muted small", d.sub));
    if (d.text) inn.append(el("div", "text", d.text));
    const cov = d.coverage || {};
    if (Object.values(cov).some(x => x && x.length)) {
      const box = el("div", "covlist");
      box.append(el("h3", "", "Who covered it"));
      for (const [k, label] of [["red", "Red"], ["gray", "Gray"], ["blue", "Blue"]]) {
        const row = el("div"), b = el("b", "", label);
        row.append(b, (cov[k] || []).length ? (cov[k] || []).join(", ") : "none of their outlets");
        box.append(row);
      }
      inn.append(box);
    }
    const acts = el("div", "acts");
    (d.links || []).forEach(([label, url], i) => {
      const a = el("a", "btn" + (i ? " ghost" : ""), label);
      a.href = url;
      if (/^https?:/.test(url)) { a.target = "_blank"; a.rel = "noopener"; a.textContent = "Read at " + label + " \u2197"; }
      acts.append(a);
    });
    if (d.remind) inn.append(remindBox(d.remind));
    if (d.agent === "lenz") {
      const w2 = el("a", "btn", "I've watched it"); w2.href = "/lenz?log=" + encodeURIComponent(d.title);
      acts.append(w2);
    }
    if (d.page) {
      const ask = el("a", "btn ghost", "Ask " + d.name); ask.href = "/chat?to=" + d.agent;
      const pg = el("a", "btn ghost", d.name + "'s page"); pg.href = d.page;
      if (/^https?:/.test(d.page)) { pg.target = "_blank"; pg.rel = "noopener"; }
      acts.append(ask, pg);
    }
    inn.append(acts);
    scroll.append(inn);
    dlg.replaceChildren(el("div", "grab"), close, scroll);
    dlg.showModal();
    scroll.scrollTop = 0;
    return true;
  }
  document.addEventListener("click", e => {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey) return;
    const w = e.target.closest(".win[data-sheet]");
    if (w && typeof dlg.showModal === "function") {
      e.preventDefault();
      if (!openSheet(w)) location.href = w.href;
      return;
    }
    const a = e.target.closest("a[href]");
    if (a && !a.target && a.origin === location.origin && !a.hash) {
      bar.className = ""; void bar.offsetWidth; bar.className = "go";
    }
  });

  // Unread dots on Chat and its channels. What you've read is kept on this
  // device; the newest message per channel comes with each page.
  const LATEST = window.THETA_LATEST || {};
  let seen = null;
  try { seen = JSON.parse(localStorage.getItem("theta_seen") || "null"); } catch (_) {}
  const saveSeen = () => { try { localStorage.setItem("theta_seen", JSON.stringify(seen)); } catch (_) {} };
  if (!seen) { seen = Object.assign({}, LATEST); saveSeen(); }  // a first visit starts with nothing unread
  const unread = c => (LATEST[c] || 0) > (seen[c] || 0);
  function paintDots() {
    const any = Object.keys(LATEST).some(unread);
    document.querySelectorAll('a[href="/chat"]').forEach(a => a.classList.toggle("unread", any));
    document.querySelectorAll('a[href^="/chat?ch="]').forEach(a => {
      const c = new URL(a.href).searchParams.get("ch");
      a.classList.toggle("unread", c === "all" ? any : unread(c));
    });
  }
  window.thetaSeen = (ch, id) => { if (typeof id === "number" && id > (seen[ch] || 0)) { seen[ch] = id; saveSeen(); } };
  window.thetaLatest = obj => { Object.assign(LATEST, obj || {}); paintDots(); };
  window.thetaPaintDots = paintDots;
  paintDots();

  // Persistent mini chat bar: Send submits through /api/allchat, the
  // same endpoint and payload the full composer uses, instead of only
  // opening chat with a draft. Replies land in channel "all" and show
  // up when the user opens chat; a pending rid lets chat resume the
  // working indicator. Without JS the form still GETs to /chat with
  // ?say=, so nothing is lost.
  const mb = document.querySelector(".minibar form.minibox");
  if (mb) {
    const input = mb.querySelector("input"), send = mb.querySelector("button[type=submit]");
    const status = mb.parentNode.querySelector(".minibar-status");
    let sending = false;
    input.addEventListener("input", () => { if (status) status.hidden = true; });
    mb.addEventListener("submit", async e => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text || sending) return;
      sending = true; send.disabled = true;
      const rid = Math.random().toString(36).slice(2, 12);
      try { sessionStorage.setItem("theta-pending-rid", rid); } catch (_) {}
      try {
        const d = await (await fetch("/api/allchat", {method: "POST", headers: window.THETA_H, body: JSON.stringify({text, channel: "all", rid})})).json();
        if (!d.ok) throw new Error(d.error || "couldn't send");
        input.value = "";
        if (status) {
          status.replaceChildren();
          if (d.command) status.textContent = d.result || "Done.";
          else { status.append("Sent — "); const a = document.createElement("a"); a.href = "/chat"; a.textContent = "see it in Chat"; status.append(a); }
          status.hidden = false;
        }
      } catch (err) {
        try { sessionStorage.removeItem("theta-pending-rid"); } catch (_) {}
        input.value = text;
        if (status) { status.textContent = "Couldn't send: " + (err.message || "network error"); status.hidden = false; }
      } finally { sending = false; send.disabled = false; }
    });
  }
})();
'''

# All Agents chat, Discord-style (channels, avatars, @ and / menus).
_CHAT_JS = r'''
(() => {
  // Discord-style chat over the All Agents thread. HUB_CHAT: {channel,
  // channels, agents: {id: {name, color, tier}}, to, draft}; HUB_MENU: @ and / lists.
  const C = window.HUB_CHAT, H = window.THETA_H;
  const box = document.getElementById("msgs"), form = document.getElementById("chat-form");
  const msg = document.getElementById("chat-msg"), btn = document.getElementById("chat-send");
  let sending = false;  // explicit in-flight guard: a disabled button alone does not stop Enter resubmits
  const status = document.getElementById("chat-status");
  let thread = [], lastIds = new Set(), first = true;
  const touch = matchMedia("(pointer: coarse)").matches;

  const parseAt = s => s ? new Date(s.replace(" ", "T") + "Z") : new Date();
  const clock = d => d.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
  const dayLabel = d => {
    const t = new Date(), y = new Date(Date.now() - 864e5);
    if (d.toDateString() === t.toDateString()) return "Today";
    if (d.toDateString() === y.toDateString()) return "Yesterday";
    return d.toLocaleDateString([], {weekday: "long", month: "long", day: "numeric"});
  };
  function avatar(id, size) {
    const img = document.createElement("img");
    img.src = "/avatar/" + (C.agents[id] || id === "you" || id === "hub" ? id : "hub") + ".svg";
    img.width = img.height = size; img.alt = ""; img.className = "av";
    return img;
  }
  function cel(tag, cls, txt) { const x = document.createElement(tag); if (cls) x.className = cls; if (txt != null) x.textContent = txt; return x; };
  const SVGNS = "http://www.w3.org/2000/svg";
  function iconSvg(kind) {
    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    if (kind === "check") {
      const pl = document.createElementNS(SVGNS, "polyline");
      pl.setAttribute("points", "20 6 9 17 4 12"); svg.append(pl);
    } else if (kind === "share") {
      const pa = document.createElementNS(SVGNS, "path");
      pa.setAttribute("d", "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4");
      const pl = document.createElementNS(SVGNS, "polyline");
      pl.setAttribute("points", "17 8 12 3 7 8");
      const ln = document.createElementNS(SVGNS, "line");
      ln.setAttribute("x1", "12"); ln.setAttribute("y1", "3"); ln.setAttribute("x2", "12"); ln.setAttribute("y2", "15");
      svg.append(pa, pl, ln);
    } else if (kind === "more") {
      for (const cx of [5, 12, 19]) {
        const c = document.createElementNS(SVGNS, "circle");
        c.setAttribute("cx", cx); c.setAttribute("cy", "12"); c.setAttribute("r", "1"); svg.append(c);
      }
    } else {
      const r = document.createElementNS(SVGNS, "rect");
      r.setAttribute("x", "9"); r.setAttribute("y", "9"); r.setAttribute("width", "13"); r.setAttribute("height", "13"); r.setAttribute("rx", "2"); svg.append(r);
      const pa = document.createElementNS(SVGNS, "path");
      pa.setAttribute("d", "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"); svg.append(pa);
    }
    return svg;
  }
  function copyBtn(getText, icon, cls, label) {
    const b = icon ? cel("button", cls || "cbtn") : cel("button", "btn small ghost", "Copy");
    b.type = "button";
    if (icon) { b.append(iconSvg("copy")); b.setAttribute("aria-label", label || "Copy code"); }
    b.onclick = async () => {
      let ok = false;
      try { await navigator.clipboard.writeText(getText()); ok = true; }
      catch (_) {
        try {
          const ta = document.createElement("textarea");
          ta.value = getText(); ta.style.cssText = "position:fixed;opacity:0";
          document.body.append(ta); ta.select();
          ok = document.execCommand("copy"); ta.remove();
        } catch (_) { ok = false; }
      }
      if (icon) { b.replaceChildren(iconSvg(ok ? "check" : "copy")); b.setAttribute("aria-label", ok ? "Copied" : "Copy failed"); }
      else { b.textContent = ok ? "Copied" : "Copy failed"; }
      b.classList.toggle("is-success", ok); b.classList.toggle("is-error", !ok);
      setTimeout(() => { if (icon) { b.replaceChildren(iconSvg("copy")); b.setAttribute("aria-label", label || "Copy code"); } else { b.textContent = "Copy"; } b.classList.remove("is-success", "is-error"); }, 1500);
    };
    return b;
  }
  // Text with links, @mentions and a safe subset of markdown: tables, lists
  // and checklists, code blocks, headings, **bold**, *italic*, `code` and
  // https images. Built from nodes, never innerHTML, so nothing in a
  // message can run as code.
  // Sources footer for web_search receipts. The bridge receipt is plain
  // text ("Web search results:\n1. title — url\n   snippet\nSources: ...");
  // parse it into links and render the stacked-favicon footer + sheet.
  // Anything unparseable returns null and renders as plain text, as before.
  // No dates: search results carry title/url/snippet only, so the sheet
  // shows host + title + snippet and invents nothing.
  function srcHost(url) { try { return new URL(url).hostname.replace(/^www\./, ""); } catch (_) { return url; } }
  function parseSources(text) {
    const at = String(text || "").indexOf("Web search results:");
    if (at < 0) return null;
    const lines = String(text).slice(at).split("\n"), out = [];
    for (let i = 1; i < lines.length && out.length < 20; i++) {
      const it = lines[i].match(/^\s*\d+[.)]\s+(.+)$/);
      if (!it) continue;
      const body = it[1], cut = body.lastIndexOf(" \u2014 ");
      if (cut <= 0) continue;
      const url = body.slice(cut + 3).trim();
      if (!/^https?:\/\/\S+$/.test(url)) continue;
      let snip = "";
      if (i + 1 < lines.length && /^\s+\S/.test(lines[i + 1]) && !/^\s*\d+[.)]\s/.test(lines[i + 1])) snip = lines[i + 1].trim();
      out.push({title: body.slice(0, cut).trim() || srcHost(url), url: url, snip: snip});
    }
    return out.length ? out : null;
  }
  function srcIcon(url) {
    const host = srcHost(url);
    let origin = "";
    try { origin = new URL(url).origin; } catch (_) {}
    if (!origin) return cel("span", "src-tile", host.charAt(0).toUpperCase());
    const img = document.createElement("img");
    img.className = "src-ic"; img.src = origin + "/favicon.ico"; img.alt = ""; img.loading = "lazy"; img.referrerPolicy = "no-referrer";
    img.onerror = () => img.replaceWith(cel("span", "src-tile", host.charAt(0).toUpperCase()));
    return img;
  }
  function sourcesFoot(text) {
    const srcs = parseSources(text);
    if (!srcs) return null;
    const b = cel("button", "src-foot"); b.type = "button";
    b.setAttribute("aria-label", "Show sources (" + srcs.length + ")");
    const stack = cel("span", "src-stack");
    srcs.slice(0, 4).forEach(s => stack.append(srcIcon(s.url)));
    if (srcs.length > 4) stack.append(cel("span", "src-more", "+" + (srcs.length - 4)));
    b.append(stack, cel("span", "src-label", "Sources"));
    b.onclick = () => openSources(srcs, b);
    return b;
  }
  let srcDlg = null;
  function openSources(srcs, opener) {
    if (srcDlg) srcDlg.remove();
    const dlg = document.createElement("dialog"); dlg.className = "sheet src-dlg";
    const x = cel("button", "src-x", "\u00d7"); x.type = "button"; x.setAttribute("aria-label", "Close sources");
    const head = cel("div", "src-head"); head.append(cel("span", "src-title", "Sources"), x);
    const scroll = cel("div", "scroll");
    for (const s of srcs) {
      const a = document.createElement("a"); a.className = "src-row"; a.href = s.url; a.target = "_blank"; a.rel = "noopener";
      const meta = cel("div", "src-meta");
      meta.append(cel("div", "src-host", srcHost(s.url)), cel("div", "src-row-title", s.title));
      if (s.snip) meta.append(cel("div", "src-snip", s.snip));
      a.append(srcIcon(s.url), meta); scroll.append(a);
    }
    dlg.append(cel("div", "grab"), head, scroll);
    x.onclick = () => dlg.close();
    dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });
    dlg.addEventListener("close", () => { dlg.remove(); if (srcDlg === dlg) srcDlg = null; if (opener) opener.focus(); });
    document.body.append(dlg); srcDlg = dlg; dlg.showModal(); x.focus();
  }
  function richText(text, m) {
    let taskN = 0;  // checklist items are numbered so ticks can be saved per message
    const root = document.createElement("div");
    root.className = "text md";
    if (!text) return root;
    const el = (tag, cls, txt) => { const x = document.createElement(tag); if (cls) x.className = cls; if (txt != null) x.textContent = txt; return x; };
    function link(url) {
      const a = el("a");
      a.href = url; a.target = "_blank"; a.rel = "noopener";
      try { const u = new URL(url); a.textContent = u.hostname.replace(/^www\./, "") + (u.pathname.length > 1 ? u.pathname.slice(0, 28) + (u.pathname.length > 28 ? "…" : "") : ""); }
      catch (_) { a.textContent = url; }
      return a;
    }
    // bold | italic (no spaces just inside the stars, so "5 * 3" stays) | code | image | link | @mention
    const INLINE = /(\*\*[^*\n]+?\*\*)|(\*(?![\s*])[^*\n]*?[^\s*]\*|\*[^\s*]\*)|(`[^`\n]+`)|(!\[[^\]\n]*\]\(https:\/\/[^\s)]+\))|(https?:\/\/[^\s<]+)|(@[A-Za-z][\w-]*)/g;
    function inline(s) {
      const frag = document.createDocumentFragment();
      let last = 0, m;
      INLINE.lastIndex = 0;
      while ((m = INLINE.exec(s))) {
        frag.append(s.slice(last, m.index));
        let end = m.index + m[0].length;
        if (m[1]) frag.append(el("strong", "", m[1].slice(2, -2)));
        else if (m[2]) frag.append(el("em", "", m[2].slice(1, -1)));
        else if (m[3]) frag.append(el("code", "", m[3].slice(1, -1)));
        else if (m[4]) {
          const im = m[4].match(/^!\[([^\]]*)\]\((.+)\)$/), img = el("img", "md-img");
          img.src = im[2]; img.alt = im[1]; img.loading = "lazy"; img.referrerPolicy = "no-referrer";
          img.onerror = () => img.remove();
          frag.append(img);
        } else if (m[5]) {
          const url = m[5].replace(/[).,!?:;'"]+$/, "");
          frag.append(link(url));
          end = m.index + url.length;
        } else frag.append(el("span", "at", m[6]));
        last = end;
        INLINE.lastIndex = end;
      }
      frag.append(s.slice(last));
      return frag;
    }
    // Copy button for code blocks: clipboard API, execCommand fallback,
    // honest success/failure states. Never touches the message text.
    // Icon form for code headers (label "Code" beside it); text form for doc cards.
    // Icons are built with createElementNS, never injected markup (model text must
    // never pass through injected markup anywhere in this script).
    // Card submission through the supported /api/allchat path. Cards
    // cannot use /api/chat/press: it only accepts server-issued
    // james/qwerty buttons. No re-render on success (it would wipe
    // the card's Sent state); the normal message poll brings the
    // sent message into the thread, which is the receipt.
    function sendCard(getText, card) {
      const st = el("div", "cfgstatus muted small"); card.append(st);
      return async () => {
        card.querySelectorAll("button,select,input,textarea").forEach(x => x.disabled = true);
        st.textContent = "Sending\u2026"; st.classList.remove("is-error", "is-success");
        try {
          const rid = Math.random().toString(36).slice(2, 12);
          const d = await (await fetch("/api/allchat", {method: "POST", headers: H, body: JSON.stringify({text: getText(), channel: C.channel, rid})})).json();
          if (!d.ok) throw new Error(d.error);
          st.textContent = "Sent"; st.classList.add("is-success");
          return true;
        } catch (err) {
          st.textContent = (err.message || "Send failed") + " \u2014 try again.";
          st.classList.add("is-error");
          card.querySelectorAll("button,select,input,textarea").forEach(x => x.disabled = false);
          return false;
        }
      };
    }
    // Quiz card: the agent asks one question when it is unsure
    // what the user means, instead of a paragraph of questions.
    // The user picks one option; Submit sends the choice as a
    // chat message through the normal /api/allchat path.
    function quizCard(body) {
      const card = el("div", "quizcard");
      const q = (body[0] || "Question").trim() || "Question";
      card.append(el("div", "doc-title", q));
      const opts = [], notes = [];
      for (const raw of body.slice(1)) {
        const mm = raw.match(/^[-*]\s+(.+)$/);
        if (mm && mm[1].trim()) opts.push(mm[1].trim());
        else if (raw.trim()) notes.push(raw.trim());
      }
      for (const n of notes) { const d = el("div"); d.append(inline(n)); card.append(d); }
      if (!opts.length) { card.append(el("div", "muted small", "Nothing to choose here.")); return card; }
      const group = "q" + Math.random().toString(36).slice(2, 10);
      const acts = el("div", "msg-acts");
      const sub = el("button", "btn", "Submit"); sub.type = "button"; sub.disabled = true;
      const picked = {value: null};
      for (const o of opts) {
        const row = el("label", "quizrow");
        const inp = el("input"); inp.type = "radio"; inp.name = group; inp.value = o;
        inp.onchange = () => { picked.value = o; sub.disabled = false; };
        row.append(inp, el("span", "", o)); card.append(row);
      }
      sub.onclick = sendCard(() => "Quiz: " + q + " \u2014 " + (picked.value || ""), card);
      acts.append(sub); card.append(acts);
      return card;
    }
    // Code block titles name the language, not the word Code.
    const LANG_NAMES = {python: "Python", py: "Python", javascript: "JavaScript", js: "JavaScript",
      typescript: "TypeScript", ts: "TypeScript", html: "HTML", css: "CSS", json: "JSON",
      bash: "Shell", sh: "Shell", shell: "Shell", zsh: "Shell", sql: "SQL", rust: "Rust",
      go: "Go", java: "Java", c: "C", "c++": "C++", cpp: "C++", ruby: "Ruby",
      markdown: "Markdown", md: "Markdown", yaml: "YAML", yml: "YAML", toml: "TOML",
      xml: "XML", svg: "SVG", text: "Text", txt: "Text", plaintext: "Text"};
    function langName(info) {
      if (!info) return "Code";
      const base = info.split(/[^a-z0-9+#]+/)[0] || "";
      const name = LANG_NAMES[base] || (base ? base.charAt(0).toUpperCase() + base.slice(1) : "Code");
      return name.slice(0, 24);
    }
    // Editable document card: Copy + Edit. Save posts the edited
    // text as a chat message; Cancel restores the original.
    function docCard(body) {
      const card = el("div", "doccard");
      const title = el("div", "doc-title", (body[0] || "Document").trim() || "Document");
      const text = body.slice(1).join("\n");
      const bd = el("div", "docbody", text);
      const acts = el("div", "msg-acts");
      const cp = copyBtn(() => bd.textContent);
      const ed = el("button", "btn small ghost", "Edit"); ed.type = "button";
      acts.append(cp, ed); card.append(title, bd, acts);
      ed.onclick = () => {
        const ta = el("textarea"); ta.className = "field"; ta.rows = Math.min(12, Math.max(3, text.split("\n").length + 1)); ta.value = text;
        const row = el("div", "msg-acts");
        const save = el("button", "btn small", "Send edited text"); save.type = "button";
        const cancel = el("button", "btn small ghost", "Cancel"); cancel.type = "button";
        row.append(save, cancel);
        bd.replaceWith(ta); acts.replaceWith(row);
        cancel.onclick = () => { ta.replaceWith(bd); row.replaceWith(acts); };
        save.onclick = async () => {
          const ok = await sendCard(() => ta.value, card)();
          if (ok) { bd.textContent = ta.value; ta.replaceWith(bd); row.replaceWith(acts); acts.querySelectorAll("button").forEach(b => b.disabled = true); }
        };
      };
      return card;
    }
    // Configuration card: strict `select:` / `check:` lines only.
    // Malformed lines render as plain text, never dropped. Submit
    // composes the choices into a chat message.
    function cfgCard(body) {
      const card = el("div", "cfgcard");
      const title = el("div", "doc-title", (body[0] || "Configuration").trim() || "Configuration");
      card.append(title);
      const fields = [];
      for (const raw of body.slice(1)) {
        const sel = raw.match(/^select\s+([^:]+):\s*(.+)$/i);
        const chk = raw.match(/^check\s+([^:]+):\s*(on|off)\s*$/i);
        if (sel) {
          const row = el("div", "cfgrow"), lab = el("label", "", sel[1].trim()), inp = el("select");
          inp.className = "field"; inp.setAttribute("aria-label", sel[1].trim());
          sel[2].split("|").map(s => s.trim()).filter(Boolean).forEach(o => inp.append(el("option", "", o)));
          row.append(lab, inp); card.append(row);
          fields.push({label: sel[1].trim(), get: () => inp.value});
        } else if (chk) {
          const row = el("div", "cfgrow"), lab = el("label", "", chk[1].trim()), inp = el("input");
          inp.type = "checkbox"; inp.checked = chk[2].toLowerCase() === "on"; inp.setAttribute("aria-label", chk[1].trim());
          row.append(lab, inp); card.append(row);
          fields.push({label: chk[1].trim(), get: () => inp.checked ? "on" : "off"});
        } else if (raw.trim()) {
          card.append(el("div", "", raw));
        }
      }
      if (!fields.length) { card.append(el("div", "muted small", "Nothing to configure here.")); return card; }
      const acts = el("div", "msg-acts"), sub = el("button", "btn", "Submit"); sub.type = "button";
      acts.append(sub); card.append(acts);
      sub.onclick = sendCard(() => "Config: " + title.textContent + " \u2014 " + fields.map(f => f.label + ": " + f.get()).join("; "), card);
      return card;
    }
    // Flow diagram: `A -> B -> C` lines become boxes + arrows.
    // Lines without arrows render as plain text, never dropped.
    function flowCard(body) {
      const box = el("div", "flow");
      for (const raw of body) {
        const nodes = raw.split("->").map(s => s.trim()).filter(Boolean);
        if (nodes.length < 2) { if (raw.trim()) box.append(el("div", "", raw)); continue; }
        nodes.forEach((n, j) => {
          if (j) box.append(el("div", "farrow", "\u2193"));
          box.append(el("div", "fnode", n));
        });
      }
      return box;
    }
    // Bar chart: `Label: number` lines become labeled bars,
    // max-normalized, negatives clamped at zero width.
    function barsCard(body) {
      const box = el("div", "");
      const rows = [];
      for (const raw of body) {
        const mm = raw.match(/^(.*?):\s*(-?[\d.,]+)\s*$/);
        if (mm) rows.push([mm[1].trim(), parseFloat(mm[2].replace(/,/g, ""))]);
        else if (raw.trim()) box.append(el("div", "", raw));
      }
      const mx = Math.max(0, ...rows.map(r => r[1]));
      for (const [lab, val] of rows) {
        const row = el("div", "bar-row");
        row.append(el("div", "bar-lab", lab));
        const track = el("div", "bar-track"), fill = el("div", "bar-fill");
        fill.style.width = (mx > 0 ? Math.max(0, val) / mx * 100 : 0) + "%";
        track.append(fill); row.append(track);
        row.append(el("div", "bar-val", String(val)));
        box.append(row);
      }
      return box;
    }
    const SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
    const cells = l => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(c => c.trim());
    const ITEM = /^\s*(?:[-*•]|\d+[.)])\s+/;
    const lines = String(text).replace(/\r\n?/g, "\n").split("\n");
    const srcs = (m && m.from !== "you" && m.from !== "hub") ? parseSources(text) : null;
    let srcSkip = -1;
    if (srcs) {
      const sl = String(text).split("\n");
      const mi = sl.findIndex(l => l.includes("Web search results:"));
      if (mi >= 0) { const si = sl.findIndex((l, j) => j > mi && /^Sources:/.test(l.trim())); if (si >= 0) srcSkip = si; }
    }
    for (let i = 0; i < lines.length;) {
      const line = lines[i];
      if (i === srcSkip) { i++; continue; }
      if (/^\s*```/.test(line)) {
        const info = line.trim().replace(/^```/, "").trim().toLowerCase();
        const body = [];
        for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) body.push(lines[i]);
        i++;
        if (info === "doc") { root.append(docCard(body)); continue; }
        if (info === "config") { root.append(cfgCard(body)); continue; }
        if (info === "flow") { root.append(flowCard(body)); continue; }
        if (info === "bars") { root.append(barsCard(body)); continue; }
        if (info === "quiz") { root.append(quizCard(body)); continue; }
        const wrap = el("div", "codeblock"), head = el("div", "chead"), pre = el("pre");
        let codeText = body.join("\n");
        const headActs = el("div", "chead-acts");
        headActs.append(copyBtn(() => codeText, true));
        const ed = el("button", "btn small ghost", "Edit"); ed.type = "button";
        headActs.append(ed);
        let preview = null, pv = null;
        if (info === "html") {
          pv = el("button", "btn small ghost", "Preview"); pv.type = "button";
          pv.onclick = () => {
            if (preview) { preview.remove(); preview = null; pv.textContent = "Preview"; return; }
            preview = document.createElement("iframe");
            preview.setAttribute("sandbox", "");
            preview.setAttribute("srcdoc", codeText);
            preview.setAttribute("title", "Preview");
            preview.style.cssText = "width:100%;height:320px;border:0;border-top:1px solid var(--border);background:#fff";
            wrap.append(preview); pv.textContent = "Code";
          };
          headActs.append(pv);
        }
        head.append(el("span", "clabel", langName(info)), headActs);
        pre.append(el("code", "", codeText));
        wrap.append(head, pre);
        ed.onclick = () => {
          if (preview) { preview.remove(); preview = null; if (pv) pv.textContent = "Preview"; }
          head.querySelectorAll("button").forEach(b => b.disabled = true);
          const ta = el("textarea"); ta.className = "field"; ta.rows = Math.min(16, Math.max(3, body.length + 1)); ta.value = codeText;
          const row = el("div", "msg-acts");
          const save = el("button", "btn small", "Save"); save.type = "button";
          const cancel = el("button", "btn small ghost", "Cancel"); cancel.type = "button";
          row.append(save, cancel);
          pre.replaceWith(ta); wrap.append(row);
          const done = () => { ta.replaceWith(pre); row.remove(); head.querySelectorAll("button").forEach(b => b.disabled = false); };
          cancel.onclick = done;
          save.onclick = async () => {
            const fenced = "```" + (info || "") + "\n" + ta.value + "\n```";
            if (await sendCard(() => fenced, wrap)()) {
              codeText = ta.value; pre.querySelector("code").textContent = codeText; done();
            }
          };
        };
        root.append(wrap); continue;
      }
      if (line.includes("|") && i + 1 < lines.length && SEP.test(lines[i + 1])) {
        const wrap = el("div", "md-scroll"), table = el("table", "md-table"), thead = el("thead"), tbody = el("tbody"), hr = el("tr");
        const aligns = cells(lines[i + 1]).map(c => /^:-+:$/.test(c) ? "center" : /^-+:$/.test(c) ? "right" : "left");
        cells(line).forEach((c, j) => { const th = el("th"); th.setAttribute("scope", "col"); th.style.textAlign = aligns[j] || "left"; th.append(inline(c)); hr.append(th); });
        thead.append(hr);
        for (i += 2; i < lines.length && lines[i].includes("|") && lines[i].trim(); i++) {
          const tr = el("tr");
          cells(lines[i]).forEach((c, j) => { const td = el("td"); td.style.textAlign = aligns[j] || "left"; td.append(inline(c)); tr.append(td); });
          tbody.append(tr);
        }
        table.append(thead, tbody); wrap.append(table); root.append(wrap); continue;
      }
      if (ITEM.test(line)) {
        const ordered = /^\s*\d+[.)]\s/.test(line), list = el(ordered ? "ol" : "ul", "md-list");
        for (; i < lines.length && (ITEM.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && list.lastChild)); i++) {
          if (ITEM.test(lines[i]) && /^\s*\d+[.)]\s/.test(lines[i]) !== ordered) break;  // bullets → numbers: a new list
          if (!ITEM.test(lines[i])) { list.lastChild.append(el("br"), inline(lines[i].trim())); continue; }
          const body = lines[i].replace(ITEM, ""), task = body.match(/^\[([ xX])\]\s+(.*)$/), li = el("li");
          if (task) {
            const cb = el("input"), label = el("span"), n = taskN++;
            cb.type = "checkbox"; cb.checked = task[1] !== " ";
            if (m && m.id && m.id !== "pending") {
              if (m.checks && n in m.checks) cb.checked = m.checks[n];
              cb.setAttribute("aria-label", task[2]);
              cb.onchange = () => fetch("/api/chat/check", {method: "POST", headers: H,
                body: JSON.stringify({msg: m.id, index: n, on: cb.checked})}).catch(() => {});
            } else cb.disabled = true;
            label.append(inline(task[2]));  // one block, so bold and code stay inline
            li.className = "task"; li.append(cb, label);
            list.classList.add("tasks");
          } else li.append(inline(body));
          list.append(li);
        }
        root.append(list); continue;
      }
      if (/^>\s?/.test(line)) {
        const q = el("blockquote", "md-quote");
        while (i < lines.length && /^>\s?/.test(lines[i])) {
          q.append(inline(lines[i].replace(/^>\s?/, ""))); q.append(el("br")); i++;
        }
        if (q.lastChild) q.lastChild.remove();
        root.append(q); continue;
      }
      const h = line.match(/^\s*#{1,4}\s+(.*)$/);
      if (h) { const d = el("div", "md-h"); d.append(inline(h[1])); root.append(d); i++; continue; }
      if (!line.trim()) { root.append(el("div", "md-gap")); i++; continue; }
      const d = el("div"); d.append(inline(line)); root.append(d); i++;
    }
    return root;
  }
  // New replies type out letter by letter, like James in Garage Gym; a tap
  // shows the rest. Reduced motion shows them at once. Screen readers get
  // the whole message.
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  function typed(m) {
    const full = richText(m.text, m);
    if (reduceMotion || m.text.length < 2) return full;
    const wrap = document.createElement("div"), shown = document.createElement("span"), caret = document.createElement("span"),
      sr = document.createElement("span");
    wrap.className = "text"; caret.className = "caret"; sr.className = "sr"; sr.textContent = m.text;
    shown.setAttribute("aria-hidden", "true"); caret.setAttribute("aria-hidden", "true");
    wrap.append(sr, shown, caret);
    const total = Math.min(m.text.length * 24, 2600), per = Math.max(1, Math.ceil(m.text.length / (total / 16)));
    let n = 0;
    const done = () => { clearInterval(t); if (wrap.isConnected) wrap.replaceWith(full); };
    const t = setInterval(() => {
      if (!wrap.isConnected) return clearInterval(t);
      const stick = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
      const from = n;
      n += per;
      if (n >= m.text.length) return done();
      shown.textContent = m.text.slice(0, n);
      if (stick) box.scrollTop = box.scrollHeight;
    }, 16);
    wrap.onclick = done;
    return wrap;
  }

  function render() {
    const near = first || box.scrollHeight - box.scrollTop - box.clientHeight < 140;
    const out = [];
    let prev = null, prevDay = "";
    for (const m of thread) {
      const d = parseAt(m.at), day = d.toDateString();
      if (day !== prevDay) {
        const sep = document.createElement("div");
        sep.className = "daysep"; sep.textContent = dayLabel(d);
        out.push(sep); prev = null; prevDay = day;
      }
      const fresh = !first && !lastIds.has(m.id);
      if (m.kind === "event") {
        const row = document.createElement("div"), t = document.createElement("span");
        row.className = "evt" + (fresh ? " new" : "");
        t.textContent = m.text;
        row.append(avatar(m.from, 16), t);
        out.push(row); prev = null;
        continue;
      }
      const cont = prev && prev.from === m.from && d - parseAt(prev.at) < 7 * 60e3;
      const row = document.createElement("div");
      row.className = "msg" + (cont ? " cont" : "") + (fresh ? " new" : "") + (m.from === "you" ? " mine" : "");
      row.dataset.id = m.id; // the Theta page's terminal finds a card's message by it
      const a = C.agents[m.from], th = C.agents.theta;
      // Every agent speaks as Theta; the trail icons below say who
      // really worked on it, since agent footers carry no name.
      const asTheta = a && th && m.from !== "you" && m.from !== "hub";
      const isAgent = m.from !== "you" && m.from !== "hub";
      const body = document.createElement("div");
      body.className = "mbody"; body.style.minWidth = "0";
      const meta = document.createElement("div"), name = document.createElement("span"), time = document.createElement("time");
      meta.className = "meta"; name.className = "name";
      name.textContent = asTheta ? th.name : (m.name || (a && a.name) || m.from);
      name.style.setProperty("--n", asTheta ? th.color : a ? a.color : "var(--text)");
      time.textContent = clock(d); time.dateTime = d.toISOString();
      // Agent answers carry no name in the footer: just the channel
      // (when cross-channel), time, and tokens, after the actions.
      // The via pill is a name too, so it stays off with the name.
      if (!isAgent) meta.append(name);
      if (asTheta && m.from !== "theta") {
        const via = document.createElement("span");
        via.className = "via"; via.textContent = a.name; via.title = "From " + a.name + (a.tier ? " (" + a.tier + ")" : "");
        via.style.setProperty("--n", a.color);
        name.setAttribute("aria-label", th.name + ", from " + a.name);
        if (!isAgent) meta.append(via);
      } else if (a && a.tier && !asTheta) { const tier = document.createElement("span"); tier.className = "tier"; tier.textContent = a.tier; meta.append(tier); }
      if (C.channel === "all" && m.ch && m.ch !== "all" && C.channelNames[m.ch]) {
        const ch = document.createElement("a");
        ch.href = "/chat?ch=" + m.ch; ch.className = "muted small"; ch.textContent = "#" + C.channelNames[m.ch];
        meta.append(ch);
      }
      meta.append(time);
      if (m.tokens) {
        const k = n => n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(n);
        const tok = document.createElement("span");
        tok.className = "tok"; tok.textContent = k(m.tokens.in) + " in · " + k(m.tokens.out) + " out";
        tok.title = "Tokens this reply used, all the agents together";
        meta.append(tok);
      }
      const agentMsg = a && m.from !== "you" && m.from !== "hub";
      body.append(fresh && agentMsg ? typed(m) : richText(m.text, m));
      if (fresh && agentMsg) { row.classList.add("dotin"); requestAnimationFrame(() => { if (window.thetaDots) thetaDots.emitTo(row, 80); }); } // its reply forms from its dots
      const imgs = [];
      if (m.attachments) for (const a of m.attachments) if (a.kind === "image") imgs.push(a);
      if (m.image && !imgs.some(a => a.url === m.image)) imgs.push({url: m.image, name: ""});
      for (const a of imgs) {
        const img = document.createElement("img");
        img.src = a.url; img.alt = (a.name || m.text.split("\n")[0]) || "Image"; img.className = "att"; img.loading = "lazy";
        if (a.url.startsWith("/upload/") || a.url.startsWith("data:")) {
          img.onload = () => { if (box.scrollHeight - box.scrollTop - box.clientHeight < img.height + 120) box.scrollTop = box.scrollHeight; };
          const lk = document.createElement("a"); lk.href = a.url; lk.target = "_blank"; lk.rel = "noopener"; lk.append(img); body.append(lk);
        } else body.append(img);
      }
      if (m.attachments) for (const a of m.attachments) if (a.kind === "file") {
        const lk = document.createElement("a"); lk.className = "fchip"; lk.href = a.url; lk.target = "_blank"; lk.rel = "noopener";
        const b = document.createElement("b"); b.textContent = a.name || "file"; lk.append(b);
        const s = document.createElement("span");
        s.textContent = (a.name || "").toLowerCase().endsWith(".pdf") ? "PDF" : "Text";
        if (a.size) s.textContent += " \u00b7 " + fmtSize(a.size);
        lk.append(s); body.append(lk);
      }
      if (m.buttons && m.buttons.length) {
        const acts = document.createElement("div");
        acts.className = "msg-acts";
        for (const bt of m.buttons) {
          const x = document.createElement("button");
          x.type = "button"; x.className = "btn small" + (bt.style === "primary" ? "" : " ghost"); x.textContent = bt.label;
          x.onclick = async () => {
            acts.querySelectorAll("button").forEach(y => y.disabled = true);
            try {
              const r = await fetch("/api/chat/press", {method: "POST", headers: H, body: JSON.stringify({msg: m.id, id: bt.id, value: bt.value, channel: C.channel})});
              const d = await r.json();
              if (!d.ok) throw new Error(d.error);
              thread = d.messages; render();
            } catch (err) { status.classList.add("is-error"); status.textContent = err.message; acts.querySelectorAll("button").forEach(y => y.disabled = false); }
          };
          acts.append(x);
        }
        body.append(acts);
      }
      if (agentMsg) {
        const foot = cel("div", "mfoot");
        const row2 = cel("div", "msg-acts macts");
        const cp = copyBtn(() => m.text, true, "mbtn", "Copy message");
        const sh = cel("button", "mbtn"); sh.type = "button";
        sh.setAttribute("aria-label", "Share message"); sh.append(iconSvg("share"));
        const flashShare = ok => {
          sh.replaceChildren(iconSvg(ok ? "check" : "share"));
          sh.setAttribute("aria-label", ok ? "Copied" : "Share failed");
          sh.classList.toggle("is-success", ok); sh.classList.toggle("is-error", !ok);
          setTimeout(() => { sh.replaceChildren(iconSvg("share")); sh.setAttribute("aria-label", "Share message"); sh.classList.remove("is-success", "is-error"); }, 1500);
        };
        sh.onclick = async () => {
          if (navigator.share) { try { await navigator.share({text: m.text}); } catch (_) {} return; }
          let ok = false;
          try { await navigator.clipboard.writeText(m.text); ok = true; }
          catch (_) {
            try {
              const ta = document.createElement("textarea");
              ta.value = m.text; ta.style.cssText = "position:fixed;opacity:0";
              document.body.append(ta); ta.select();
              ok = document.execCommand("copy"); ta.remove();
            } catch (_) { ok = false; }
          }
          flashShare(ok);
        };
        const menu = cel("div", "mmenu glass"); menu.hidden = true;
        const mi = (label, fn) => {
          const b = cel("button", "mmenu-item", label); b.type = "button";
          b.onclick = () => { menu.hidden = true; fn(); }; return b;
        };
        menu.append(
          mi("Copy text", () => cp.onclick()),
          mi("Share", () => sh.onclick()),
          mi("Download as Markdown", () => {
            const blob = new Blob([m.text], {type: "text/markdown"});
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a"); a.href = url; a.download = "message.md"; a.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
          }));
        const more = cel("button", "mbtn"); more.type = "button";
        more.setAttribute("aria-label", "More actions"); more.append(iconSvg("more"));
        more.onclick = e => {
          e.stopPropagation();
          menu.hidden = !menu.hidden;
          if (!menu.hidden) setTimeout(() => document.addEventListener("click", function close(ev) {
            if (!foot.contains(ev.target)) { menu.hidden = true; document.removeEventListener("click", close); }
          }), 0);
        };
        row2.append(cp, sh, more); foot.append(row2, menu); body.append(foot);
        const sf = sourcesFoot(m.text);
        if (sf) body.append(sf);
      }
      body.append(meta);
      if (m.trail && m.trail.length) {
        const tr = trailRow(m.trail, document.createElement("div"));
        tr.className = "trail"; tr.setAttribute("aria-label", "Worked on by " + m.trail.map(id => (C.agents[id] || {}).name || id).join(", "));
        body.append(tr);
      }
      row.append(body);
      out.push(row); prev = m;
    }
    if (!thread.length) {
      const e = document.createElement("p");
      e.className = "empty"; e.style.padding = "24px 16px";
      e.textContent = "Nothing here yet. Say hello, or @mention an agent.";
      out.push(e);
    }
    box.replaceChildren(...out);
    lastIds = new Set(thread.map(m => m.id));
    for (const m of thread) if (m.kind !== "event" && m.from !== "you") thetaSeen(m.ch || C.channel, m.id);
    thetaPaintDots();
    if (near) box.scrollTop = box.scrollHeight;
    first = false;
  }
  // The Head page (voice, panels) shares this thread: it hears about every change and can hand it new messages.
  function announce() { document.dispatchEvent(new CustomEvent("theta:thread", {detail: thread})); }
  window.thetaChat = {take(ms) { stopWorking(); thread = ms; render(); box.scrollTop = box.scrollHeight; announce(); }, load: () => load(),
    // a message sent another way (Theta's voice): it shows at once, with "Pondering..." under it, like a typed one
    pending(text, rid) {
      thread = [...thread, {id: "pending", from: "you", name: "You", text, kind: "message", ch: C.channel,
                            at: new Date().toISOString().slice(0, 19).replace("T", " ")}];
      render(); box.scrollTop = box.scrollHeight; startWorking(rid, "theta");
    },
    failed() { stopWorking(); thread = thread.filter(m => m.id !== "pending"); render(); }};
  async function load() {
    try {
      const d = await (await fetch("/api/allchat?channel=" + C.channel, {headers: H})).json();
      if (d.ok) {
        thetaLatest(d.latest);
        const ids = d.messages.map(m => m.id).join();
        if (ids !== thread.map(m => m.id).join()) { thread = d.messages; render(); announce(); }
      }
    } catch (_) {}
  }
  setInterval(() => { if (!document.hidden) load(); }, 6000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });

  // Composer: grows with its text; Enter sends on keyboards, Return is a new line on phones.
  function grow() { msg.style.height = "auto"; msg.style.height = Math.min(msg.scrollHeight, 168) + "px"; }

  // Attachments: images shrunk on the phone (longest side 1600px, JPEG) so uploads stay small;
  // PDFs and text files go through as-is. At most 4, 3 MB each and combined.
  const attach = document.getElementById("chat-attach"), file = document.getElementById("chat-file");
  let atts = [];
  function fmtSize(n) { if (n < 1024) return n + " B"; if (n < 1048576) return (n / 1024).toFixed(0) + " KB"; return (n / 1048576).toFixed(1) + " MB"; }
  function shrink(f) {
    return new Promise((ok, bad) => {
      const url = URL.createObjectURL(f), im = new Image();
      im.onload = () => {
        const k = Math.min(1, 1600 / Math.max(im.naturalWidth, im.naturalHeight));
        const c = document.createElement("canvas");
        c.width = Math.round(im.naturalWidth * k); c.height = Math.round(im.naturalHeight * k);
        const g = c.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
        g.drawImage(im, 0, 0, c.width, c.height); URL.revokeObjectURL(url);
        ok(c.toDataURL("image/jpeg", 0.82));
      };
      im.onerror = () => { URL.revokeObjectURL(url); bad(new Error("That file isn't an image this browser can open.")); };
      im.src = url;
    });
  }
  function fileKind(f) {
    const name = (f.name || "file").toLowerCase();
    if (f.type.startsWith("image/")) return "image";
    if (f.type === "application/pdf" || name.endsWith(".pdf")) return "file";
    if (f.type.startsWith("text/") || name.endsWith(".txt") || name.endsWith(".md")) return "file";
    return null;
  }
  function attErr(m) { status.textContent = m; status.classList.add("is-error"); }
  function renderAtts() {
    attach.replaceChildren();
    atts.forEach((a, i) => {
      const w = document.createElement("span");
      if (a.kind === "image") {
        w.className = "attp";
        const im = document.createElement("img"); im.src = a.data; im.alt = a.name; w.append(im);
      } else {
        w.className = "fchip";
        const b = document.createElement("b"); b.textContent = a.name; w.append(b);
        const s = document.createElement("span");
        s.textContent = (a.name.toLowerCase().endsWith(".pdf") ? "PDF" : "Text") + " \u00b7 " + fmtSize(a.size); w.append(s);
      }
      const x = document.createElement("button"); x.type = "button"; x.className = "dx"; x.setAttribute("aria-label", "Remove attachment"); x.textContent = "\u00d7";
      x.onclick = () => { atts.splice(i, 1); renderAtts(); };
      w.append(x); attach.append(w);
    });
    attach.hidden = !atts.length;
  }
  function setAtts(list) { atts = list; renderAtts(); }
  function readFile(f) {
    return new Promise((ok, bad) => {
      const r = new FileReader();
      r.onload = () => ok(r.result); r.onerror = () => bad(new Error("Couldn't read " + (f.name || "that file") + "."));
      r.readAsDataURL(f);
    });
  }
  async function takeFiles(list) {
    for (const f of list) {
      const kind = fileKind(f), name = f.name || "file";
      if (!kind) { attErr(name + " isn't a type the chat can take (images, PDF, text)."); continue; }
      if (f.size === 0) { attErr(name + " is empty."); continue; }
      if (atts.length >= 4) { attErr("At most 4 attachments on one message."); break; }
      try {
        const data = kind === "image" ? await shrink(f) : await readFile(f);
        const size = kind === "image" ? Math.round(data.length * 3 / 4) : f.size;
        if (size > 3000000) { attErr(name + " is too big (3 MB at most)."); continue; }
        if (atts.reduce((n, a) => n + a.size, 0) + size > 3000000) { attErr("Attachments together are too big (3 MB at most)."); break; }
        atts.push({kind, name, size, data});
        status.classList.remove("is-error"); status.textContent = "";
      } catch (err) { attErr(err.message); }
    }
    renderAtts(); msg.focus();
  }
  if (file) file.onchange = () => { takeFiles([...file.files]); file.value = ""; };
  msg.addEventListener("paste", e => {
    const f = [...(e.clipboardData || {}).files || []].find(x => x.type.startsWith("image/"));
    if (f) { e.preventDefault(); takeFiles([f]); }
  });
  msg.addEventListener("input", grow);
  // Typing guard: tell the hub you're typing (at most every 30 s), so a
  // scheduled round holds its update until you've stopped.
  let typedAt = 0;
  msg.addEventListener("input", () => {
    if (!msg.value.trim() || Date.now() - typedAt < 30000) return;
    typedAt = Date.now();
    fetch("/api/typing", {method: "POST", headers: H, body: "{}"}).catch(() => {});
  });
  msg.addEventListener("focus", () => { if (touch) document.body.classList.add("typing"); });
  msg.addEventListener("blur", () => setTimeout(() => document.body.classList.remove("typing"), 120));

  // "@" and "/" menus, like Discord: type to filter, arrows + Enter/Tab, Esc, or tap.
  const menu = document.getElementById("chat-menu");
  let items = [], active = 0, range = null;
  function query() {
    const before = msg.value.slice(0, msg.selectionStart);
    let m = before.match(/(^|\s)@([\w-]*)$/);
    if (m) return {kind: "@", q: m[2].toLowerCase(), start: before.length - m[2].length - 1};
    m = before.match(/^\/(\w*)$/);
    if (m) return {kind: "/", q: m[1].toLowerCase(), start: 0};
    // Instant commands: offered on an empty box and while a message starts like one.
    const lead = before.trimStart().toLowerCase();
    if (msg.value.length === before.length && lead.length <= 14 && (HUB_MENU.quick || []).some(x => quickHit(x, lead)))
      return {kind: "!", q: lead, start: 0, bare: true};
    // A bare name ("rem", "theta") offers the @mention too; only a tap or Tab takes it, so
    // "I like red" still sends as typed.
    m = before.match(/(^|\s)([A-Za-z]{3,})$/);
    if (m && HUB_MENU.agents.some(a => a.name.toLowerCase().startsWith(m[2].toLowerCase())))
      return {kind: "@", q: m[2].toLowerCase(), start: before.length - m[2].length, bare: true};
    return null;
  }
  const quickHit = (x, t) => !t || x.keys.some(k => k.startsWith(t) || t.startsWith(k));
  function closeMenu() { menu.hidden = true; items = []; range = null; msg.removeAttribute("aria-activedescendant"); }
  function renderMenu() {
    const q = query();
    if (!q) return closeMenu();
    const src = q.kind === "@" ? HUB_MENU.agents : HUB_MENU.commands;
    const key = x => x.name.toLowerCase();
    items = q.kind === "!" ? HUB_MENU.quick.filter(x => quickHit(x, q.q)).slice(0, 6) :
      q.bare ? src.filter(x => key(x).startsWith(q.q)).slice(0, 4) :
      src.filter(x => key(x).startsWith(q.q) || (q.kind === "@" && x.id.startsWith(q.q)))
      .concat(src.filter(x => !key(x).startsWith(q.q) && key(x).includes(q.q) && q.q)).slice(0, 12);
    if (!items.length) return closeMenu();
    range = q; active = Math.min(active, items.length - 1);
    menu.replaceChildren(...items.map((x, i) => {
      const li = document.createElement("li");
      li.id = "chat-menu-" + i; li.setAttribute("role", "option");
      li.setAttribute("aria-selected", String(i === active));
      const b = document.createElement("b"), small = document.createElement("span");
      small.className = "muted";
      if (q.kind === "!") {
        b.textContent = x.show; small.textContent = x.about;
        const txt = document.createElement("span"); txt.style.minWidth = "0";
        txt.append(b, document.createElement("br"), small);
        const w = document.createElement("span"); w.className = "avw"; w.append(avatar(x.agent, 26));
        li.append(w, txt);
      } else if (q.kind === "@") {
        const w = document.createElement("span"), dot = document.createElement("span");
        w.className = "avw"; dot.className = "dot" + (x.online ? " on" : "");
        w.append(avatar(x.id, 26), dot);
        b.textContent = x.name; small.textContent = x.tier;
        const txt = document.createElement("span"); txt.style.minWidth = "0";
        txt.append(b, document.createElement("br"), small);
        li.append(w, txt);
      } else {
        b.textContent = "/" + x.name;
        small.textContent = (x.args ? x.args + " · " : "") + x.about;
        const txt = document.createElement("span"); txt.style.minWidth = "0";
        txt.append(b, document.createElement("br"), small);
        li.append(txt);
      }
      li.onmousedown = ev => { ev.preventDefault(); pick(i); };
      return li;
    }));
    menu.hidden = false;
    msg.setAttribute("aria-activedescendant", "chat-menu-" + active);
  }
  function pick(i) {
    const x = items[i], q = range;
    if (!x || !q) return;
    if (q.kind === "!") {  // fill in the command's start (keeps what's typed if it's already past that)
      if (x.insert.toLowerCase().startsWith(msg.value.trimStart().toLowerCase())) msg.value = x.insert;
      msg.setSelectionRange(msg.value.length, msg.value.length); msg.focus();
      active = 0; closeMenu(); grow(); return;
    }
    const insert = (q.kind === "@" ? "@" : "/") + x.name + " ";
    const end = msg.selectionStart;
    msg.value = msg.value.slice(0, q.start) + insert + msg.value.slice(end);
    const pos = q.start + insert.length;
    msg.setSelectionRange(pos, pos); msg.focus();
    active = 0; closeMenu(); grow();
  }
  msg.addEventListener("input", () => { active = 0; renderMenu(); });
  msg.addEventListener("click", renderMenu);
  msg.addEventListener("focus", renderMenu);
  msg.addEventListener("blur", () => setTimeout(closeMenu, 150));
  msg.addEventListener("keydown", e => {
    if (!menu.hidden) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
        renderMenu();
      } else if (e.key === "Enter" && range && range.bare) {
        closeMenu();  // a suggestion, not a choice: Enter sends as typed
        if (!e.shiftKey && !touch) { e.preventDefault(); form.requestSubmit(); }
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault(); pick(active);
      } else if (e.key === "Escape") {
        e.preventDefault(); closeMenu();
      }
      return;
    }
    if (e.key === "Enter" && !e.shiftKey && !touch) { e.preventDefault(); form.requestSubmit(); }
  });

  // "Thinking..." (with the avatar of whoever it is) while a reply is on its way: the hub notes who's
  // working on this message (and on what) and the chat asks every 1.5 s.
  const VERBS = {mistral: ["thinking", "reading the chat", "working it out"], theta: ["pondering", "ruminating", "weighing it up"],
                 qwerty: ["checking", "scanning"], glass: ["counting", "tallying"], remi: ["checking the calendar"],
                 lenz: ["browsing"], charter: ["drawing"], red: ["reading the news"], blue: ["reading the news"],
                 gray: ["reading the news"], james: ["asking Garage Gym"]};
  const wBox = document.getElementById("chat-working"), wText = document.getElementById("chat-working-text");
  const wAv = document.getElementById("chat-working-av"), wDone = document.getElementById("chat-working-done");
  const wElapsed = document.getElementById("chat-working-elapsed"), wDots = wBox.querySelector(".wdots");
  const fmtElapsed = s => s < 60 ? s + "s" : Math.floor(s / 60) + "m " + (s % 60) + "s";
  let wTimer = null, wPoll = null;
  // A row of small icons, in order, for the agents that worked on something.
  function trailRow(ids, row) {
    row.replaceChildren();
    ids.forEach((id, i) => {
      if (i) { const sep = document.createElement("span"); sep.className = "sep"; sep.textContent = "›"; row.append(sep); }
      const av = avatar(id, 18); av.title = (C.agents[id] || {}).name || id; row.append(av);
    });
    return row;
  }
  function showWorking(who, name, step, done, info) {
    const state = (info && info.state) || "working";
    // A stopped agent leaves no bar behind: completed and failed both
    // hide the box instead of lingering on a finished note.
    if (state === "completed" || state === "failed") { wBox.hidden = true; wDone.replaceChildren(); clearInterval(wTimer); return; }
    wBox.hidden = false; if (window.thetaDots) thetaDots.stream(wBox); // a stream of dots from Theta while it works
    wAv.replaceChildren(avatar(who, 22));
    trailRow(done || [], wDone);
    wDots.hidden = state !== "working";
    if (info && info.elapsed != null) wElapsed.textContent = fmtElapsed(info.elapsed) + (info.stale ? " · still working" : "");
    clearInterval(wTimer);
    if (state === "waiting_approval") { wText.textContent = "Waiting for your approval."; return; }
    let n = 0;
    // just what's happening ("Pondering...", "Looking it up..."): the avatar beside it already says who
    const say = () => { const v = VERBS[who] || ["working"], w = step || v[n++ % v.length]; wText.textContent = w.charAt(0).toUpperCase() + w.slice(1) + "..."; };
    say(); if (!step) wTimer = setInterval(say, 3000);
  }
  function startWorking(rid, who) {
    let seen = "";
    showWorking(who, (C.agents[who] || {}).name || "Mistral");
    wPoll = setInterval(async () => {
      try {
        const d = await (await fetch("/api/chat/working?rid=" + rid, {headers: H})).json();
        if (!d.ok || !d.agent) return;
        const stale = d.updated && (Date.now() / 1000 - d.updated > 30);
        const info = {elapsed: d.elapsed, stale, state: d.state || "working"};
        const key = d.agent + "|" + d.step + "|" + (d.done || []).join() + "|" + info.state;
        if (key !== seen) { seen = key; showWorking(d.agent, d.name, d.step, d.done, info); }
        else if (d.elapsed != null) wElapsed.textContent = fmtElapsed(d.elapsed) + (stale ? " · still working" : "");
        if (info.state !== "working") { clearInterval(wPoll); clearInterval(wTimer); }
      } catch (_) {}
    }, 1500);
  }
  function stopWorking() { clearInterval(wTimer); clearInterval(wPoll); wBox.hidden = true; wDone.replaceChildren(); if (window.thetaDots) thetaDots.stream(null);
    try { sessionStorage.removeItem("theta-pending-rid"); } catch (_) {} }

  form.onsubmit = async e => {
    e.preventDefault();
    const text = msg.value.trim(), savedAtts = atts;
    if (!text && !savedAtts.length) return;
    if (sending) return; sending = true;  // button and keyboard both land here, so one guard covers both
    if (!(text.startsWith("/") && !savedAtts.length) && window.thetaDots) thetaDots.absorb(msg, 70); // your words fly into Theta as dots
    msg.value = ""; grow(); setAtts([]); btn.disabled = true; btn.classList.add("is-loading"); status.classList.remove("is-error"); closeMenu();
    const isCmd = text.startsWith("/") && !savedAtts.length;
    const rid = Math.random().toString(36).slice(2, 12);
    try { sessionStorage.setItem("theta-pending-rid", rid); } catch (_) {}
    status.textContent = isCmd ? "Running " + text.split(" ")[0] + "..." : "";
    if (!isCmd) startWorking(rid, /@theta\b/i.test(text) ? "theta" : (C.lead || "mistral"));
    if (!isCmd) {
      thread = [...thread, {id: "pending", from: "you", name: "You", text, attachments: savedAtts.map(a => ({url: a.data, name: a.name, kind: a.kind, size: a.size})), kind: "message", at: new Date().toISOString().slice(0, 19).replace("T", " "), ch: C.channel}];
      render(); box.scrollTop = box.scrollHeight;
    }
    try {
      const body = savedAtts.length ? {text, attachments: savedAtts.map(a => ({name: a.name, type: a.kind, data: a.data})), channel: C.channel, rid} : {text, channel: C.channel, rid};
      const d = await (await fetch("/api/allchat", {method: "POST", headers: H, body: JSON.stringify(body)})).json();
      stopWorking();
      if (!d.ok) { const e = new Error(d.error); e.serverError = true; throw e; }
      thread = d.messages; render(); box.scrollTop = box.scrollHeight; announce();
      thetaLatest(d.latest);
      if (isCmd) { status.textContent = d.result; status.classList.remove("is-error"); }
      else {
        const errs = Object.entries(d.errors || {}).map(([n, m]) => n + " couldn't reply: " + m);
        const routed = (d.routed || []).length && C.lead !== "theta" ? "Mistral passed this to " + d.routed.join(" and ") + "." : ""; // only Theta on: nothing was passed
        status.textContent = [routed, ...errs].filter(Boolean).join(" | ");
        status.classList.toggle("is-error", errs.length > 0);
      }
    } catch (err) {
      stopWorking(); status.classList.add("is-error");
      // A dropped connection doesn't mean the hub didn't get it: look before putting the text back.
      thread = thread.filter(m => m.id !== "pending"); await load();
      const arrived = !isCmd && thread.slice(-8).some(m => m.from === "you" && m.text === text.slice(0, 2000));
      if (arrived) status.textContent = err.serverError
        ? "The hub hit an error: " + err.message + ". Your message is saved. Before sending it again, check whether anything it asked for already happened, so it doesn't run twice."
        : "Your message went through, but the reply didn't arrive. It may still show up here — if it does, don't resend it. If it doesn't, check what already happened (like a task it created) before sending it again, so it doesn't run twice.";
      else { render(); msg.value = text; grow(); setAtts(savedAtts); status.textContent = "Couldn't send: " + err.message; }
    } finally { sending = false; btn.disabled = false; btn.classList.remove("is-loading"); }
  };

  // Members sheet on phones
  const mb = document.getElementById("members-btn"), members = document.getElementById("members"), scrim = document.getElementById("scrim");
  const toggle = open => { members.classList.toggle("open", open); scrim.classList.toggle("open", open); };
  if (mb) mb.onclick = () => toggle(!members.classList.contains("open"));
  if (scrim) scrim.onclick = () => toggle(false);

  if (C.to && C.agents[C.to]) { msg.value = "@" + C.agents[C.to].name + " "; grow(); }
  if (C.draft) { msg.value = C.draft; grow(); }  // draft from the mini bar (?say=): prefilled, not sent
  thread = C.initial || [];
  render(); announce();
  load();
  // A refresh mid-reply resumes the indicator from the hub note, if it
  // is still working; a finished or pruned note just clears the draft.
  try {
    const pendingRid = sessionStorage.getItem("theta-pending-rid");
    if (pendingRid) {
      fetch("/api/chat/working?rid=" + pendingRid, {headers: H}).then(r => r.json()).then(d => {
        if (d.ok && d.agent && d.state === "working") startWorking(pendingRid, d.agent);
        else sessionStorage.removeItem("theta-pending-rid");
      }).catch(() => {});
    }
  } catch (_) {}
})();
'''


_BUDGET_JS = """
document.addEventListener("click", async e => {
  const b = e.target.closest("[data-exp-rm]"); if (!b) return;
  if (!confirm("Remove this expense?")) return;
  const [month, id] = b.dataset.expRm.split(":");
  b.disabled = true;
  try {
    const d = await (await fetch("/api/glass/remove", {method: "POST", headers: window.THETA_H, body: JSON.stringify({month, id})})).json();
    if (!d.ok) throw new Error(d.error);
    location.reload();
  } catch (err) { b.disabled = false; b.textContent = "Couldn't remove"; }
});
document.getElementById("csv-import").onclick = async () => {
  const f = document.getElementById("csv-file").files[0], out = document.getElementById("csv-status");
  if (!f) { out.textContent = "Pick your Rocket Money CSV first."; return; }
  out.textContent = "Importing...";
  try {
    const d = await (await fetch("/api/glass/import", {method: "POST",
      headers: {"Content-Type": "application/json", "x-dashboard-key": new URLSearchParams(location.search).get("key") || ""},
      body: JSON.stringify({csv: await f.text()})})).json();
    if (!d.ok) throw new Error(d.error);
    const sk = Object.entries(d.skipped).filter(([, n]) => n).map(([k, n]) => n + " " + k).join(", ");
    out.textContent = "Added " + d.added + " expenses" + (d.duplicates ? ", " + d.duplicates + " already imported" : "")
      + (sk ? "; skipped " + sk : "") + ". Read columns " + Object.values(d.columns).join(", ")
      + "; expenses were " + d.expenses_were + " in this file. Reload to see the totals.";
  } catch (err) { out.textContent = "Import failed: " + err.message; }
};
"""


UI_ICONS = {
    "home": '<path d="M3.5 10.5L12 3.5l8.5 7"/><path d="M5.5 9v11h13V9"/><path d="M10 20v-5.5h4V20"/>',
    "chat": '<path d="M20.5 11.5a8 8 0 0 1-11.7 7.1L4 19.8l1.2-4.4A8 8 0 1 1 20.5 11.5z"/><path d="M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15.5" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    "money": '<rect x="3" y="6" width="18" height="13.5" rx="3"/><path d="M3 10.5h18M15.5 15h2.5"/>',
    "settings": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    "play": '<path d="M7 5l12 7-12 7z"/>',
    "bell": '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
    "check": '<rect x="4" y="4" width="16" height="16" rx="4"/><path d="M8.5 12.5l2.5 2.5 4.5-5"/>',
    "send": '<path d="M5 12l15-7-5 15-2.5-6.5z"/><path d="M12.5 13.5L20 5"/>',
    "photo": '<rect x="3.5" y="5" width="17" height="14" rx="3"/><circle cx="9" cy="10" r="1.6"/><path d="M4 17l5-4.5 3.5 3 3-2.5L20 17"/>',
    "users": '<circle cx="9" cy="8.5" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 5.2a3.5 3.5 0 0 1 0 6.6M18.5 20a6.5 6.5 0 0 0-2.7-5.3"/>',
    "bolt": '<path d="M13 3L5 13.5h6L10 21l8-10.5h-6z"/>',
    "rings": '<circle cx="12" cy="12" r="2.4"/><path d="M12 4.5a7.5 7.5 0 0 1 7.5 7.5M12 19.5A7.5 7.5 0 0 1 4.5 12"/><path d="M12 7.5a4.5 4.5 0 0 1 4.5 4.5M12 16.5A4.5 4.5 0 0 1 7.5 12"/>',
    "news": '<path d="M5 4.5h11v15H6.5A1.5 1.5 0 0 1 5 18z"/><path d="M16 8.5h3v9.5a1.5 1.5 0 0 1-3 0M8 8.5h5M8 12h5M8 15.5h3"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
}
# Primary destinations in the bottom bar. Chat, Calendar and Money keep
# their routes and are reached from the sidebar Sections list, the Home
# quick actions and the persistent chat bar; nothing was removed.
NAV = [("/", "Home", "home"), ("/head", "Theta", "rings"), ("/diagnostics", "Diagnostics", "bolt"), ("/settings", "Settings", "settings")]
NAV_MORE = [("/chat", "Chat", "chat"), ("/calendar", "Calendar", "calendar"), ("/money", "Money", "money")]


def ui_icon(name):
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{UI_ICONS[name]}</svg>')


_BAR_CSS = '\n/* ---- The bottom bar in each frame (2026-11-04): the suggestion chips, the message box, the send button and the\n   tab bar take the frame\'s shape. Glass+ and Liquid Glass keep the round pills they were drawn for. */\n:root[data-glassstyle="edge"] .minibar{border-top:1px solid color-mix(in srgb,var(--accent) 55%,transparent)}\n:root[data-glassstyle="edge"] .minichips a{border-radius:0;clip-path:polygon(0 0,calc(100% - 7px) 0,100% 7px,100% 100%,7px 100%,0 calc(100% - 7px));border-color:color-mix(in srgb,var(--accent) 40%,transparent);font-family:var(--f-label);text-transform:uppercase;letter-spacing:.06em;font-size:11px}\n:root[data-glassstyle="edge"] .minibox,:root[data-glassstyle="edge"] .box{border-radius:0;clip-path:polygon(0 0,calc(100% - 11px) 0,100% 11px,100% 100%,11px 100%,0 calc(100% - 11px));border-color:color-mix(in srgb,var(--accent) 45%,transparent);box-shadow:inset 3px 0 0 var(--accent)}\n:root[data-glassstyle="edge"] .minibox .btn.send,:root[data-glassstyle="edge"] .box .btn{border-radius:0;clip-path:polygon(0 0,calc(100% - 7px) 0,100% 7px,100% 100%,7px 100%,0 calc(100% - 7px))}\n:root[data-glassstyle="edge"] .tabbar a.on{box-shadow:inset 0 2px 0 var(--accent);border-radius:0}\n:root[data-glassstyle="breach"] .minibar{border-top:1px solid var(--accent)}\n:root[data-glassstyle="breach"] .minichips a{border-radius:0;background:transparent;border-color:color-mix(in srgb,var(--accent) 55%,transparent);font-family:var(--f-mono);font-size:12px}\n:root[data-glassstyle="breach"] .minichips a::before{content:"> ";color:var(--accent)}\n:root[data-glassstyle="breach"] .minibox,:root[data-glassstyle="breach"] .box{border-radius:0;border-color:color-mix(in srgb,var(--accent) 60%,transparent);background:color-mix(in srgb,var(--surface) 70%,transparent);box-shadow:inset 0 3px 0 var(--accent)}\n:root[data-glassstyle="breach"] .minibox input,:root[data-glassstyle="breach"] .box textarea{font-family:var(--f-mono)}\n:root[data-glassstyle="breach"] .minibox .btn.send,:root[data-glassstyle="breach"] .box .btn{border-radius:0}\n:root[data-glassstyle="breach"] .tabbar a.on{background:var(--accent);color:var(--on);border-radius:0}\n:root[data-glassstyle="hud"] .minichips a{border-radius:3px;background:linear-gradient(var(--accent),var(--accent)) left top/7px 1.5px no-repeat,linear-gradient(var(--accent),var(--accent)) left top/1.5px 7px no-repeat,linear-gradient(var(--accent),var(--accent)) right top/7px 1.5px no-repeat,linear-gradient(var(--accent),var(--accent)) right top/1.5px 7px no-repeat,linear-gradient(var(--accent),var(--accent)) left bottom/7px 1.5px no-repeat,linear-gradient(var(--accent),var(--accent)) left bottom/1.5px 7px no-repeat,linear-gradient(var(--accent),var(--accent)) right bottom/7px 1.5px no-repeat,linear-gradient(var(--accent),var(--accent)) right bottom/1.5px 7px no-repeat,var(--surface2);border-color:color-mix(in srgb,var(--text) 10%,transparent);text-transform:uppercase;letter-spacing:.06em;font-size:12px}\n:root[data-glassstyle="hud"] .minibox,:root[data-glassstyle="hud"] .box{border-radius:4px;background:linear-gradient(var(--accent),var(--accent)) left top/12px 2px no-repeat,linear-gradient(var(--accent),var(--accent)) left top/2px 12px no-repeat,linear-gradient(var(--accent),var(--accent)) right top/12px 2px no-repeat,linear-gradient(var(--accent),var(--accent)) right top/2px 12px no-repeat,linear-gradient(var(--accent),var(--accent)) left bottom/12px 2px no-repeat,linear-gradient(var(--accent),var(--accent)) left bottom/2px 12px no-repeat,linear-gradient(var(--accent),var(--accent)) right bottom/12px 2px no-repeat,linear-gradient(var(--accent),var(--accent)) right bottom/2px 12px no-repeat,var(--surface2);border-color:color-mix(in srgb,var(--text) 10%,transparent)}\n:root[data-glassstyle="hud"] .minibox .btn.send,:root[data-glassstyle="hud"] .box .btn{border-radius:3px}\n:root[data-glassstyle="hud"] .tabbar a.on{box-shadow:inset 0 2px 0 var(--accent);border-radius:0}\n:root[data-glassstyle="console"] .minibar{border-top:1px solid var(--border);box-shadow:none}\n:root[data-glassstyle="console"] .minichips a{border-radius:2px;background:transparent;font-family:var(--f-mono);font-size:12px;color:var(--muted)}\n:root[data-glassstyle="console"] .minibox,:root[data-glassstyle="console"] .box{border-radius:2px}\n:root[data-glassstyle="console"] .minibox::before{content:"\\203A";font-family:var(--f-mono);color:var(--accent);margin-left:-6px}\n:root[data-glassstyle="console"] .minibox input,:root[data-glassstyle="console"] .box textarea{font-family:var(--f-mono);font-size:15px}\n:root[data-glassstyle="console"] .minibox .btn.send,:root[data-glassstyle="console"] .box .btn{border-radius:2px}\n:root[data-glassstyle="console"] .tabbar a{font-family:var(--f-mono);text-transform:uppercase;letter-spacing:.06em;font-size:10px}\n:root[data-glassstyle="console"] .tabbar a.on{box-shadow:inset 0 -2px 0 var(--accent);border-radius:0}\n:root[data-glassstyle="holo"] .minibar{background:color-mix(in srgb,var(--bg) 70%,transparent);border-top:1px solid color-mix(in srgb,var(--text) 22%,transparent)}\n:root[data-glassstyle="holo"] .minichips a{border-radius:4px;background:color-mix(in srgb,var(--text) 6%,transparent);border-color:color-mix(in srgb,var(--text) 30%,transparent);text-transform:uppercase;letter-spacing:.08em;font-size:11px;box-shadow:0 0 10px color-mix(in srgb,var(--text) 10%,transparent)}\n:root[data-glassstyle="holo"] .minibox,:root[data-glassstyle="holo"] .box{border-radius:10px;background:linear-gradient(90deg,transparent,color-mix(in srgb,var(--text) 70%,transparent) 50%,transparent) top/100% 1px no-repeat,color-mix(in srgb,var(--text) 6%,transparent);border-color:color-mix(in srgb,var(--text) 28%,transparent);box-shadow:0 0 16px color-mix(in srgb,var(--text) 10%,transparent)}\n:root[data-glassstyle="holo"] .minibox .btn.send,:root[data-glassstyle="holo"] .box .btn{border-radius:4px}\n:root[data-glassstyle="holo"] .tabbar a.on{text-shadow:0 0 12px color-mix(in srgb,var(--accent) 70%,transparent)}\n:root[data-glassstyle="ornate"] .minichips a{border-radius:0;background:transparent;border:0;border-bottom:1px solid color-mix(in srgb,var(--accent) 45%,transparent);text-transform:uppercase;letter-spacing:.1em;font-size:11px;font-family:var(--f-label)}\n:root[data-glassstyle="ornate"] .minibox .btn.send,:root[data-glassstyle="ornate"] .box .btn{border-radius:0;background:transparent;color:var(--accent);border:1px solid color-mix(in srgb,var(--accent) 60%,transparent)}\n:root[data-glassstyle="ornate"] .tabbar a.on{box-shadow:inset 0 -1px 0 var(--accent);border-radius:0}\n'
_MOVE_CSS = r'''
/* ---- Moving between pages (2026-11-04). Where the browser can (Safari 18.2+, Chrome 126+), each page change is a
   view transition: the old page fades back, the new one rises in, the tab bar stays put, and Theta morphs
   between the middle of the Theta page and the corner of the others. Elsewhere pages still ease in. */
@view-transition{navigation:auto}
.tabbar{view-transition-name:tabbar}
.theta-mini{view-transition-name:theta}
::view-transition-old(root){animation:vt-out .18s ease-in both}
::view-transition-new(root){animation:vt-in .32s cubic-bezier(.2,.8,.2,1) both}
::view-transition-group(theta){animation-duration:.5s;animation-timing-function:cubic-bezier(.22,.9,.24,1)}
@keyframes vt-out{to{opacity:0;transform:scale(.985)}}
@keyframes vt-in{from{opacity:0;transform:translateY(14px)}}
/* the page's cards come in one after another */
.main > .top,.main > .stack > *,.main > .grid2 > *,.main > .wins > *,.main > section{animation:var(--in,pagein) var(--in-dur,.42s) var(--in-ease,cubic-bezier(.2,.8,.2,1)) backwards}
.main > .stack > :nth-child(2),.main > .grid2 > :nth-child(2),.main > .wins > :nth-child(2){animation-delay:.05s}
.main > .stack > :nth-child(3),.main > .grid2 > :nth-child(3),.main > .wins > :nth-child(3){animation-delay:.1s}
.main > .stack > :nth-child(4),.main > .wins > :nth-child(4){animation-delay:.15s}
.main > .stack > :nth-child(5),.main > .wins > :nth-child(5){animation-delay:.2s}
.main > .stack > :nth-child(n+6),.main > .wins > :nth-child(n+6){animation-delay:.24s}
@keyframes pagein{from{opacity:0;transform:translateY(12px)}}
/* Each frame arrives its own way (2026-11-04): the cards above, and the whole page in a view transition.
   Fill is "backwards" only, so nothing an animation sets (a clip, a transform) outlasts it. */
:root[data-glassstyle="plus"]{--in:in-bubble;--in-dur:.55s;--in-ease:cubic-bezier(.34,1.56,.64,1)}
@keyframes in-bubble{0%{opacity:0;transform:scale(.86);filter:blur(6px)}55%{opacity:1;filter:blur(0)}}
:root[data-glassstyle="liquid"]{--in:in-liquid;--in-dur:.7s;--in-ease:ease-out}
@keyframes in-liquid{0%{opacity:0;transform:scale(.72,.6);filter:blur(10px)}40%{opacity:1;transform:scale(1.05,.95);filter:blur(1px)}
 60%{transform:scale(.97,1.03)}80%{transform:scale(1.01,.99)}100%{transform:none;filter:none}}
:root[data-glassstyle="edge"]{--in:in-glitch;--in-dur:.5s;--in-ease:linear}
@keyframes in-glitch{0%{opacity:0;transform:translateX(-14px) skewX(-10deg);filter:hue-rotate(90deg) saturate(3)}
 15%{opacity:1;transform:translateX(6px) skewX(6deg)}25%{opacity:.25;transform:translateX(-3px)}35%{opacity:1;transform:translateX(2px);filter:hue-rotate(-40deg)}
 50%{opacity:.6;transform:none}62%{opacity:1;filter:none}75%{opacity:.85}100%{opacity:1;transform:none}}
:root[data-glassstyle="breach"]{--in:in-print;--in-dur:.5s;--in-ease:steps(7,end)}
@keyframes in-print{0%{clip-path:inset(0 0 100% 0)}100%{clip-path:inset(0 0 0 0)}}
:root[data-glassstyle="hud"]{--in:in-lock;--in-dur:.55s;--in-ease:ease-out}
@keyframes in-lock{0%{opacity:0;transform:scale(1.09);outline:2px solid var(--accent);outline-offset:10px}
 35%{opacity:1;transform:scale(.985);outline:2px solid var(--accent);outline-offset:2px}48%{opacity:.45}58%{opacity:1}
 100%{transform:none;outline:2px solid transparent;outline-offset:0}}
:root[data-glassstyle="console"]{--in:in-type;--in-dur:.45s;--in-ease:steps(14,end)}
@keyframes in-type{0%{clip-path:inset(0 100% 0 0)}100%{clip-path:inset(0 0 0 0)}}
:root[data-glassstyle="holo"]{--in:in-project;--in-dur:.65s;--in-ease:cubic-bezier(.2,.8,.2,1)}
@keyframes in-project{0%{opacity:0;transform-origin:50% 100%;transform:perspective(700px) rotateX(78deg) scaleY(.25);filter:brightness(3)}
 50%{opacity:.85;filter:brightness(1.8)}62%{opacity:.35}74%{opacity:.95}100%{opacity:1;transform-origin:50% 100%;filter:none}}
:root[data-glassstyle="ornate"]{--in:in-unveil;--in-dur:.6s;--in-ease:cubic-bezier(.2,.8,.2,1)}
@keyframes in-unveil{0%{opacity:0;clip-path:inset(0 50% 0 50%)}60%{opacity:1}100%{clip-path:inset(0 0 0 0)}}
/* the whole page, per frame */
:root[data-glassstyle="plus"]::view-transition-new(root),:root[data-glassstyle="liquid"]::view-transition-new(root){animation:vt-bubble .42s cubic-bezier(.34,1.4,.64,1) both}
:root[data-glassstyle="plus"]::view-transition-old(root),:root[data-glassstyle="liquid"]::view-transition-old(root){animation:vt-melt .22s ease-in both}
@keyframes vt-bubble{from{opacity:0;transform:scale(.94);filter:blur(8px)}}
@keyframes vt-melt{to{opacity:0;transform:scale(1.03);filter:blur(8px)}}
:root[data-glassstyle="edge"]::view-transition-old(root),:root[data-glassstyle="breach"]::view-transition-old(root){animation:vt-glitch-out .22s steps(4,end) both}
:root[data-glassstyle="edge"]::view-transition-new(root),:root[data-glassstyle="breach"]::view-transition-new(root){animation:vt-glitch-in .3s steps(5,end) both}
@keyframes vt-glitch-out{30%{transform:translateX(8px);opacity:.7}60%{transform:translateX(-6px);opacity:.4}to{opacity:0;transform:none}}
@keyframes vt-glitch-in{from{opacity:0;transform:translateX(-10px)}40%{opacity:.6;transform:translateX(6px)}70%{opacity:.9;transform:translateX(-2px)}}
:root[data-glassstyle="holo"]::view-transition-old(root){animation:vt-holo-off .26s ease-in both}
:root[data-glassstyle="ornate"]::view-transition-new(root){animation:vt-unveil .45s cubic-bezier(.2,.8,.2,1) both}
@keyframes vt-unveil{from{opacity:0;clip-path:inset(0 30% 0 30%)}}
:root[data-glassstyle="holo"]::view-transition-new(root){animation:vt-holo-on .4s cubic-bezier(.2,.8,.2,1) both}
@keyframes vt-holo-off{60%{transform:scaleY(.04);opacity:.9;filter:brightness(3)}to{transform:scaleY(.01) scaleX(.6);opacity:0}}
@keyframes vt-holo-on{from{transform:scaleY(.02);opacity:0;filter:brightness(3)}50%{transform:scaleY(1.02);opacity:.9}}
/* while the next page loads, Theta in the corner thinks */
.nav-wait .theta-mini{animation:minithink .9s ease-in-out infinite}
@keyframes minithink{50%{transform:scale(.86);filter:brightness(1.5)}}
@media (prefers-reduced-motion:reduce){@view-transition{navigation:none}
 .main > *,.main > .stack > *,.main > .grid2 > *,.main > .wins > *{animation:none!important}.nav-wait .theta-mini{animation:none}}
'''
# ---- Charm (2026-11-06): what's delightful about a theme or a frame is how it behaves. A theme celebrates
# when you finish something, in its own manner (CHEERS: Sakura drops petals, Ember throws sparks, Ocean
# ripples, Paper stamps a check...); a frame answers your touch in its own manner (Glass+ squishes, Liquid
# Glass pools light, Edge sweeps a lit edge, HUD snaps target brackets on...). Both stay out of the layout
# and off with reduced motion.
CHEERS = {"theta": ("orbit", ""), "midnight": ("star", ""), "nebula": ("star", ""), "aurora": ("wash", ""), "graphite": ("check", ""),
          "lobby": ("check", ""), "forest": ("leaf", ""), "ember": ("spark", ""), "ocean": ("ripple", ""), "paper": ("stamp", "\u2713 DONE"),
          "sakura": ("petal", ""), "terminal": ("print", "> done \u2713"), "redline": ("spark", ""), "datalog": ("ripple", ""),
          "breach": ("print", "[ ACCESS OK ]"), "scanner": ("stamp", "CLEARED"), "amber": ("spark", ""), "mission": ("check", ""),
          "hologram": ("check", ""), "gilded": ("glint", ""), "lattice": ("ripple", ""), "bloom": ("petal", ""), "neonrift": ("neon", ""),
          "verdant": ("leaf", ""), "lunar": ("glint", ""), "bloodsign": ("spark", ""), "nightfiligree": ("glint", ""), "dusk": ("star", "")}
_CHARM_CSS = r'''.card,.win,.kpi,.w{background-image:var(--lit,none)}
/* dot moments: the overlay that carries Theta's dots between things (window.thetaDots) */
.dotfx{position:fixed;inset:0;width:100vw;height:100vh;pointer-events:none;z-index:40;mix-blend-mode:screen}
:root[data-mode="light"] .dotfx{mix-blend-mode:multiply}
/* its reply sharpens in as its dots land */
.msg.dotin .mbody{animation:dotsharpen .8s ease-out .15s backwards}
@keyframes dotsharpen{from{opacity:0;filter:blur(6px)}}
/* while it works: a small stream of dots instead of words (the words stay for screen readers) */
.working .wdots.stream{position:relative;display:inline-block;width:96px;height:8px;flex:none}
.working .wdots.stream i{position:absolute;left:0;top:1px;width:5px;height:5px;border-radius:50%;background:currentColor;animation:wstream 1.7s linear infinite;opacity:0}
.working .wdots.stream i:nth-child(2){animation-delay:.24s}.working .wdots.stream i:nth-child(3){animation-delay:.48s}.working .wdots.stream i:nth-child(4){animation-delay:.72s}
.working .wdots.stream i:nth-child(5){animation-delay:.96s}.working .wdots.stream i:nth-child(6){animation-delay:1.2s}.working .wdots.stream i:nth-child(7){animation-delay:1.44s}
@keyframes wstream{0%{transform:translateX(0) scale(.4);opacity:0}15%{opacity:1}100%{transform:translateX(90px) scale(1);opacity:0}}
.working .wdots.stream:not([hidden]) ~ #chat-working-text{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
/* progress as dots: the day ring's arcs */
.dayring .dr-left,.dayring .dr-done{stroke-linecap:round;stroke-dasharray:0 9}
.dayring .dr-track{stroke-linecap:round;stroke-dasharray:0 9;stroke-width:4!important}
@media (prefers-reduced-motion:reduce){.msg.dotin .mbody{animation:none}.working .wdots.stream i{animation:none;opacity:.6}}
/* ---- The Theta frames: the cards are Theta's dots (drawn on .dotframe), so their own fill steps back */
.dotframe{position:fixed;inset:0;width:100vw;height:100vh;pointer-events:none;z-index:8;mix-blend-mode:screen}
:root[data-mode="light"] .dotframe{mix-blend-mode:multiply}
@media (prefers-color-scheme:light){:root:not([data-mode="dark"]) .dotframe{mix-blend-mode:multiply}}
:root[data-glassstyle="lines"] :is(.card,.win,.kpi,.w,.holo),:root[data-glassstyle="nebula"] :is(.card,.win,.kpi,.w,.holo){background:transparent!important;border-color:transparent!important;box-shadow:none!important;-webkit-backdrop-filter:none;backdrop-filter:none}
:root[data-glassstyle="settle"] :is(.card,.win,.kpi,.w,.holo){background:color-mix(in srgb,var(--surface) 22%,transparent)!important;border-color:transparent!important;box-shadow:none!important}
:root[data-glassstyle="grain"] :is(.card,.win,.kpi,.w,.holo),:root[data-glassstyle="press"] :is(.card,.win,.kpi,.w,.holo){background:color-mix(in srgb,var(--surface) 38%,transparent)!important;border-color:color-mix(in srgb,var(--accent) 14%,transparent)!important;box-shadow:none!important}
@media (prefers-reduced-motion:reduce){:root:is([data-glassstyle="lines"],[data-glassstyle="nebula"],[data-glassstyle="settle"]) :is(.card,.win,.kpi,.w,.holo){background:var(--surface)!important;border-color:var(--border)!important}}

/* ---- Each frame's charm (2026-11-06): how it answers a touch. The pressed thing gets .tap for a moment and a
   .tapfx layer (inset, its own corners, never in the layout); --tx/--ty is where the finger landed. */
.tapfx{position:absolute;inset:0;border-radius:inherit;pointer-events:none;overflow:hidden;opacity:0;z-index:0}
.tap > .tapfx{animation:tapfx-fade .6s ease-out}
@keyframes tapfx-fade{0%{opacity:1}100%{opacity:0}}
.cheer{position:fixed;inset:0;width:100vw;height:100vh;pointer-events:none;z-index:9990}
/* Glass+: a soft squish, a little bloom under the finger */
:root[data-glassstyle="plus"] .tap{animation:tap-squish .42s cubic-bezier(.34,1.56,.64,1)}
:root[data-glassstyle="plus"] .tapfx{background:radial-gradient(circle at var(--tx) var(--ty),color-mix(in srgb,white 35%,transparent),transparent 60%)}
@keyframes tap-squish{0%{transform:scale(1)}30%{transform:scale(.955)}100%{transform:scale(1)}}
/* Liquid Glass: light pools where you press and spreads to the edges */
:root[data-glassstyle="liquid"] .tap{animation:tap-squish .5s cubic-bezier(.34,1.56,.64,1)}
:root[data-glassstyle="liquid"] .tap > .tapfx{animation:tap-pool .65s ease-out}
:root[data-glassstyle="liquid"] .tapfx{background:radial-gradient(circle at var(--tx) var(--ty),color-mix(in srgb,white 55%,transparent),color-mix(in srgb,var(--accent) 18%,transparent) 30%,transparent 62%)}
@keyframes tap-pool{0%{opacity:1;clip-path:circle(0 at var(--tx) var(--ty))}60%{opacity:.8}100%{opacity:0;clip-path:circle(150% at var(--tx) var(--ty))}}
/* Edge: a lit edge sweeps across */
:root[data-glassstyle="edge"] .tapfx{background:linear-gradient(100deg,transparent 30%,color-mix(in srgb,var(--accent) 45%,transparent) 48%,color-mix(in srgb,white 50%,transparent) 50%,transparent 66%) 200% 0/250% 100% no-repeat}
:root[data-glassstyle="edge"] .tap > .tapfx{animation:tap-sweep .45s cubic-bezier(.4,0,.2,1)}
@keyframes tap-sweep{0%{opacity:1;background-position:200% 0}100%{opacity:1;background-position:-100% 0}}
/* Breach: the box inverts for a blink, like a terminal accepting a key */
:root[data-glassstyle="breach"] .tapfx{background:var(--accent);mix-blend-mode:difference}
:root[data-glassstyle="breach"] .tap > .tapfx{animation:tap-blink .32s steps(2,jump-none)}
@keyframes tap-blink{0%{opacity:1}100%{opacity:0}}
/* HUD: target brackets snap onto what you touched */
:root[data-glassstyle="hud"] .tapfx{overflow:visible;background:linear-gradient(var(--accent),var(--accent)) left top/10px 2px no-repeat,linear-gradient(var(--accent),var(--accent)) left top/2px 10px no-repeat,
 linear-gradient(var(--accent),var(--accent)) right top/10px 2px no-repeat,linear-gradient(var(--accent),var(--accent)) right top/2px 10px no-repeat,
 linear-gradient(var(--accent),var(--accent)) left bottom/10px 2px no-repeat,linear-gradient(var(--accent),var(--accent)) left bottom/2px 10px no-repeat,
 linear-gradient(var(--accent),var(--accent)) right bottom/10px 2px no-repeat,linear-gradient(var(--accent),var(--accent)) right bottom/2px 10px no-repeat}
:root[data-glassstyle="hud"] .tap > .tapfx{animation:tap-lock .5s cubic-bezier(.2,.8,.2,1)}
@keyframes tap-lock{0%{opacity:0;transform:scale(1.18)}35%{opacity:1;transform:scale(1)}70%{opacity:1}100%{opacity:0;transform:scale(1)}}
/* Console: the line highlights like a selected row, with a cursor at the end */
:root[data-glassstyle="console"] .tapfx{background:color-mix(in srgb,var(--accent) 16%,transparent);box-shadow:inset 3px 0 0 var(--accent)}
:root[data-glassstyle="console"] .tapfx::after{content:"\258C";position:absolute;right:8px;top:50%;transform:translateY(-50%);color:var(--accent);font:600 13px var(--f-mono)}
:root[data-glassstyle="console"] .tap > .tapfx{animation:tap-row .6s steps(1,end)}
@keyframes tap-row{0%,100%{opacity:0}1%,30%{opacity:1}31%,45%{opacity:.35}46%,80%{opacity:1}}
/* Hologram: it flickers as if the projection caught your finger, and a scan line runs through */
:root[data-glassstyle="holo"] .tap{animation:tap-flicker .4s linear}
:root[data-glassstyle="holo"] .tapfx{background:linear-gradient(180deg,transparent 45%,color-mix(in srgb,var(--text) 40%,transparent) 50%,transparent 55%) 0 -100%/100% 200% no-repeat}
:root[data-glassstyle="holo"] .tap > .tapfx{animation:tap-scan .45s linear}
@keyframes tap-flicker{0%,100%{opacity:1}20%{opacity:.55}30%{opacity:1}55%{opacity:.75}65%{opacity:1}}
@keyframes tap-scan{0%{opacity:1;background-position:0 -100%}100%{opacity:1;background-position:0 100%}}
/* Filigree: an engraved line draws itself under what you chose */
:root[data-glassstyle="ornate"] .tapfx{overflow:visible;background:linear-gradient(90deg,transparent,var(--accent) 20%,var(--accent) 80%,transparent) 50% 100%/0 1px no-repeat}
:root[data-glassstyle="ornate"] .tap > .tapfx{animation:tap-engrave .7s cubic-bezier(.2,.8,.2,1)}
@keyframes tap-engrave{0%{opacity:1;background-size:0 1px}55%{opacity:1;background-size:100% 1px}100%{opacity:0;background-size:100% 1px}}
@media (prefers-reduced-motion:reduce){.tap,.tap > .tapfx{animation:none!important}}
'''
_DOTMOMENTS_JS = r'''(() => {
  // ---- Dot moments (2026-11-06): Theta's dots carry what happens. Your message breaks into dots that fly into
  // Theta; its reply and its cards form from dots it sends out; a tapped option goes back to it as a burst; while it
  // works, a stream of dots runs from it to the chat; a widget you swipe away crumbles into dots that drift home.
  // One overlay that only adds light, in every frame; nothing with reduced motion.
  const root = document.documentElement, TAU = Math.PI * 2;
  let cv = null, g = null, W = 0, H = 0, P = [], running = false, last = 0, streamTo = null, hue = 195, hueAt = 0, clock = 0;
  const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  function theta() { const e = document.getElementById("head-av") || document.querySelector(".theta-mini");
    if (e) { const r = e.getBoundingClientRect(); if (r.width) return {x: r.left + r.width / 2, y: r.top + r.height / 2}; } return {x: innerWidth - 30, y: 34}; }
  function readHue() { const c = getComputedStyle(root).getPropertyValue("--mood").trim() || getComputedStyle(root).getPropertyValue("--accent2").trim(), m = c.match(/^#([0-9a-f]{6})$/i);
    if (!m) return hue; const n = parseInt(m[1], 16), r = (n >> 16 & 255) / 255, gg = (n >> 8 & 255) / 255, b = (n & 255) / 255, mx = Math.max(r, gg, b), mn = Math.min(r, gg, b), d = mx - mn;
    if (!d) return hue; const h = mx === r ? ((gg - b) / d) % 6 : mx === gg ? (b - r) / d + 2 : (r - gg) / d + 4; return (h * 60 + 360) % 360; }
  function size() { const dpr = Math.min(2, devicePixelRatio || 1); W = innerWidth; H = innerHeight; cv.width = W * dpr; cv.height = H * dpr; g.setTransform(dpr, 0, 0, dpr, 0, 0); }
  function ensure() {
    if (still() || !document.body) return false;
    if (!cv) { cv = document.createElement("canvas"); cv.className = "dotfx"; cv.setAttribute("aria-hidden", "true"); document.body.append(cv); g = cv.getContext("2d"); size(); addEventListener("resize", size); }
    if (!running) { running = true; last = performance.now(); requestAnimationFrame(frame); }
    return true;
  }
  const rectOf = el => { const r = el && el.getBoundingClientRect ? el.getBoundingClientRect() : null; return r && r.width ? r : null; };
  // from an area to Theta (your message, a tapped option, a dismissed widget)
  function absorb(el, n, opts) {
    const r = rectOf(el); if (!r || !ensure()) return; const t = theta(), o = opts || {};
    for (let i = 0; i < (n || 60); i++) { const x = r.left + Math.random() * r.width, y = r.top + Math.random() * r.height;
      P.push({x, y, vx: (Math.random() - .5) * (o.burst || 2), vy: (Math.random() - .5) * (o.burst || 2) - (o.lift || 0), tx: t.x, ty: t.y, to: "theta",
              delay: Math.random() * (o.spread || .35), life: 0, s: Math.random(), size: o.size || 1.5, hue: o.hue}); }
  }
  // from Theta into an area, landing on it (its reply, its cards)
  function emitTo(el, n) {
    const r = rectOf(el); if (!r || !ensure()) return; const t = theta();
    for (let i = 0; i < (n || 70); i++) P.push({x: t.x + (Math.random() - .5) * 10, y: t.y + (Math.random() - .5) * 10, vx: (Math.random() - .5) * 3, vy: (Math.random() - .5) * 3,
      tx: r.left + Math.random() * r.width, ty: r.top + Math.random() * r.height, to: "land", delay: Math.random() * .3, life: 0, s: Math.random(), size: 1.5});
  }
  // a widget crumbles into dots in place, which then drift home
  function crumble(el) {
    const r = rectOf(el); if (!r || !ensure()) return; const sp = Math.max(8, Math.sqrt(r.width * r.height / 260)), t = theta();
    for (let x = r.left + sp / 2; x < r.right; x += sp) for (let y = r.top + sp / 2; y < r.bottom; y += sp)
      P.push({x, y, vx: (Math.random() - .5) * 1.5, vy: -Math.random() * 1.5, tx: t.x, ty: t.y, to: "theta", delay: .15 + ((x - r.left) / r.width) * .35 + Math.random() * .1, life: 0, s: Math.random(), size: 1.8, fall: 1});
  }
  function stream(el) { streamTo = el; if (el) ensure(); }
  window.thetaDots = {absorb, emitTo, crumble, stream};

  function frame(now) {
    const dt = Math.min(.05, (now - last) / 1000); last = now; clock += dt;
    if (clock - hueAt > 1.5) { hue = readHue(); hueAt = clock; }
    g.clearRect(0, 0, W, H);
    const t = theta();
    if (streamTo && streamTo.isConnected && rectOf(streamTo)) { const r = rectOf(streamTo); // while Theta works: a stream of dots from it to the chat
      if (Math.random() < .7) P.push({x: t.x, y: t.y, vx: (Math.random() - .5) * 2, vy: (Math.random() - .5) * 2, tx: r.left + 24 + Math.random() * Math.min(160, r.width - 24), ty: r.top + r.height / 2,
        to: "fade", delay: 0, life: 0, s: Math.random(), size: 1.3}); }
    else streamTo = null;
    g.globalCompositeOperation = "lighter";
    for (let i = P.length - 1; i >= 0; i--) {
      const p = P[i]; p.life += dt; if (p.life < p.delay) continue;
      const age = p.life - p.delay;
      if (p.to === "theta") { p.tx = t.x; p.ty = t.y; }
      if (p.fall && age < .35) { p.vy += .12; p.x += p.vx; p.y += p.vy; } // a crumble first falls apart a little
      else { const k = .045 + .03 * p.s; p.vx = (p.vx + (p.tx - p.x) * k) * .82; p.vy = (p.vy + (p.ty - p.y) * k) * .82; p.x += p.vx; p.y += p.vy; }
      const d = Math.hypot(p.tx - p.x, p.ty - p.y), sp = Math.hypot(p.vx, p.vy);
      let a = Math.min(1, age * 4);
      if (p.to === "land" && d < 3) a *= Math.max(0, 1 - (age - p.arr || 0)); // landed: fade into what formed
      if (p.to === "land" && d < 3 && p.arr == null) p.arr = age;
      if ((p.to === "theta" && d < 8) || (p.to === "fade" && d < 6) || (p.to === "land" && p.arr != null && age - p.arr > .5) || age > 4) { P.splice(i, 1); continue; }
      g.fillStyle = `hsla(${(p.hue != null ? p.hue : hue) + 20 * (p.s - .5)},${70 + Math.min(25, sp * 3)}%,${66 + Math.min(20, sp * 2)}%,${a * (.55 + .45 * p.s)})`;
      g.beginPath(); g.arc(p.x, p.y, p.size * (.7 + .6 * p.s), 0, TAU); g.fill();
    }
    g.globalCompositeOperation = "source-over";
    if (P.length || streamTo) requestAnimationFrame(frame); else { running = false; g.clearRect(0, 0, W, H); }
  }
  // a tapped option or answer goes back to Theta as a burst
  document.addEventListener("click", e => { const b = e.target.closest(".msg-acts .btn,.quizcard button,.cfgcard button,#term-body .btn"); if (b) absorb(b, 26, {burst: 4, spread: .15, size: 1.3}); }, true);
})();
'''
_DOTFRAME_JS = r'''(() => {
  // ---- The Theta frames (2026-11-06, from the Dot UI Lab): every card is made of Theta's own dots. Grain and Press
  // print the card in a halftone; Lines, Nebula and Settle make it a constellation (Settle sits in a neat grid while
  // Theta is at rest and comes alive when it listens, thinks or speaks). Dots stream out of Theta when a card appears
  // and fly home when it goes; they follow Theta's state, voice and mood, and scatter from your finger. One canvas
  // over the page that only adds light (screen), so words stay readable. Off with reduced motion.
  const KINDS = {grain: "print", press: "print", lines: "swarm", nebula: "swarm", settle: "swarm"};
  const SEL = ".card,.win,.kpi,.w,.holo,.term:not([hidden]),.dialog-card";
  const root = document.documentElement, TAU = Math.PI * 2, MAXDOTS = 2600;
  let cv = null, g = null, W = 0, H = 0, dpr = 1, running = false, clock = 0, last = 0, level = 0, hue = 195, hueAt = 0;
  const cards = new Map(), seen = new WeakSet(), SW = {idle: 1, listening: 0, thinking: 0, speaking: 0};
  let touch = {x: -999, y: -999, t: -9}, homing = [];
  const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const variant = () => root.dataset.glassstyle;
  const hsla = (h, s, l, a) => `hsla(${(h % 360 + 360) % 360},${s}%,${Math.min(97, l)}%,${Math.max(0, Math.min(1, a))})`;
  function source() { const e = document.getElementById("head-av") || document.querySelector(".theta-mini");
    if (e) { const r = e.getBoundingClientRect(); if (r.width) return {x: r.left + r.width / 2, y: r.top + r.height / 2}; } return {x: innerWidth - 30, y: 30}; }
  function moodHue() { // Theta's mood color (or the theme's), as a hue
    const c = getComputedStyle(root).getPropertyValue("--mood").trim() || getComputedStyle(root).getPropertyValue("--accent2").trim();
    const m = c.match(/^#([0-9a-f]{6})$/i); if (!m) return hue;
    const n = parseInt(m[1], 16), r = (n >> 16 & 255) / 255, gg = (n >> 8 & 255) / 255, b = (n & 255) / 255, mx = Math.max(r, gg, b), mn = Math.min(r, gg, b), d = mx - mn;
    if (!d) return hue; let h = mx === r ? ((gg - b) / d) % 6 : mx === gg ? (b - r) / d + 2 : (r - gg) / d + 4; return (h * 60 + 360) % 360;
  }
  function size() { dpr = Math.min(2, devicePixelRatio || 1); W = innerWidth; H = innerHeight; cv.width = W * dpr; cv.height = H * dpr; g.setTransform(dpr, 0, 0, dpr, 0, 0); }
  function start() {
    if (running) return; running = true;
    cv = document.createElement("canvas"); cv.className = "dotframe"; cv.setAttribute("aria-hidden", "true"); document.body.append(cv);
    g = cv.getContext("2d"); size(); addEventListener("resize", size); last = performance.now(); requestAnimationFrame(frame);
  }
  function stop() { running = false; cards.clear(); homing = []; if (cv) cv.remove(); cv = null; removeEventListener("resize", size); }
  function spawn(el, R, fromTheta) {
    const v = variant(), kind = KINDS[v], area = R.w * R.h, s0 = source(), list = [];
    const budget = Math.max(60, Math.min(520, (MAXDOTS - [...cards.values()].reduce((n, c) => n + c.dots.length, 0)) / 2));
    const mk = (gx, gy, i, n) => ({gx, gy, i, n, u: i / n, ph: Math.random() * TAU, pace: .6 + Math.random() * .8, s: Math.random(),
      x: fromTheta ? s0.x + (Math.random() - .5) * 8 : R.x + gx * R.w, y: fromTheta ? s0.y + (Math.random() - .5) * 8 : R.y + gy * R.h, vx: 0, vy: 0,
      delay: fromTheta ? Math.random() * .3 : 0, cx: gx, cy: gy});
    if (kind === "print" || v === "settle") {
      const base = v === "grain" ? 7 : v === "press" ? 8 : 10, sp = Math.max(base, Math.sqrt(area / budget));
      const cols = Math.max(2, Math.floor(R.w / sp)), rows = Math.max(2, Math.floor(R.h / sp));
      for (let a = 0; a < cols; a++) for (let b = 0; b < rows; b++) list.push(mk((a + .5) / cols, (b + .5) / rows, a * rows + b, cols * rows));
      if (v === "settle") list.forEach(d => { d.cx = d.gx; d.cy = d.gy; d.gx = Math.random(); d.gy = Math.random(); });
    } else {
      const n = Math.round(Math.min(budget, area / (v === "lines" ? 150 : 70)));
      for (let i = 0; i < n; i++) { const d = mk(Math.random(), Math.random(), i, n);
        if (v === "nebula" && Math.random() < .8) { const e = .015 + Math.random() * .06 * (Math.random() < .6 ? 1 : 1.8); if (Math.random() < R.h / (R.w + R.h)) d.gx = Math.random() < .5 ? e : 1 - e; else d.gy = Math.random() < .5 ? e : 1 - e; }
        list.push(d); }
    }
    return {el, dots: list, born: clock, v};
  }
  function scan() { // which cards are on screen now: new ones form from Theta (or in place, if seen before), gone ones go home
    const v = variant(), now = new Set();
    document.querySelectorAll(SEL).forEach(el => {
      const r = el.getBoundingClientRect(); if (r.width < 40 || r.height < 30 || r.bottom < -60 || r.top > H + 60) return;
      const cs = getComputedStyle(el); if (cs.visibility === "hidden" || +cs.opacity < .05) return;
      if (el.parentElement && el.parentElement.closest(SEL)) return; // a card inside a card: the outer one has the dots
      now.add(el);
      const c = cards.get(el);
      if (!c || c.v !== v) { cards.set(el, spawn(el, {x: r.left, y: r.top, w: r.width, h: r.height}, !seen.has(el))); seen.add(el); }
    });
    for (const [el, c] of cards) if (!now.has(el)) { cards.delete(el); if (el.isConnected === false || !el.getBoundingClientRect().width) homing.push(...c.dots.map(d => (d.home = 1, d))); }
  }
  let scanAt = 0;
  function frame(nowMs) {
    if (!running) return;
    const v = variant(); if (!KINDS[v] || still()) { stop(); return; }
    const dt = Math.min(.05, (nowMs - last) / 1000); last = nowMs; clock += dt;
    const TH = window.thetaHead, state = TH && TH.state ? TH.state() : "idle", lv = TH && TH.level ? TH.level() : 0;
    for (const k in SW) SW[k] += ((state === k ? 1 : 0) - SW[k]) * Math.min(1, dt * 3.2);
    level += (lv - level) * .3;
    if (clock - hueAt > 1) { hue = moodHue(); hueAt = clock; }
    if (clock - scanAt > .25) { scan(); scanAt = clock; }
    g.clearRect(0, 0, W, H);
    const t = clock, th = source(), lineSets = [];
    g.globalCompositeOperation = "lighter";
    const draw = (d, tx, ty, rad, a, h) => {
      const k = .05 + .04 * d.pace; d.vx = (d.vx + (tx - d.x) * k) * .8; d.vy = (d.vy + (ty - d.y) * k) * .8; d.x += d.vx; d.y += d.vy;
      if (a <= .01 || rad <= .2) return; const sp = Math.hypot(d.vx, d.vy);
      g.fillStyle = hsla(h, 70 + 20 * Math.min(1, sp / 6), 62 + Math.min(18, sp * 2), a); g.beginPath(); g.arc(d.x, d.y, rad, 0, TAU); g.fill(); };
    for (const [el, c] of cards) {
      const r = el.getBoundingClientRect(), R = {x: r.left, y: r.top, w: r.width, h: r.height}, age = t - c.born, set = [];
      for (const d of c.dots) {
        if (age < d.delay) { draw(d, th.x, th.y, 0, 0, hue); continue; }
        let hh = hue + 7 * Math.sin(t * d.pace * 1.7 + d.ph) * SW.idle, tx, ty, rad, a;
        const touched = Math.max(0, 1 - Math.hypot(d.x - touch.x, d.y - touch.y) / 60) * Math.max(0, 1 - (t - touch.t) * .8);
        if (c.v === "grain" || c.v === "press") {
          tx = R.x + d.gx * R.w; ty = R.y + d.gy * R.h;
          const edge = Math.min(d.gx, 1 - d.gx, d.gy * R.h / R.w, (1 - d.gy) * R.h / R.w) * 2, settled = Math.min(1, Math.max(0, age - 1.2) * 1.2);
          if (c.v === "grain") {
            const grow = Math.max(0, Math.min(1, (age - .15 - Math.hypot(tx - th.x, ty - th.y) / H * 1.1) / .45));
            const keep = Math.max(0, 1 - edge * 5) ** 1.5 + (Math.min(d.gx, 1 - d.gx) < .06 && Math.min(d.gy, 1 - d.gy) < .2 ? .5 : 0);
            const ring = Math.max(0, Math.sin(Math.hypot(tx - th.x, ty - th.y) * .09 - t * 6)) ** 3 * level * SW.speaking;
            rad = 2.3 * grow * ((1 - settled) + settled * (keep * (.6 + .4 * Math.sin(t * d.pace + d.ph)) + 1.1 * ring + 1.4 * touched + .5 * SW.thinking * Math.max(0, Math.sin((d.gx - d.gy) * 9 - t * 4)) * keep));
            a = .5 * grow; hh += 28 * ring - 26 * SW.listening * (1 - d.gy) + 40 * Math.sin(d.gx * 6 + t * 3) * SW.thinking;
          } else {
            const grow = Math.max(0, Math.min(1, (age - .15 - d.gy * .6) / .25)), lit = (1 - d.gy) ** 1.4, shimmer = Math.max(0, Math.sin((d.gx + d.gy) * 7 - t * 4)) ** 4 * SW.thinking;
            rad = 2.4 * grow * ((1 - settled) + settled * (lit * (.75 + .25 * Math.sin(t * d.pace + d.ph)) * (1 + .5 * level * SW.speaking) + .45 * SW.listening * (d.gy < .35 ? 1 : 0) + .8 * shimmer + 1.2 * touched));
            a = .4 * grow; hh += 30 * level * SW.speaking - 26 * SW.listening * (1 - d.gy) + 40 * shimmer;
          }
        } else {
          const swirl = SW.thinking * t * .8 * (d.s - .5), ang = d.ph + swirl, rr = (c.v === "lines" ? .05 : .04) * Math.sin(t * d.pace + d.ph);
          let fx = d.gx + rr * Math.cos(ang), fy = d.gy + rr * Math.sin(ang) * 1.6;
          if (SW.thinking > .01) { const dx = fx - .5, dy = fy - .5, a2 = Math.atan2(dy, dx) + t * .9 * SW.thinking * (.5 + d.s), r2 = Math.hypot(dx, dy); fx = .5 + Math.cos(a2) * r2; fy = .5 + Math.sin(a2) * r2; }
          if (c.v === "settle") { const calm = SW.idle * Math.min(1, Math.max(0, age - .8) * 1.5); fx += (d.cx - fx) * calm; fy += (d.cy - fy) * calm; }
          const swell = 1 + .08 * level * SW.speaking * Math.sin(d.gx * 9 - t * 7) + .02 * Math.sin(t * 1.3);
          tx = R.x + R.w / 2 + (fx - .5) * R.w * swell; ty = R.y + R.h / 2 + (fy - .5) * R.h * swell;
          if (touched > .05) { const dx = tx - touch.x, dy = ty - touch.y, dd = Math.hypot(dx, dy) || 1; tx += dx / dd * 26 * touched; ty += dy / dd * 26 * touched; }
          const edgeFade = Math.min(1, Math.min(fx, 1 - fx, fy, 1 - fy) * 9 + .15);
          rad = c.v === "nebula" ? (d.s > .85 ? 2.4 : 1 + .6 * d.s) + level * SW.speaking : c.v === "settle" ? 1.1 + 1.1 * SW.idle * (1 - fy) + level * SW.speaking : 1.4 + .5 * d.s;
          a = (c.v === "nebula" ? (d.s > .85 ? .2 : .26 + .4 * d.s) : c.v === "settle" ? .22 + .36 * d.s * (1 - SW.idle) + .2 * SW.idle : .38 + .4 * d.s) * edgeFade;
          hh += -30 * SW.listening * (1 - fy) + 40 * Math.sin(Math.atan2(fy - .5, fx - .5) * 2 + t * 3) * SW.thinking + 26 * level * SW.speaking;
          if (c.v === "lines") set.push(d);
        }
        draw(d, tx, ty, rad, a, hh);
      }
      if (set.length) lineSets.push(set);
    }
    for (let i = homing.length - 1; i >= 0; i--) { const d = homing[i]; draw(d, th.x, th.y, 1.2, .6 * Math.min(1, Math.hypot(d.x - th.x, d.y - th.y) / 80), hue);
      if (Math.hypot(d.x - th.x, d.y - th.y) < 6 || homing.length > 1500) homing.splice(i, 1); }
    g.lineWidth = .7;
    for (const L of lineSets) for (let i = 0; i < L.length; i++) for (let j = i + 1; j < L.length; j++) { const p = L[i], q = L[j], dx = p.x - q.x, dy = p.y - q.y;
      if (Math.abs(dx) > 26 || Math.abs(dy) > 26) continue; const dd = Math.hypot(dx, dy); if (dd > 26) continue;
      g.strokeStyle = hsla(hue + 40 * SW.thinking * Math.sin(p.u * 9 + t * 3), 70, 66, (1 - dd / 26) * (.26 + .3 * SW.thinking + .2 * level * SW.speaking));
      g.beginPath(); g.moveTo(p.x, p.y); g.lineTo(q.x, q.y); g.stroke(); }
    g.globalCompositeOperation = "source-over";
    requestAnimationFrame(frame);
  }
  document.addEventListener("pointerdown", e => { if (!running) return; touch = {x: e.clientX, y: e.clientY, t: clock};
    for (const c of cards.values()) for (const d of c.dots) { const dx = d.x - e.clientX, dy = d.y - e.clientY, r = Math.hypot(dx, dy); if (r < 70) { const k = (1 - r / 70) * 9; d.vx += dx / (r || 1) * k; d.vy += dy / (r || 1) * k; } } }, {passive: true});
  const check = () => { if (KINDS[variant()] && !still() && document.body) start(); };
  new MutationObserver(check).observe(root, {attributes: true, attributeFilter: ["data-glassstyle"]});
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", check); else check();
})();
'''
_CHARM_JS_SRC = r'''(() => {
  // ---- The charm of each theme (2026-11-06): how it celebrates when you finish something (a reminder done, a
  // daily check ticked, a widget cleared). A short, quiet moment in the theme's own character; never with
  // reduced motion. window.thetaCheer(x, y) from wherever the thing was finished.
  const CHEER = __CHEERS__, root = document.documentElement;
  const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const dark = () => root.dataset.mode === "dark" || (root.dataset.mode !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
  window.thetaCheerKind = () => (CHEER[root.dataset.theme] || CHEER.theta).kind;
  window.thetaCheer = (x, y) => {
    document.dispatchEvent(new CustomEvent("theta:cheer")); // Theta takes it in too (proud for a moment)
    if (still()) return;
    const c = CHEER[root.dataset.theme] || CHEER.theta, [A, B, T] = dark() ? c.dark : c.light, kind = c.kind;
    if (x == null) { x = innerWidth / 2; y = innerHeight / 2; }
    const cv = document.createElement("canvas"), dpr = Math.min(2, devicePixelRatio || 1);
    cv.className = "cheer"; cv.width = innerWidth * dpr; cv.height = innerHeight * dpr; cv.setAttribute("aria-hidden", "true");
    document.body.append(cv);
    const g = cv.getContext("2d"); g.scale(dpr, dpr);
    const r = (m, n) => m + Math.random() * (n - m), ease = k => 1 - Math.pow(1 - k, 3);
    const font = getComputedStyle(root).getPropertyValue("--f-label") || "system-ui";
    let P = [], DUR = 1100;
    if (kind === "petal" || kind === "leaf") { DUR = 1700;
      P = Array.from({length: 14}, (_, i) => ({x: x + r(-30, 30), y: y + r(-20, 10), vx: r(-1.2, 1.2), vy: r(-2.6, -.8), rot: r(0, 6), vr: r(-.08, .08), s: r(4, 7), c: i % 3 ? A : B, ph: r(0, 6)})); }
    if (kind === "spark") { DUR = 1200; P = Array.from({length: 22}, (_, i) => ({x: x + r(-12, 12), y, vx: r(-1.4, 1.4), vy: r(-4.5, -1.5), s: r(1.2, 2.6), c: i % 4 ? A : B, f: r(0, 6)})); }
    if (kind === "glint") { DUR = 1300; P = Array.from({length: 6}, (_, i) => ({x: x + r(-70, 70), y: y + r(-46, 30), s: r(5, 11), d: i * .09, c: i % 2 ? A : B})); }
    if (kind === "star") { DUR = 1300; P = Array.from({length: 9}, () => ({a: r(0, 6.3), d: r(14, 46), s: r(1, 2.2)})); }
    function frame(now) {
      const k = Math.min(1, (now - t0) / DUR); g.clearRect(0, 0, innerWidth, innerHeight);
      if (kind === "check") { // a ring draws itself, then the tick: calm and exact
        const u = ease(Math.min(1, k * 1.8)), v = Math.max(0, Math.min(1, (k - .35) * 2.6)); g.globalAlpha = k < .75 ? 1 : (1 - k) * 4;
        g.lineWidth = 2.5; g.lineCap = "round"; g.strokeStyle = A; g.beginPath(); g.arc(x, y, 20, -1.57, -1.57 + 6.283 * u); g.stroke();
        if (v) { g.beginPath(); g.moveTo(x - 8, y + 1); const p1 = Math.min(1, v * 2), p2 = Math.max(0, v * 2 - 1);
          g.lineTo(x - 8 + 6 * p1, y + 1 + 6 * p1); if (p2) g.lineTo(x - 2 + 11 * p2, y + 7 - 14 * p2); g.stroke(); }
      } else if (kind === "orbit") { // Theta: a ring opens around it, three moons go round once
        const u = ease(k), R = 14 + 34 * u; g.globalAlpha = 1 - k; g.lineWidth = 1.5; g.strokeStyle = A;
        g.beginPath(); g.arc(x, y, R, 0, 6.283); g.stroke();
        for (let i = 0; i < 3; i++) { const t = -1.57 + i * 2.094 + u * 6.283; g.fillStyle = i ? A : B; g.beginPath(); g.arc(x + R * Math.cos(t), y + R * Math.sin(t), 3, 0, 6.283); g.fill(); }
      } else if (kind === "ripple" || kind === "neon") { // rings on water (or neon, with a glow)
        if (kind === "neon") { g.shadowColor = A; g.shadowBlur = 14; }
        for (let i = 0; i < 3; i++) { const u = Math.max(0, k * 1.4 - i * .18); if (!u || u > 1) continue;
          g.globalAlpha = (1 - u) * .9; g.lineWidth = kind === "neon" ? 2.5 : 1.5; g.strokeStyle = i % 2 ? B : A;
          g.beginPath(); g.ellipse(x, y, 10 + 60 * ease(u), (10 + 60 * ease(u)) * (kind === "neon" ? 1 : .55), 0, 0, 6.283); g.stroke(); }
      } else if (kind === "wash") { // Aurora: a breath of colored light
        const u = ease(k), R = 40 + 220 * u, gr = g.createRadialGradient(x, y, 0, x, y, R);
        gr.addColorStop(0, A); gr.addColorStop(.5, B); gr.addColorStop(1, "transparent"); g.globalAlpha = .28 * (1 - k); g.fillStyle = gr; g.fillRect(x - R, y - R, R * 2, R * 2);
      } else if (kind === "star") { // a shooting star lands where you finished, and twinkles
        const u = Math.min(1, k * 2.2), sx = x - 170 + 170 * ease(u), sy = y - 110 + 110 * ease(u);
        if (u < 1) { const gr = g.createLinearGradient(sx - 60, sy - 39, sx, sy); gr.addColorStop(0, "transparent"); gr.addColorStop(1, T);
          g.strokeStyle = gr; g.lineWidth = 2; g.globalAlpha = 1; g.beginPath(); g.moveTo(sx - 60, sy - 39); g.lineTo(sx, sy); g.stroke(); }
        else P.forEach(p => { const w = Math.sin((k - .45) / .55 * 3.14); g.globalAlpha = Math.max(0, w); g.fillStyle = T; g.beginPath();
          g.arc(x + Math.cos(p.a) * p.d * (k + .2), y + Math.sin(p.a) * p.d * (k + .2), p.s, 0, 6.283); g.fill(); });
      } else if (kind === "stamp" || kind === "print") { // Paper's ink stamp, Scanner's tag, Terminal's printout
        const word = c.word;
        if (kind === "stamp") { const u = Math.min(1, k * 4), s = 1.7 - .7 * ease(u); g.save(); g.translate(x, y - 34); g.rotate(-.14); g.scale(s, s);
          g.globalAlpha = Math.min(1, u * 1.5) * (k < .7 ? 1 : (1 - k) / .3); g.strokeStyle = A; g.fillStyle = A; g.lineWidth = 2;
          g.font = "700 15px " + font; const w = g.measureText(word).width + 18; g.strokeRect(-w / 2, -13, w, 26); g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(word, 0, 1); g.restore(); }
        else { const n = Math.ceil(Math.min(1, k * 2.2) * word.length); g.globalAlpha = k < .75 ? 1 : (1 - k) * 4; g.fillStyle = A;
          g.font = "600 14px " + (getComputedStyle(root).getPropertyValue("--f-mono") || "monospace"); g.textBaseline = "middle";
          g.fillText(word.slice(0, n) + (k < .9 && (now / 260 | 0) % 2 ? "▌" : ""), x - 40, y - 30); }
      } else if (kind === "glint") { // the gilded themes: little four-point stars catch the light
        P.forEach(p => { const u = Math.max(0, Math.min(1, (k - p.d) * 1.6)), s = p.s * Math.sin(u * 3.14); if (s <= 0) return;
          g.globalAlpha = .95; g.fillStyle = p.c; g.beginPath(); g.moveTo(p.x, p.y - s); g.quadraticCurveTo(p.x, p.y, p.x + s, p.y); g.quadraticCurveTo(p.x, p.y, p.x, p.y + s);
          g.quadraticCurveTo(p.x, p.y, p.x - s, p.y); g.quadraticCurveTo(p.x, p.y, p.x, p.y - s); g.fill(); });
      } else { // petals, leaves and sparks: a handful of light things in the theme's colors
        P.forEach(p => {
          if (kind === "spark") { p.vy += .06; p.x += p.vx; p.y += p.vy; g.globalAlpha = (1 - k) * (.6 + .4 * Math.sin(now / 40 + p.f)); g.fillStyle = p.c;
            g.shadowColor = p.c; g.shadowBlur = 8; g.beginPath(); g.arc(p.x, p.y, p.s, 0, 6.283); g.fill(); return; }
          p.vy = Math.min(p.vy + .07, 1.6); p.x += p.vx + Math.sin(now / 300 + p.ph) * .6; p.y += p.vy; p.rot += p.vr;
          g.globalAlpha = k < .6 ? 1 : (1 - k) / .4; g.fillStyle = p.c; g.save(); g.translate(p.x, p.y); g.rotate(p.rot); g.beginPath();
          if (kind === "leaf") { g.moveTo(-p.s, 0); g.quadraticCurveTo(0, -p.s * .7, p.s, 0); g.quadraticCurveTo(0, p.s * .7, -p.s, 0); }
          else g.ellipse(0, 0, p.s, p.s * .6, 0, 0, 6.283);
          g.fill(); g.restore(); });
      }
      if (k < 1) requestAnimationFrame(frame); else cv.remove();
    }
    const t0 = performance.now(); requestAnimationFrame(frame);
  };

  // ---- The charm of each frame: how it answers a touch. A light effect on the thing you pressed, in the
  // frame's own manner (CSS: the .tap class and the .tapfx layer); nothing moves the layout.
  const TAPPABLE = "button,.btn,a.chip,.chip,.bchip,.minichips a,.tabbar a,.w,.card a,.seg button,.sw,.lrow,summary";
  document.addEventListener("pointerdown", e => {
    if (still()) return;
    const el = e.target.closest(TAPPABLE); if (!el || el.disabled || el.closest(".cheer")) return;
    const b = el.getBoundingClientRect(); if (!b.width) return;
    el.style.setProperty("--tx", (e.clientX - b.left) + "px"); el.style.setProperty("--ty", (e.clientY - b.top) + "px");
    let fx = el.querySelector(":scope > .tapfx");
    if (!fx) { fx = document.createElement("span"); fx.className = "tapfx"; fx.setAttribute("aria-hidden", "true");
      if (getComputedStyle(el).position === "static") el.style.position = "relative"; el.append(fx); }
    el.classList.remove("tap"); void el.offsetWidth; el.classList.add("tap");
    clearTimeout(el._tapT); el._tapT = setTimeout(() => el.classList.remove("tap"), 700);
  }, {passive: true});
})();
'''


def _cheers_json():
    return json.dumps({k: {"kind": CHEERS.get(k, ("check", ""))[0], "word": CHEERS.get(k, ("check", ""))[1],
                           "light": [t["light"]["accent"], t["light"]["accent2"], t["light"]["text"]],
                           "dark": [t["dark"]["accent"], t["dark"]["accent2"], t["dark"]["text"]]} for k, t in THEMES.items()})


_UI_CSS = theme_css() + "\n" + _BASE_CSS + "\n" + _hdr_css() + "\n" + _frames_css() + "\n" + _fonts_css() + _MOVE_CSS + _BAR_CSS + "\n/* ---- inside the Theta page's sheet (2026-11-04): the page alone, without the app's own bars */\nhtml.embedded .tabbar,html.embedded .minibar,html.embedded .theta-mini,html.embedded .rail{display:none!important}\nhtml.embedded .main{padding-top:14px;padding-bottom:calc(28px + env(safe-area-inset-bottom,0px))}\nhtml.embedded body.has-mini header.top{padding-right:0}\n" + "\nhtml.veiled .app,html.veiled .tabbar{visibility:hidden}" + "\n:root[data-glassstyle=\"liquid\"] .tabbar,:root[data-glassstyle=\"holo\"] .tabbar,:root[data-glassstyle=\"liquid\"] .minibar,:root[data-glassstyle=\"holo\"] .minibar{background:color-mix(in srgb,var(--bg) 88%,transparent);-webkit-backdrop-filter:blur(26px) saturate(160%);backdrop-filter:blur(26px) saturate(160%)}" + "\n" + _CHARM_CSS
_UI_JS = _UI_JS_SRC.replace("__THEMES__", json.dumps(
    {n: {"glass": bool(t.get("glass")), "mono": bool(t.get("mono")), "light": t["light"]["bg"],
         "dark": t["dark"]["bg"], "accent2": t["dark"]["accent2"]} for n, t in THEMES.items()})) + "\n" + _CHARM_JS_SRC.replace("__CHEERS__", _cheers_json()) + "\n" + _DOTFRAME_JS + "\n" + _DOTMOMENTS_JS
_ASSET_V = hashlib.sha1((_UI_CSS + _UI_JS + _CHAT_JS).encode()).hexdigest()[:10]


def ui_prefs(headers):
    """(theme, mode, layout, glassstyle, bg) from the theta_ui cookie, with defaults."""
    raw = (_cookie(headers, "theta_ui") or "").split(".")
    theme = raw[0] if raw[0] in THEMES else "theta"
    mode = raw[1] if len(raw) > 1 and raw[1] in MODES else "auto"
    layout = raw[2] if len(raw) > 2 and raw[2] in LAYOUTS else "grid"
    glassstyle = raw[3] if len(raw) > 3 and raw[3] in FRAMES else "plus"
    bg = raw[4] if len(raw) > 4 and raw[4] in ("theme", "shards", "stars", "black", "gemini", "image", "spotlight") else "theme"
    return theme, mode, layout, glassstyle, bg


def ui_type(headers):
    """The font picked in Settings (frame = the frame's own), the 6th part of the theta_ui cookie."""
    raw = (_cookie(headers, "theta_ui") or "").split(".")
    return raw[5] if len(raw) > 5 and raw[5] in FONT_PICKS else "frame"


def avatar_img(agent, size=40):
    return (f'<img src="/avatar/{html.escape(agent)}.svg" width="{size}" height="{size}" alt="" '
            f'class="av" loading="lazy">')


def _json_script(name, obj):
    safe = json.dumps(obj).replace("</", "<\\/")  # a "</script>" in the data can't end the tag
    return f"<script>window.{name} = {safe};</script>"


MINIBAR_SUGGESTIONS = {
    "/": ["What's new today?", "Summarize my day", "What needs my attention?"],
    "/diagnostics": ["What's broken right now?", "Which models are down?", "Check the crew's wiring"],
    "/settings": ["Help me set up reminders", "How do I add a budget?", "Change the color scheme"],
    "/calendar": ["What's on today?", "What do I have tomorrow?", "Remind me about something"],
    "/money": ["How much have I spent this month?", "What's over budget?", "Log an expense"],
}


def minibar_html(active):
    """Persistent chat bar above the tab bar. Its Send button submits
    through /api/allchat (the same endpoint and payload the full
    composer uses); without JS the form still GETs to /chat with ?say=
    as a draft, so no message is lost. Suggestion chips still open
    chat with a draft; they are not sends."""
    sugg = MINIBAR_SUGGESTIONS.get(active, MINIBAR_SUGGESTIONS["/"])
    who = "Message Theta\u2026" if head_on() else "Message the crew\u2026"  # only Theta answers in single-head mode
    chips = "".join(f'<a href="/chat?say={quote(s)}">{html.escape(s)}</a>' for s in sugg)
    return (f'<div class="minibar"><div class="minichips">{chips}</div>'
            f'<form class="minibox" action="/chat" method="get" role="search">'
            f'<input type="text" name="say" maxlength="300" placeholder="{who}" aria-label="{who.rstrip(chr(8230))}" '
            f'enterkeyhint="send" autocomplete="off">'
            f'<button class="btn send" type="submit" aria-label="Send">{ui_icon("send")}</button></form>'
            f'<p class="minibar-status" role="status" hidden></p></div>')


def page(headers, title, active, body, body_class="", statuses=None, chat=None):
    """A full page in the app shell: sidebar on wide screens, tab bar on phones."""
    theme, mode, layout, glassstyle, bg = ui_prefs(headers)
    t = THEMES[theme]
    bgstyle = (' style="background:#000"' if bg == "gemini" else
               ' style="background:#000"' if bg in ("shards", "stars", "black", "image", "spotlight") else "")
    if mode == "auto":
        metas = (f'<meta name="theme-color" content="{t["light"]["bg"]}" media="(prefers-color-scheme: light)">'
                 f'<meta name="theme-color" content="{t["dark"]["bg"]}" media="(prefers-color-scheme: dark)">')
    else:
        metas = f'<meta name="theme-color" content="{t[mode]["bg"]}">'
    flags = (" data-glass" if t.get("glass") else "") + (' data-font="mono"' if t.get("mono") else "")
    statuses = agent_statuses() if statuses is None else statuses
    crew = "".join(
        f'<a class="crewlink" href="/agent/{a["bot_id"]}" title="{html.escape(a["name"])}"><span class="avw">{avatar_img(a["bot_id"], 26)}'
        f'<span class="dot{" on" if a["online"] else ""}"></span></span>{html.escape(a["name"])}'
        f'<span class="act">{html.escape(a["activity"] if a["online"] else a["tier"])}</span></a>'
        for a in statuses if a["bot_id"] in AGENTS)
    nav = "".join(f'<a href="{href}" class="{"on" if href == active else ""}" aria-label="{label}" title="{label}"'
                  f'{" aria-current=page" if href == active else ""}>{ui_icon(icon)}<span>{label}</span></a>'
                  for href, label, icon in NAV)
    more = "".join(f'<a href="{href}" class="{"on" if href == active else ""}" aria-label="{label}" title="{label}"'
                   f'{" aria-current=page" if href == active else ""}>{ui_icon(icon)}<span>{label}</span></a>'
                   for href, label, icon in NAV_MORE)
    show_minibar = "chatpage" not in body_class.split()  # the chat page (and the Head page, which is the chat) has the full composer
    if active != "/head":
        body_class = (body_class + " has-mini").strip()  # Theta sits in the top-right corner of this page
    body_cls = ("hasminibar " + body_class).strip() if show_minibar else body_class
    return (
        f'<!doctype html><html lang="en" data-theme="{theme}" data-mode="{mode}" data-layout="{layout}" data-glassstyle="{glassstyle}" data-bg="{bg}" data-type="{ui_type(headers)}"{flags}{bgstyle}>'
        '<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        + ('<script>window.THETA_ONEPAGE=true</script>' if head_on() else '')  # one page: others open inside the Theta page
        + f'<title>{html.escape(title)} · {APP_NAME}</title>'
        '<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">'
        '<link rel="apple-touch-icon" href="/apple-touch-icon.png?v=2"><link rel="icon" href="/avatar/theta.svg" type="image/svg+xml">'
        f'<meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="{APP_NAME}">'
        '<meta name="apple-mobile-web-app-status-bar-style" content="default">'
        f'{metas}<link rel="stylesheet" href="/ui.css?v={_ASSET_V}">'
        # Request headers for page scripts, defined before any of them runs.
        '<script>window.THETA_H = {"Content-Type": "application/json", "x-dashboard-key": '
        'new URLSearchParams(location.search).get("key") || ""};'
        # The app opens on Theta: opened from its Home Screen icon, a launch onto Home goes to the Theta page
        # (an icon added before start_url changed still opens "/"). After that, Home is just a tab.
        'try{var emb=window.top!==window;if(emb)document.documentElement.classList.add("embedded");if(window.THETA_ONEPAGE&&!emb&&location.pathname!=="/head"&&!/[?&]full=1/.test(location.search)){location.replace(location.pathname==="/"&&!location.hash?"/head"+location.search:"/head?open="+encodeURIComponent(location.pathname+location.search+location.hash))}}catch(e){}try{window.thetaVT=("onpagereveal" in window)&&CSS.supports("view-transition-name:a")&&!matchMedia("(prefers-reduced-motion: reduce)").matches}catch(e){}try{if(location.pathname==="/"&&(navigator.standalone||matchMedia("(display-mode: standalone)").matches)'
        '&&!sessionStorage.getItem("theta:launched")){sessionStorage.setItem("theta:launched","1");location.replace("/head"+location.search)}'
        'sessionStorage.setItem("theta:launched","1")}catch(e){}'
        + ('window.THETA_LOCK = true;' if (current_session(headers) or {}).get("lock") else '') + '</script>'
        # browsers that support it (Chrome) start loading a page as your finger lands on its link
        + '<script type="speculationrules">{"prefetch":[{"where":{"and":[{"href_matches":"/*"},{"not":{"href_matches":"/api/*"}},{"not":{"href_matches":"/*\\\\?*key=*"}}]},"eagerness":"moderate"}]}</script></head>'
        f'<body class="{body_cls}"><div class="app"><aside class="rail glass" aria-label="Sidebar">'
        f'<a class="brand" href="/">{avatar_img("theta", 32)}{APP_NAME}</a><nav aria-label="Main">{nav}</nav>'
        f'<div class="label">Sections</div><nav aria-label="Sections">{more}</nav>'
        f'<div class="label">Crew</div>{crew}</aside><main class="main">{body}</main></div>'
        + (minibar_html(active) if show_minibar else "")
        + ('' if active == "/head" else '<a class="theta-mini" href="/head" aria-label="Theta: talk to Theta">'
           '<canvas width="112" height="112" aria-hidden="true"></canvas></a>')  # Theta in the corner of every page
        + f'<nav class="tabbar glass" aria-label="Main">{nav}</nav>'
        + _json_script("THETA_LATEST", latest_by_channel(chat))
        + f'<script src="/ui.js?v={_ASSET_V}"></script>'
        # Some of what's shown was stale: fetch new data now, for the next load (you don't wait on it).
        + ('<script>setTimeout(() => fetch("/api/refresh", {method: "POST", headers: window.THETA_H, body: "{}"})'
           '.catch(() => {}), 1200);</script>' if getattr(_REQ, "stale", False) else "")
        + '</body></html>')


def _ago(ts, now=None):
    if not ts:
        return ""
    secs = max(0, (now or time.time()) - ts)
    if secs < 90:
        return "now"
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if secs >= size:
            return f"{int(secs // size)}{unit}"
    return ""


_OUTLET_LOOKS = [("#334155", "#0f172a"), ("#1e3a8a", "#312e81"), ("#7c2d12", "#431407"), ("#134e4a", "#042f2e"),
                 ("#581c87", "#3b0764"), ("#9f1239", "#4c0519"), ("#365314", "#1a2e05"), ("#0c4a6e", "#082f49")]


def win_html(w):
    if w["agent"]:
        c1, c2, glyph = agent_look(w["agent"])
    else:  # a story with no picture: a newspaper on its outlet's own color
        c1, c2 = _OUTLET_LOOKS[int(hashlib.sha1((w.get("source") or "").encode()).hexdigest(), 16) % len(_OUTLET_LOOKS)]
        glyph = UI_ICONS["news"]
    ph = (f'<div class="ph" style="--c1:{c1};--c2:{c2}"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" '
          f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{glyph}</svg></div>')
    img = (f'<img src="{html.escape(w["image"])}" alt="" loading="lazy" decoding="async"'
           f'{" class=fit" if w.get("fit") else ""} referrerpolicy="no-referrer" onerror="this.remove()">'
           if w.get("image") else "")
    tag = f'<span class="tag">{html.escape(w["tag"])}</span>' if w.get("tag") else ""
    logo = (f'<img class="logo" src="{site_logo(w["site"])}" alt="" width="16" height="16" loading="lazy" '
            f'referrerpolicy="no-referrer" onerror="this.remove()">' if w.get("site") else "")
    if w["agent"]:
        who = f'{avatar_img(w["agent"], 18)}<span class="nm">{html.escape(display_name(w["agent"]))}</span>'
        if w.get("source"):
            who += f'<span class="src">· {logo}{html.escape(w["source"])}</span>'
    else:
        who = f'{logo}<span>{html.escape(w.get("source") or "")}</span>'
    when = _ago(w.get("at"))
    sub = f'<div class="sub">{html.escape(w["sub"])}</div>' if w.get("sub") else ""
    ext = ' target="_blank" rel="noopener"' if w.get("external") else ""
    sheet = {"title": w["raw"] or w["title"] or "", "sub": w.get("sub") or "", "text": w.get("text") or "",
             "links": [[label, url] for label, url in (w.get("links") or []) if url],
             "coverage": w.get("coverage"), "agent": w["agent"],
             "name": display_name(w["agent"]) if w["agent"] else "", "source": w.get("source") or "",
             "page": f"/agent/{w['agent']}" if w["agent"] in AGENTS else "", "remind": w.get("remind")}
    sheet_attr = "" if w.get("nosheet") else f' data-sheet="{html.escape(json.dumps(sheet))}"'
    return (f'<a class="win" href="{html.escape(w["href"])}"{ext}{sheet_attr}>'
            f'<div class="pic">{ph}{img}{tag}</div>'
            f'<div class="body"><div class="who">{who}<span class="t">{when}</span></div>'
            f'<div class="title">{html.escape(w["title"] or "")}</div>{sub}{coverage_html(w.get("coverage"))}</div></a>')


def site_logo(site):
    """A news site's own icon, by domain (DuckDuckGo's favicon service)."""
    return f"https://icons.duckduckgo.com/ip3/{quote(site.lower())}.ico"


_SIDES = (("red", "Red"), ("gray", "Gray"), ("blue", "Blue"))


def coverage_html(cov):
    """How many of each side's outlets carried a story, as a split bar."""
    if not cov or not any(cov.values()):
        return ""
    counts = [(a, label, len(cov.get(a) or [])) for a, label in _SIDES]
    tip = "; ".join(f"{label}'s outlets: {', '.join(cov.get(a) or []) or 'none'}" for a, label, _ in counts)
    bar = "".join(f'<i style="flex:{n};background:{AGENT_LOOKS[a][0]}"></i>' for a, _, n in counts if n)
    text = " · ".join(f"{label} {n}" for _, label, n in counts)
    return (f'<div class="cov" title="{html.escape(tip)}"><div class="covbar" aria-hidden="true">{bar}</div>'
            f'<span>{html.escape(text)}</span></div>')


def _dot_arc(circ, frac, n=20):
    """A progress arc as dots: one dot per twentieth of the ring, as far as the progress goes (2026-11-06)."""
    k = max(0, min(n, round(frac * n)))
    return " ".join([f"0 {circ / n:.2f}"] * k + [f"0 {circ:.2f}"]) if k else f"0 {circ:.2f}"


def ring_svg(frac, size=46, color="var(--accent)"):
    r = (size - 7) / 2
    circ = 2 * 3.14159 * r
    frac = max(0.0, min(frac, 1.0))
    return (f'<svg class="ring" width="{size}" height="{size}" viewBox="0 0 {size} {size}" aria-hidden="true">'
            f'<circle cx="{size / 2}" cy="{size / 2}" r="{r:.1f}" fill="none" stroke="var(--surface2)" stroke-width="4" stroke-linecap="round" stroke-dasharray="0 {circ / 20:.2f}"/>'
            f'<circle cx="{size / 2}" cy="{size / 2}" r="{r:.1f}" fill="none" stroke="{color}" stroke-width="6" '
            f'stroke-linecap="round" stroke-dasharray="{_dot_arc(circ, frac)}" '
            f'transform="rotate(-90 {size / 2} {size / 2})"/></svg>')


# The chart's colors come from the theme (2026-11-06): its two accents, then blends of them and the text,
# so a chart looks like it belongs to the theme it's in. In order, so neighbors stay distinct.
_DONUT_COLORS = ["var(--accent)", "var(--accent2)", "color-mix(in oklab,var(--accent) 50%,var(--accent2))",
                 "color-mix(in oklab,var(--accent) 55%,var(--text))", "color-mix(in oklab,var(--accent2) 55%,var(--text))",
                 "color-mix(in oklab,var(--accent) 55%,var(--bg))", "color-mix(in oklab,var(--accent2) 55%,var(--bg))",
                 "color-mix(in oklab,var(--accent) 30%,var(--muted))", "color-mix(in oklab,var(--accent2) 30%,var(--muted))", "var(--muted)"]


def donut_svg(cats, total, size=180):
    """A spending donut: one segment per category with actual spending.

    cats is [(label, spent), ...] with spent > 0; total is their sum, so the
    legend always reconciles with the header total. Budgets are limits,
    not spending, and never enter the total."""
    r = (size - 28) / 2
    circ = 2 * 3.14159 * r
    segs, off = [], 0.0
    for i, (label, spent) in enumerate(cats):
        frac = spent / total if total else 0
        segs.append(f'<circle cx="{size / 2}" cy="{size / 2}" r="{r:.1f}" fill="none" '
                    f'style="stroke:{_DONUT_COLORS[i % len(_DONUT_COLORS)]}" stroke-width="22" '
                    f'stroke-dasharray="{circ * frac:.1f} {circ:.1f}" stroke-dashoffset="{-off:.1f}" '
                    f'transform="rotate(-90 {size / 2} {size / 2})"/>')
        off += circ * frac
    legend = "".join(
        f'<li><span class="sw" style="background:{_DONUT_COLORS[i % len(_DONUT_COLORS)]}"></span>'
        f'{html.escape(label)}<span class="amt">${spent:,.2f} \u00b7 {spent / total:.0%}</span></li>'
        for i, (label, spent) in enumerate(cats))
    return (f'<div class="donut"><svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
            f'role="img" aria-label="Spending by category, ${total:,.2f} total">'
            f'<circle cx="{size / 2}" cy="{size / 2}" r="{r:.1f}" fill="none" stroke="var(--surface2)" stroke-width="22"/>'
            + "".join(segs)
            + f'<text x="{size / 2}" y="{size / 2 - 2}" text-anchor="middle" font-size="22" font-weight="700" '
            f'style="fill:var(--text)">${total:,.0f}</text>'
            + f'<text x="{size / 2}" y="{size / 2 + 20}" text-anchor="middle" font-size="12" '
            f'style="fill:var(--muted)">spent</text></svg>'
            f'<ul class="legend">{legend}</ul></div>')


def kpi_html(value, label, sub="", frac=None, color="var(--accent)", icon="bolt", href=None):
    lead = ring_svg(frac, color=color) if frac is not None else f'<span class="ico">{ui_icon(icon)}</span>'
    tag, attrs = ("a", f' href="{href}"') if href else ("div", "")
    sub_html = f'<div class="s">{html.escape(sub)}</div>' if sub else ""
    return (f'<{tag} class="kpi"{attrs}>{lead}<div><div class="v">{html.escape(value)}</div>'
            f'<div class="l">{html.escape(label)}</div>{sub_html}</div></{tag}>')
