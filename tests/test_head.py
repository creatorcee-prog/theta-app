"""(The ACTION-line way, the fallback when native tool calling is off or
refused: test_head_native.py covers native tool calling.)
Single head (Stage 8.2): with HEAD_MODE=single, Theta alone answers every
message on DeepSeek, reads lookups before answering, runs actions once, and
the crew is only paused (HEAD_MODE=crew brings it back). A fake
OpenAI-format server stands in for DeepSeek and Gemini; no live network."""
import sys, json, os, io, threading
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
BODIES, SPEECH, GSPEECH = [], [], []
CALLS, SCRIPT, STATE = [], [], {"deepseek_down": False, "groq_down": False}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self): self._send(200, {"data": [{"id": "deepseek-flash"}]})
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n))
        who = self.path.split("/")[1]
        if self.path.startswith("/gtts/"):  # Gemini's voice: the Interactions API isn't there, generateContent is
            GSPEECH.append((self.path, body))
            if self.path.endswith("/interactions"):
                return self._send(404, {"error": {"message": "not found"}})
            pcm = b"\x01\x00" * 2400
            return self._send(200, {"candidates": [{"content": {"parts": [{"inlineData": {
                "mimeType": "audio/L16;codec=pcm;rate=24000", "data": __import__("base64").b64encode(pcm).decode()}}]}}]})
        if self.path.endswith("/audio/speech"):  # Groq's Orpheus voice
            SPEECH.append(body)
            if STATE.get("voice") == "out":
                return self._send(429, {"error": {"message": "Rate limit reached for requests per day"}})
            if STATE.get("voice") == "terms":
                return self._send(400, {"error": {"message": "The model requires terms acceptance"}})
            b = b"RIFF$\x00\x00\x00WAVEfmt "; self.send_response(200); self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        CALLS.append((who, body["model"], body["messages"]))
        BODIES.append(body)
        if (who == "deepseek" and STATE["deepseek_down"]) or (who == "groq" and STATE["groq_down"]):
            return self._send(503, {"error": {"message": "busy"}})
        text = SCRIPT.pop(0) if SCRIPT else "Hey, I'm here."
        self._send(200, {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 50, "completion_tokens": 5}})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ.update(HEAD_NATIVE_TOOLS="off", DASHBOARD_KEY="dk", GROQ_API_KEY="qk", GEMINI_API_KEY="gk", ANTHROPIC_API_KEY="", DEEPSEEK_API_KEY="dsk",
                  GLASS_BUDGETS="Groceries:600,Dining:200", NEWS_FEEDS="http://127.0.0.1:1/x.xml",
                  ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h  # memory store in both modes: nothing here depends on Redis
from wsgiref.util import setup_testing_defaults
h.PROVIDERS["deepseek"] = (base + "/deepseek/chat/completions", "DEEPSEEK_API_KEY")
h.PROVIDERS["gemini"] = (base + "/gemini/chat/completions", "GEMINI_API_KEY")
h.PROVIDERS["groq"] = (base + "/groq/chat/completions", "GROQ_API_KEY")
h.LLM_RETRY_DELAY = 0
h.notify = lambda *a, **k: 0
h.tmdb_trending = lambda: []
h.refresh_windows = lambda deadline=None: ""


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


def post(text, **extra):
    raw = json.dumps({"text": text, **extra}).encode()
    env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/allchat", "QUERY_STRING": "", "CONTENT_LENGTH": str(len(raw)),
           "wsgi.input": io.BytesIO(raw), "HTTP_X_DASHBOARD_KEY": "dk"}
    setup_testing_defaults(env); got = {}
    out = json.loads(b"".join(h.app(env, lambda s, hd: got.update(s=s))))
    return out


def last_reply():
    return [m for m in h.allchat_view(200) if m.get("kind") != "event" and m["from"] != "you"][-1]


print("mode:", mode)
check("the crew stays by default (HEAD_MODE=crew)", h.HEAD_MODE == "crew" and not h.head_on())
h.HEAD_MODE = "single"
check("HEAD_MODE is a setting QWERTY can propose", "HEAD_MODE" in h.SETTABLE)

