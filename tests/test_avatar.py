"""Theta's avatar is Urchin Pour (picked in the Avatar Lab, 2026-11-03): a 3D swarm that pours the
voice out in spikes, follows the real audio, eases into a mood Theta's reply carries, and has its
style, size, energy and mood colors in "Voice and tools". No live network."""
import sys, os, re, subprocess, tempfile, time
sys.dont_write_bytecode = True
from datetime import datetime
os.environ.update(DASHBOARD_KEY="dk", HEAD_MODE="single", NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.HEAD_MODE = "single"


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


noon = datetime.now(h.hub_tz()).replace(hour=12, minute=0).timestamp()
night = datetime.now(h.hub_tz()).replace(hour=23, minute=0).timestamp()
check("over budget: concerned", h.reply_mood("Heads up: dining is over budget.", noon) == "concerned")
check("a failed action: concerned", h.reply_mood("Done.\n✗ remind: When?", noon) == "concerned")
check("two things done: proud", h.reply_mood("All set.\n✓ Reminder set\n✓ Logged $12", noon) == "proud")
check("nice work: proud", h.reply_mood("Nice work, that's the taxes finished.", noon) == "proud")
check("happy words: happy", h.reply_mood("Haha, love that. Sounds fun.", noon) == "happy")
check("plain at noon: calm", h.reply_mood("It's 72 and sunny.", noon) == "calm")
check("plain late at night: sleepy", h.reply_mood("It's 72 and sunny.", night) == "sleepy")
h.focus_start("20 taxes")
check("during a focus session: focused", h.reply_mood("Keep going.", noon) == "focused")
h.focus_start("stop")
h._REQ.mood = "happy"
x = h.reply_extra()
check("the reply carries its mood, once", x.get("mood") == "happy" and "mood" not in h.reply_extra())

js = h._HEAD_JS.replace('__THEME__', '{"calm": "#4fd3ff"}')
check("Urchin Pour is the avatar, the classic rings a style", 'style: "urchin"' in js and "function drawUrchin" in js and "function drawRings" in js)
check("real 3D: depth-sorted, near bigger, far fogged", "pts.sort((a, b) => b[2] - a[2])" in js and "const fog" in js)
check("follows the real voice: the playing clip's loudness, never rerouted", "envelope(blob)" in js and "OfflineAudioContext" in js
      and "createMediaElementSource" not in js and "voiceEnv[Math.floor(player.currentTime * 30)]" in js)
check("moods change color and shape", all(m in js for m in ("calm", "focused", "happy", "concerned", "sleepy", "proud")) and "function moodShape" in js)
check("mood comes from Theta's latest reply, sleepy late at night", "m.mood" in js and "(h >= 22 || h < 6)" in js)
page = h.head_page({"host": "x", "x-dashboard-key": "dk"})
check("settings: style, size, energy, a color per mood, reset",
      all(x in page for x in ('id="av-style"', 'id="av-size"', 'id="av-energy"', 'data-avmood="concerned"', 'id="av-reset"')))
check("kept on this device", 'store("theta:avatar"' in js)
check("reduced motion slows it", "reduce ? 0.35 : 1" in js)
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
    f.write(js.replace("__ORPHEUS__", "[]").replace("__GEMINI__", "[]"))
check("the script parses", subprocess.run(["node", "--check", f.name], capture_output=True).returncode == 0)
# ---- the opening: assemble, greet, update only if it matters, then ask
h.head_chat = lambda *a, **k: (_ for _ in ()).throw(h.LLMError("down"))
d = h.head_hello(60)
check("back within minutes: just the question", d["text"] == "What are we working on?")
h.add_reminder("in 30 min take the meds")
d = h.head_hello(6 * 3600)
check("away hours, model down: a greeting, the update and the question", d["text"].startswith("Good ")
      and "Coming up: take the meds" in d["text"] and d["text"].endswith("What are we working on?"))
h.head_chat = lambda msgs, *a, **k: (ASKED.append(msgs[-1]["content"]), "Evening! Meds in half an hour.")[1]
ASKED = []
d = h.head_hello(6 * 3600)
check("the model writes it from the facts, and the question is always there", d["text"] == "Evening! Meds in half an hour. What are we working on?"
      and "take the meds" in ASKED[-1] and "Under 30 words" in ASKED[-1])
import json as _j
s_, ct, out = h.handle("GET", "/api/head/hello", {"away": ["60"]}, {"x-dashboard-key": "dk"}, b"")[:3]
check("the page asks /api/head/hello", s_ == 200 and _j.loads(out)["text"] == "What are we working on?")
stage = h._STAGE_JS
check("the opening scatters the dots so they fly in, on a blank stage", "TH.scatter()" in stage and 'body.classList.add("opening")' in stage
      and "body.opening .deck" in h._STAGE_CSS)
check("the greeting is spoken on the first tap (iPhone needs one), shown at once", "TH.speak(greeting)" in stage and "cap.textContent = greeting" in stage)
check("the controls hide until a tap, and go 1.5 s after", "1500" in stage and 'body.classList.add("ui-hidden")' in stage
      and 'id="imm-on"' in page and "body.immersive.ui-hidden .msgs" in h._STAGE_CSS)
check("...not while typing or a menu is open", "function busy()" in stage and ".hud-more[open]" in stage)
check("...and a scroll by the page itself doesn't count", 'addEventListener("scroll", reveal' not in stage)
# ---- themes built around Theta
check("the avatar's calm color and its space come from the theme", h.theme_stage({}) == {"calm": "#3dd6f0", "stage": "#0c0e1a"})
h.THEMES["_dim"] = {"label": "x", "about": "x", "dark": dict(h.THEMES["theta"]["dark"], accent2="#222222"), "light": h.THEMES["theta"]["light"]}
h.ui_prefs = (lambda real: (lambda headers: ("_dim",) + tuple(real(headers)[1:]) if headers.get("dim") else real(headers)))(h.ui_prefs)
check("a theme whose accent is too dark keeps Theta's cyan", h.theme_stage({"dim": "1"})["calm"] == "#4fd3ff")
del h.THEMES["_dim"]
check("the page's glow, panels and Talk follow the mood", "var(--mood" in h._DECK_CSS and "var(--mood" in h._STAGE_CSS
      and 'setProperty("--mood"' in js)
check("each theme's swatch shows Theta in its colors", 'class="globe"' in h.theme_globe("forest") and "#f2cc3d" in h.theme_globe("forest"))
# ---- the widget wears Theta's avatar and mood
w = h.widget_script("https://x.example")
check("the widget draws Urchin Pour, in the mood's color", "function urchin(size, hex)" in w and "rings(" not in w and "d.color" in w)
check("the widget data carries the mood and its color", {"mood", "color"} <= set(h.phone_widget().keys()))
# ---- the app opens on Theta; the cinematic first open; docking to the corner on every page
s_, ct, out = h.handle("GET", "/manifest.webmanifest", {}, {}, b"")[:3]
check("the app opens on Theta", _j.loads(out)["start_url"].startswith("/head"))
stage = h._STAGE_JS
check("the first open of a session is cinematic, later ones the quick assembly, from the corner the reverse move",
      "theta:booted" in stage and "cinematic()" in stage and "TH.scatter()" in stage and "theta:fromCorner" in stage and "undock" in stage)
check("cinematic: a spark, streams spiraling in, a shockwave, the name", "the spark" in stage and "the streams" in stage
      and "the shockwave" in stage and 'id="head-word"' in page)
check("reduced motion skips the cinematic", "!booted && !reduce" in stage)
check("the stage is the Settings background: no fill of its own", "transparent 70%)!important" in h._STAGE_CSS)
check("on a light background the dots draw darker instead of adding light", "lightBg" in js and 'lightBg ? "source-over" : "lighter"' in js)
check("docks to the corner once you've talked and Theta pulls something up", "theta:panels" in stage and "if (e.detail.count && talked) dock()" in stage
      and "panelsEvent(m.panels.length)" in h._DECK_JS)
check("a smooth move both ways (FLIP)", "function flip(change, ms)" in stage and "cubic-bezier" in stage)
check("leaving for another page: it shrinks into the corner first", "location.href = u.href" in stage)
check("the corner is the same spot as on other pages", "top:calc(env(safe-area-inset-top,0px) + 10px);right:calc(env(safe-area-inset-right,0px) + 12px)"
      in h._STAGE_CSS and "top:calc(env(safe-area-inset-top,0px) + 10px);right:calc(env(safe-area-inset-right,0px) + 12px)" in h._UI_CSS)
other = h.handle("GET", "/settings", {}, {"x-dashboard-key": "dk"}, b"")[2].decode()
check("Theta sits in the corner of every other page, and taps back to the Theta page", 'class="theta-mini" href="/head"' in other
      and 'class="theta-mini"' not in h.head_page({"host": "x", "x-dashboard-key": "dk"}) and "theta:fromCorner" in h._UI_JS)
check("the corner Theta wears its last mood", "theta:moodColor" in h._UI_JS and 'store("theta:moodColor"' in js)
# ---- fixes from the phone (2026-11-04)
home = h.handle("GET", "/", {}, {"x-dashboard-key": "dk"}, b"")[2].decode()
check("opened from the Home Screen icon onto Home, the app goes to Theta (an icon added before still opens /)",
      'location.pathname==="/"&&(navigator.standalone' in home and 'location.replace("/head"' in home and "theta:launched" in home)
check("pages with Theta in the corner leave room in their header", 'has-mini' in home and "body.has-mini header.top{padding-right:60px}" in h._UI_CSS)
check("the Needs attention card keeps its distance from the cards below", ".attention{border-color:color-mix(in srgb,var(--warn) 55%,var(--border));margin:0 0 16px}" in h._UI_CSS)
check("while hidden, only a tap where the text box sits brings the controls back", "function inBoxZone(e)" in stage
      and "inBoxZone(e)) reveal()" in stage and '["keydown", "input"].forEach' in stage)
check("tapping Theta isn't typing: focus only counts in a text field", "/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) reveal()" in stage)
check("voice effects: a picker and a strength, in Voice and tools", 'id="head-fx"' in page and 'id="head-fx-amt"' in page
      and all(f'value="{k}"' in page for k in h.VOICE_FX))
ui = h._UI_JS
check("effects are rendered offline into a new clip, so playback isn't rerouted", "window.thetaFx" in ui
      and "startRendering()" in ui and "createMediaElementSource" not in ui + js and ".then(voiceFx)" in js and "thetaFx.render(" in js)
check("an effect that fails plays the plain voice", "catch (e) { return blob; }" in ui)
check("never clips", "0.98 / peak" in ui)
check("the effect waits for the page script, which loads after", 'addEventListener("DOMContentLoaded", fxInit)' in js)
print("done")
