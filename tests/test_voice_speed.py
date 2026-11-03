"""Theta's voice starts sooner (2026-11-03): the on-phone voice is warmed up
when the Head page opens, the engine loads once even when asked twice, the
first words go first, and the page shows how long the reply and the voice
took. Checks the page's script; the browser run is in the PR notes."""
import sys, os, re, subprocess, tempfile
sys.dont_write_bytecode = True
os.environ.update(DASHBOARD_KEY="dk", NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


js = h._HEAD_JS
page = h.head_page({"host": "x", "x-dashboard-key": "dk"})
html_ = page[2].decode() if isinstance(page, tuple) else str(page)
check("warmed up when the page opens", "async function warmVoice()" in js and re.search(r"setTimeout\(.*warmVoice\(\)\), 600\)", js))
check("warmed again when you pick another voice", "setTimeout(warmVoice, 50)" in js)
check("and when you send, while Theta thinks", "tSent = performance.now(); tReply = 0; warmVoice();" in js)
check("the engine loads once: a shared promise", "piperMod = import(PIPER_JS)" in js and "await (await piperMod).predict" in js
      and "kokoroModel = import(KOKORO_JS).then(" in js)
check("a failed load can be tried again", "piperMod.catch(() => { piperMod = null; })" in js and "kokoroModel.catch(() => { kokoroModel = null; })" in js)
check("first words first: split at the first comma", 'parts[0].indexOf(", ")' in js and "parts.splice(0, 1," in js)
check("timings on the page", 'id="head-timing"' in html_ and "Reply ${" in js and "voice ${" in js)
check("voice timing for both on-phone and phone voices", js.count("heardVoice()") >= 2)
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
    f.write(js.replace("__ORPHEUS__", "[]").replace("__GEMINI__", "[]"))
check("the script parses", subprocess.run(["node", "--check", f.name], capture_output=True).returncode == 0)
print("done")