# ---- Theta answers, on DeepSeek
CALLS.clear(); SCRIPT[:] = ["Hey! Doing well. What's up?"]
d = post("hey, how's it going?")
r = last_reply()
check("Theta answers, on DeepSeek", d["ok"] and r["from"] == "theta" and r["text"] == "Hey! Doing well. What's up?"
      and CALLS[0][0] == "deepseek" and CALLS[0][1] == "deepseek-flash")
sysmsg = CALLS[0][2][0]["content"]
check("...with the soul, the handle-everything role and the crew's tools", "# Theta's soul" in sysmsg
      and "You're the only one the user talks to now" in sysmsg and "ACTION: spend |" in sysmsg
      and "ACTION: calendar |" in sysmsg and "ACTION: propose |" in sysmsg and "ACTION: ask |" not in sysmsg)
check("...and not told it's a stand-in for Claude", "isn't answering right now, so you run on" not in sysmsg)
SCRIPT[:] = ["Glass would've said it: $0 so far on dining."]
post("@glass how much have I spent on dining?")
check("a leading @agent is just text: Theta still answers", last_reply()["from"] == "theta")

# ---- instant commands still run at once, as Theta
CALLS.clear()
post("$42 groceries")
r = last_reply()
check("$42 groceries logs at once, with no model call, said by Theta", r["from"] == "theta" and not CALLS
      and any(e["amount"] == 42 for e in h.store().list_expenses(h.datetime.now(h.hub_tz()).strftime("%Y-%m"))))

# ---- lookups come back before Theta answers; actions run once, from the final answer
CALLS.clear()
SCRIPT[:] = ["Let me check.\nACTION: budget | this month\nACTION: remind | 6pm pay rent",
             "You've spent $42 on groceries, $558 left. Rent reminder's set for 6.\nACTION: remind | 6pm pay rent"]
before = len(h.reminders())
post("how's my grocery budget? and remind me at 6pm to pay rent")
r = last_reply()
check("the lookup ran and its result went back to Theta", len(CALLS) == 2
      and "What your lookups found" in CALLS[1][2][-1]["content"] and "Groceries: $42.00 of $600" in CALLS[1][2][-1]["content"])
check("...the answer comes from it", r["text"].startswith("You've spent $42 on groceries"))
check("...and the reminder was set once, from the final answer", len(h.reminders()) == before + 1
      and "✓ Reminder set" in r["text"])
CALLS.clear()
SCRIPT[:] = ["ACTION: calendar | week"] * 5
post("what's on my calendar this week?")
check("lookups stop after HEAD_STEPS rounds, and it says it couldn't finish", len(CALLS) == h.HEAD_STEPS + 1
      and "couldn't pull an answer together" in last_reply()["text"])
SCRIPT[:] = ["SEARCH: Broncos score last night", "The Broncos won 24-17."]
h.TOOLS["web_search"] = ("web_search | <query>", lambda a, ag: "Results: Broncos 24, Raiders 17 (espn.com)", None)
CALLS.clear()
post("who won the Broncos game last night?")
check("an old-style SEARCH: line becomes a web_search lookup", len(CALLS) == 2 and "Broncos 24, Raiders 17" in CALLS[1][2][-1]["content"]
      and last_reply()["text"] == "The Broncos won 24-17.")

# ---- propose works for Theta (it still waits for Approve)
SCRIPT[:] = ["I can switch the crew back on for you.\nACTION: propose | HEAD_MODE = crew"]
post("bring the crew back")
r = last_reply()
check("Theta can propose a setting, with Approve / Decline", r["from"] == "theta" and r.get("buttons")
      and "Nothing changes until you tap Approve" in r["text"])

# ---- DeepSeek down: Gemini answers, no error
STATE["deepseek_down"] = True; CALLS.clear(); SCRIPT[:] = ["Still here (on the backup)."]
post("you there?")
check("DeepSeek down: Groq (fast, free) answers instead", last_reply()["text"] == "Still here (on the backup)."
      and [c[0] for c in CALLS] == ["deepseek", "deepseek", "groq"])
