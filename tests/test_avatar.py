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

js = h._HEAD_JS
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
print("done")
