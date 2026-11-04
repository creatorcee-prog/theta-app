"""2026-11-04: Theta's voice on Fish Audio. The free model first; the paid one only within the monthly cap
($0 by default); Piper on the phone when neither can speak. A fake Fish Audio stands in: no live network."""
import sys, os, json, io
sys.dont_write_bytecode = True
os.environ.update(DASHBOARD_KEY="dk", NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
os.environ.pop("FISH_AUDIO_API_KEY", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
import urllib.error


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


K = {"x-dashboard-key": "dk"}
CALLS, FAIL = [], {}
VID = "e58b0d7efca34eb38d5c4985e378abcb"


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake_urlopen(req, timeout=None):
    url = req.full_url
    CALLS.append((url, dict(req.header_items()), req.data))
    if "/v1/tts" in url:
        model = dict((k.lower(), v) for k, v in req.header_items())["model"]
        if model in FAIL:
            raise urllib.error.HTTPError(url, FAIL[model], "x", {}, io.BytesIO(json.dumps({"status": FAIL[model], "message": "nope"}).encode()))
        return Resp(b"ID3fake-mp3-" + model.encode())
    if "/model?" in url:
        return Resp(json.dumps({"total": 2, "items": [
            {"_id": VID, "title": "Calm British Man", "description": "Warm and steady", "task_count": 1200,
             "samples": [{"audio": "https://cdn.fish.audio/sample.mp3"}], "cover_image": "https://cdn.fish.audio/c.png"},
            {"_id": "bad id!", "title": "dropped"}]}).encode())
    raise AssertionError("unexpected call " + url)


h.urllib.request.urlopen = fake_urlopen

# ---- no key yet: Settings says how, Theta stays on Piper
sett = h.handle("GET", "/settings", {}, K, b"")[2].decode()
check("no key: Settings says to add FISH_AUDIO_API_KEY in Vercel", 'id="voice"' in sett and "FISH_AUDIO_API_KEY" in sett and "Piper" in sett)
check("no key: the Theta page keeps Piper", '"on": false' in h.head_script({}) and 'PIPER_VOICE = "piper:' in h._HEAD_JS)
try:
    h.fish_say("hi", VID); check("no key: saying fails clearly", False)
except h.LLMError as e:
    check("no key: saying fails clearly", "FISH_AUDIO_API_KEY" in str(e))

os.environ["FISH_AUDIO_API_KEY"] = "fk-test"
# ---- picking a voice
s, kind, out = h.handle("GET", "/api/voice/fish/voices", {"q": ["british"]}, K, b"")[:3]
d = json.loads(out)
check("the voice list: top English voices with a sample, bad ids dropped", d["ok"] and [v["id"] for v in d["voices"]] == [VID]
      and d["voices"][0]["sample"].startswith("https://"))
lst = [c for c in CALLS if "/model?" in c[0]][-1]
check("...asked for English, best first, with the key", "language=en" in lst[0] and "sort_by=score" in lst[0] and "title=british" in lst[0]
      and lst[1].get("Authorization") == "Bearer fk-test")
n = len(CALLS); h.fish_voices("british")
check("...and kept for a day", len(CALLS) == n)
check("the voice list needs the dashboard key", h.handle("GET", "/api/voice/fish/voices", {}, {}, b"")[0] == 401)
r = json.loads(h.handle("POST", "/api/voice/fish/config", {}, K, json.dumps({"voice": VID, "name": "Calm British Man"}).encode())[2])
check("picking a voice saves it", r["ok"] and h.fish_cfg()["voice"] == VID and h.fish_cfg()["name"] == "Calm British Man")
check("a bad id is refused", h.handle("POST", "/api/voice/fish/config", {}, K, json.dumps({"voice": "../x"}).encode())[0] == 400)
check("the cap starts at $0: free only", h.fish_cfg()["cap"] == 0)
check("the Theta page now speaks with it by default", f'"voice": "{VID}"' in h.head_script({})
      and 'DEFAULT_VOICE = FISH.on && FISH.voice ? "fish:" + FISH.voice : PIPER_VOICE' in h._HEAD_JS)

# ---- speaking
CALLS.clear()
s, kind, audio = h.handle("POST", "/api/voice/say", {}, K, json.dumps({"text": "Hey, it's Theta.", "voice": "fish:" + VID}).encode())[:3]
tts = [c for c in CALLS if "/v1/tts" in c[0]]
body = json.loads(tts[0][2])
check("speaks on the free model first, as MP3", s == 200 and kind == "audio/mpeg" and audio.endswith(b"s2.1-pro-free")
      and dict((k.lower(), v) for k, v in tts[0][1].items())["model"] == "s2.1-pro-free")
check("...in the picked voice, quick to start", body["reference_id"] == VID and body["format"] == "mp3" and body["latency"] == "balanced")
check("free characters are counted", h.fish_usage()["free"] == len("Hey, it's Theta.") and h.fish_usage()["paid"] == 0)

FAIL["s2.1-pro-free"] = 429
r = h.handle("POST", "/api/voice/say", {}, K, json.dumps({"text": "Busy now.", "voice": "fish:" + VID}).encode())
check("free busy, cap $0: no paid call, a clear reason (the page then uses Piper)", r[0] == 429
      and "cap $0" in json.loads(r[2])["error"] and not any("s2.1-pro" == dict((k.lower(), v) for k, v in c[1].items()).get("model") for c in CALLS if "/v1/tts" in c[0]))
h.fish_set(cap=0.0005)  # about 33 characters
r = h.handle("POST", "/api/voice/say", {}, K, json.dumps({"text": "Paid voice steps in.", "voice": "fish:" + VID}).encode())
check("free busy, within the cap: the paid model speaks", r[0] == 200 and r[2].endswith(b"s2.1-pro") and h.fish_usage()["paid"] == len("Paid voice steps in."))
check("...and its cost is tracked", abs(h.fish_usage()["cost"] - len("Paid voice steps in.") * 15 / 1e6) < 1e-9)
r = h.handle("POST", "/api/voice/say", {}, K, json.dumps({"text": "This one would go past the cap.", "voice": "fish:" + VID}).encode())
check("past the cap: no paid call", r[0] == 429 and "cap" in json.loads(r[2])["error"] and "used up" in json.loads(r[2])["error"])
FAIL.clear(); FAIL["s2.1-pro-free"] = 401
r = h.handle("POST", "/api/voice/say", {}, K, json.dumps({"text": "Bad key.", "voice": "fish:" + VID}).encode())
check("a bad key never falls through to the paid model", r[0] == 502 and "FISH_AUDIO_API_KEY" in json.loads(r[2])["error"])
FAIL.clear()
check("too long is refused", h.handle("POST", "/api/voice/say", {}, K, json.dumps({"text": "x" * 700, "voice": "fish:" + VID}).encode())[0] == 400)
check("the cap has limits", h.handle("POST", "/api/voice/fish/config", {}, K, json.dumps({"cap": 500}).encode())[0] == 400)

# ---- the page
js = h._HEAD_JS
check("Fish Audio speaks a sentence at a time, the next made while one plays", 'bySentence = local || engine === "fish"' in js)
check("when Fish Audio can't, Piper; when Piper can't, the phone's voice", "Using Piper for now." in js
      and "speakClips(said, PIPER_VOICE)" in js and ".catch(() => speakPhone(said))" in js)
sett = h.handle("GET", "/settings", {}, K, b"")[2].decode()
check("Settings: the picker, the cap and this month's use", 'id="fish-list"' in sett and 'id="fish-cap"' in sett
      and "Calm British Man" in sett and "characters free" in sett)
print("done")

# ---- keep some voices, swap the rest (2026-11-04, later)
r = json.loads(h.handle("POST", "/api/voice/fish/config", {}, K, json.dumps({"keep": [
    {"id": VID, "name": "Ethan", "sample": "https://cdn.fish.audio/a.mp3"},
    {"id": "f" * 32, "name": "Egirl", "sample": "javascript:alert(1)"}], "seeded": True, "page": 3}).encode())[2])
check("kept voices are saved, with only https samples", r["ok"] and [k["name"] for k in h.fish_cfg()["keep"]] == ["Ethan", "Egirl"]
      and h.fish_cfg()["keep"][1]["sample"] == "" and h.fish_cfg()["seeded"] and h.fish_cfg()["page"] == 3)
check("a bad kept voice is refused", h.handle("POST", "/api/voice/fish/config", {}, K, json.dumps({"keep": [{"id": "../x"}]}).encode())[0] == 400)
check("at most 12 kept", h.handle("POST", "/api/voice/fish/config", {}, K, json.dumps({"keep": [{"id": f"{i:032d}"} for i in range(13)]}).encode())[0] == 400)
sett = h.handle("GET", "/settings", {}, K, b"")[2].decode()
check("Settings: Keep and Swap, kept voices first, and the list picks up where Swap left it", 'id="fish-swap"' in sett
      and '"page": 3' in sett and "Ethan" in sett and "...keep.map(row), ...rest.map(row)" in h._FISH_JS)
check("once: Ethan and Egirl kept, the rest swapped", "(ethan|e[\\s-]?girl)" in h._FISH_JS and "seeded: true" in h._FISH_JS)
print("keep done")

# ---- samples with the effect (2026-11-04, later)
check("only Fish Audio's own https addresses are fetched for a sample", h.fish_sample_ok("https://cdn.fish.audio/a.mp3")
      and h.fish_sample_ok("https://fish.audio/x") and not h.fish_sample_ok("http://cdn.fish.audio/a.mp3")
      and not h.fish_sample_ok("https://evil.example/fish.audio") and not h.fish_sample_ok("https://fish.audio.evil.example/a")
      and not h.fish_sample_ok("https://cdn.fish.audio:8443/a") and not h.fish_sample_ok("https://169.254.169.254/"))
check("the sample route refuses anything else", h.handle("GET", "/api/voice/fish/sample", {"url": ["https://evil.example/a.mp3"]}, K, b"")[0] == 400
      and h.handle("GET", "/api/voice/fish/sample", {"url": ["https://cdn.fish.audio/a.mp3"]}, {}, b"")[0] == 401)
sett = h.handle("GET", "/settings", {}, K, b"")[2].decode()
check("Settings: the effect picker next to the voices, samples play through it", 'id="fish-fx"' in sett and 'id="fish-fx-amt"' in sett
      and "FXN.render(await sampleBlob(url)" in h._FISH_JS and "/api/voice/fish/sample?url=" in h._FISH_JS)
print("samples done")