STATE["groq_down"] = True; CALLS.clear(); SCRIPT[:] = ["Still here (last resort)."]
post("you there?")
check("...and Gemini only when Groq is down too", last_reply()["text"] == "Still here (last resort)."
      and [c[0] for c in CALLS][-1] == "gemini" and "groq" in [c[0] for c in CALLS])
STATE["deepseek_down"] = STATE["groq_down"] = False

# ---- spoken answers are short
CALLS.clear(); BODIES.clear(); SCRIPT[:] = ["You're on track. Want the details?"]
post("how's my budget looking?", spoken=True)
ask = CALLS[0][2][-1]["content"]
check("the Head page's spoken flag asks for 1-2 sentences, no lists, an offer of details",
      "read aloud" in ask and "1 or 2 short sentences" in ask and "Want the details?" in ask and BODIES[0]["max_tokens"] == 350)
CALLS.clear(); BODIES.clear()
post("how's my budget looking?")
check("typed chat: short too, but not the spoken rule", "read aloud" not in CALLS[0][2][-1]["content"]
      and "2 to 4 sentences" in CALLS[0][2][-1]["content"] and BODIES[0]["max_tokens"] == 900)
post("hey", spoken="yes")
check("only a real true turns on spoken mode", "read aloud" not in CALLS[-1][2][-1]["content"])

# ---- rounds post as Theta
CALLS.clear(); SCRIPT[:] = ["Heads up: dining's at 92%."]
h.round_summary([{"from": "glass", "text": "Dining is at 92% of its budget."}])
r = last_reply()
check("the round update is Theta's own, on the head's model", r["from"] == "theta" and r["text"] == "Heads up: dining's at 92%."
      and CALLS[0][0] == "deepseek" and "don't name the crew" in CALLS[0][2][0]["content"])

# ---- the Head page (8.3)
def get(path, qs=""):
    env = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO()}
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s)))
    return int(got["s"][:3]), out.decode()
s, page = get("/head")
check("the Head page needs the key like every page", s == 401)
s, page = get("/head", "key=dk")
check("the Head page: the Rings avatar, a Talk button, the chat's own composer (it's the chat too), the voice options",
      s == 200 and 'id="head-av"' in page and 'id="head-talk"' in page and 'id="chat-msg"' in page and 'id="msgs"' in page
      and 'id="head-voice"' in page and "webkitSpeechRecognition" in page and "speechSynthesis" in page)
check("...it talks through /api/allchat, so it's in the chat history too", 'fetch("/api/allchat"' in page)
check("...and says the reply will be spoken when the voice is on", "spoken: !!voiceOn.checked" in page)
check("...and Theta is a tab in the main navigation", 'href="/head"' in get("/", "key=dk")[1] and '<span>Theta</span>' in page)

# ---- Theta's check-ins (8.5)
check("every push is Theta's, without the crew's lead-in", h.head_push("Mistral", "Glass: Heads up: dining's at 92%.")
      == ("Theta", "Heads up: dining's at 92%."))
check("...a body that isn't an agent's lead-in is left alone", h.head_push("Lenz", "Out today: Dune 3") == ("Theta", "Out today: Dune 3"))
PUSHES = []
h.notify = lambda title, body, url="/": PUSHES.append((title, body, url)) or 1
h.store().set_meta("round:mistral:digest_day", "")
CALLS.clear(); SCRIPT[:] = ["Morning! Light day: just the dentist at 3, and your budget's fine."]
h.send_digest()
r = last_reply()
check("the morning digest is Theta's short brief, from the digest's facts", r["from"] == "theta"
      and r["text"] == "Morning! Light day: just the dentist at 3, and your budget's fine."
      and "Here's today" in CALLS[0][2][-1]["content"] and "2 or 3 short sentences" in CALLS[0][2][-1]["content"])
check("...pushed, opening the Head page to hear it", PUSHES and PUSHES[-1][0] == "Theta" and PUSHES[-1][2] == "/head?play=latest")
check("...and once a day", h.send_digest() is False)
s_, page = get("/head", "key=dk&play=latest")
check("the Head page has a Hear it button for a new message or a tapped push", 'id="head-hear"' in page
      and 'get("play") === "latest"' in page and 'store("theta:heard"' in page)

# ---- Theta's voice: Orpheus on Groq (8.4b)
def say(body, key="dk"):
    raw = json.dumps(body).encode()
    env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/voice/say", "QUERY_STRING": "", "CONTENT_LENGTH": str(len(raw)),
           "wsgi.input": io.BytesIO(raw), "HTTP_X_DASHBOARD_KEY": key}
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s, h=dict(hd))))
    return int(got["s"][:3]), got["h"].get("Content-Type"), out
check("the voice needs the key", say({"text": "hi", "voice": "troy"}, key="nope")[0] == 401)
s_, ct, out = say({"text": "Hey, it's Theta.", "voice": "troy"})
check("Theta's voice: WAV from Groq's Orpheus, with the hub's Groq key", s_ == 200 and ct == "audio/wav" and out.startswith(b"RIFF")
      and SPEECH[-1] == {"model": "canopylabs/orpheus-v1-english", "input": "Hey, it's Theta.", "voice": "troy", "response_format": "wav"})
check("more than Groq's free 200 characters a request is refused (the page sends it in pieces)",
      say({"text": "x" * 201, "voice": "troy"})[0] == 400)
check("an unknown voice is refused", say({"text": "hi", "voice": "hal9000"})[0] == 400)
STATE["voice"] = "out"
s_, ct, out = say({"text": "hi", "voice": "troy"})
check("out of free uses: a 429 the page falls back on, saying why", s_ == 429 and b"out of free uses" in out)
STATE["voice"] = "terms"
s_, ct, out = say({"text": "hi", "voice": "troy"})
check("model terms not accepted yet: says where to accept them", s_ == 502 and b"accept the Orpheus model" in out)
STATE["voice"] = None
h._GEMINI_BASE = base + "/gtts"
s_, ct, out = say({"text": "Morning! Light day today.", "voice": "gemini:Charon"})
check("Gemini's voice: tries the Interactions API, falls back to generateContent, wraps its PCM as WAV",
      s_ == 200 and ct == "audio/wav" and out[:4] == b"RIFF" and out[8:12] == b"WAVE" and len(out) == 44 + 4800
      and [p for p, _ in GSPEECH] == ["/gtts/interactions", "/gtts/models/gemini-3.8-flash-tts:generateContent"]
      and GSPEECH[-1][1]["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Charon")
check("...an unknown Gemini voice is refused", say({"text": "hi", "voice": "gemini:HAL"})[0] == 400)
check("...and 'orpheus:troy' works like 'troy'", say({"text": "hi", "voice": "orpheus:troy"})[0] == 200)
s_, page = get("/head", "key=dk")
check("the picker offers Gemini, Piper and Kokoro too, the on-phone ones loaded from jsdelivr",
      '"Charon"' in page and "piper:" in page and "kokoro:" in page and "vits-web@1.0.3" in page and "kokoro-js@1.2.1" in page)
check("Theta's voice is Piper's Northern English man until a Fish Audio voice is picked; Gemini, Kokoro and the phone's stay to pick from",
      'id="head-test"' in page and 'PIPER_VOICE = "piper:en_GB-northern_english_male-medium"' in page
      and 'DEFAULT_VOICE = FISH.on && FISH.voice ? "fish:" + FISH.voice : PIPER_VOICE' in page
      and 'group("Orpheus' not in page and "Using your phone's voice for now" in page and 'fetch("/api/voice/say"' in page)

# ---- the switch back
h.HEAD_MODE = "crew"
h.desk_replies = lambda thread: ([("mistral", "Mistral here.", {})], {})
post("hello?")
check("HEAD_MODE=crew: the crew's front desk answers again", last_reply()["from"] == "mistral")
print("ALL PASS")
