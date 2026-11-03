"""(Head page = chat, Jarvis panels, Theta's own buttons) Native tool calling for the single head (2026-11-03): Theta gets its tools
as real function tools, sees every result (failures too) and keeps going for
several rounds; actions show as receipts; a model that refuses tools falls
back to the ACTION-line way; every call carries the writing rule. A fake
OpenAI-format server scripts the model's turns; no live network."""
import sys, json, os, io, threading
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
BODIES, SCRIPT, STATE = [], [], {"refuse_tools": False}


def call_(name, arg, cid):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps({"input": arg})}}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        BODIES.append((self.path.split("/")[1], body))
        if STATE["refuse_tools"] and body.get("tools"):
            return self._send(400, {"error": {"message": "tools are not supported by this model"}})
        step = SCRIPT.pop(0) if SCRIPT else "Okay."
        msg = {"content": step, "role": "assistant"} if isinstance(step, str) else {"content": step.get("text"), "role": "assistant", "tool_calls": step["calls"]}
        self._send(200, {"choices": [{"message": msg}], "usage": {"prompt_tokens": 50, "completion_tokens": 5}})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ.update(DASHBOARD_KEY="dk", GROQ_API_KEY="qk", GEMINI_API_KEY="gk", ANTHROPIC_API_KEY="", DEEPSEEK_API_KEY="dsk",
                  GLASS_BUDGETS="Groceries:600", NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
os.environ.pop("HEAD_NATIVE_TOOLS", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
from wsgiref.util import setup_testing_defaults
for p in ("deepseek", "gemini", "groq"):
    h.PROVIDERS[p] = (f"{base}/{p}/chat/completions", h.PROVIDERS[p][1])
h.LLM_RETRY_DELAY = 0
h.notify = lambda *a, **k: 0
h.tmdb_trending = lambda: []
h.refresh_windows = lambda deadline=None: ""
h.HEAD_MODE = "single"


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


def post(text):
    raw = json.dumps({"text": text}).encode()
    env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/allchat", "QUERY_STRING": "", "CONTENT_LENGTH": str(len(raw)),
           "wsgi.input": io.BytesIO(raw), "HTTP_X_DASHBOARD_KEY": "dk"}
    setup_testing_defaults(env)
    return json.loads(b"".join(h.app(env, lambda s, hd: None)))


def last_reply():
    return [m for m in h.allchat_view(200) if m.get("kind") != "event" and m["from"] != "you"][-1]


K = {"x-dashboard-key": "dk"}


def call(method, path, body=None):
    s, ct, out = h.handle(method, path, {}, K, json.dumps(body or {}).encode())[:3]
    return s, (json.loads(out) if ct.startswith("application/json") else out.decode() if isinstance(out, bytes) else out)


# ---- the bug: Theta's own Approve / Decline said "That button is gone"
pid = h.propose_to_user({"kind": "dream", "idea": "Call the bank at 9", "summary": "Dream: call the bank"},
                        "An idea from last night:\nCall the bank at 9\nKeep it?", labels=("Keep", "No"))
m = [x for x in h.store().list_chat(h.ALLCHAT_KEEP) if x.get("buttons")][-1]
s, d = call("POST", "/api/chat/press", {"msg": m["id"], "id": f"qp:{pid}:no"})
check("Theta's own buttons work now", s == 200 and any("not that one" in x["text"] for x in d["messages"]))
check("...and the answer is Theta's", d["messages"][-1]["from"] == "theta")
s, d = call("POST", "/api/chat/press", {"msg": m["id"], "id": f"qp:{pid}:no"})
check("...once", s == 409)
pid2 = h.propose_to_user({"kind": "memory_add", "line": "x", "summary": "Remember: x"}, "Worth remembering?\n- x")
m2 = [x for x in h.store().list_chat(h.ALLCHAT_KEEP) if x.get("buttons")][-1]
h.apply_memory_proposal = lambda p: (_ for _ in ()).throw(ValueError("the vault is busy"))
s, d = call("POST", "/api/chat/press", {"msg": m2["id"], "id": f"qp:{pid2}:yes"})
again = next(x for x in d["messages"] if x["id"] == m2["id"])
check("a failed Approve brings its buttons back, to try again", s == 200 and again.get("buttons"))
s, d = call("POST", "/api/chat/press", {"msg": m2["id"], "id": "not-a-button"})
check("a made-up button is still refused", s == 400)

# ---- panels ride on Theta's reply
h.glass_log_reply((70.0, "dining", "dinner"))
SCRIPT[:] = [{"text": "", "calls": [call_("budget", "this month", "p1"), call_("remind", "6pm pay rent", "p2"),
                                    call_("directions", "Costco", "p3")]}, "Dining's at $70. Rent's set for 6."]
post("how's my money, remind me about rent at 6, and get me to costco")
r = [x for x in h.allchat_view(200) if x["from"] == "theta" and x.get("kind") != "event"][-1]
kinds = [p["kind"] for p in r.get("panels") or []]
check("the reply carries what it pulled up, as panels", kinds == ["budget", "reminders", "map"])
bud = r["panels"][0]
check("a panel is built from real data, not the model's words", bud["total"] >= 70 and any(x["name"].lower() == "dining" and x["spent"] == 70 for x in bud["rows"]))
check("the map panel has the Apple Maps link", r["panels"][2]["url"].startswith("https://maps.apple.com/?daddr=Costco"))
SCRIPT[:] = ["Just chatting."]
post("thanks!")
r2 = [x for x in h.allchat_view(200) if x["from"] == "theta" and x.get("kind") != "event"][-1]
check("a reply that pulled nothing up has no panels", not r2.get("panels"))
check("a failed tool pulls nothing up", (h._REQ.__setattr__("panels", []) or True) and (h.note_panel("budget", "", False, "") or True) and h._REQ.panels == [])
check("weather is a lookup Theta has", "weather" in h.head_tools() and "weather" in h.HEAD_LOOKUPS)

# ---- one page: the Head page is the chat
s, page = call("GET", "/head")
check("the Head page is the chat: rings, Talk, panel deck, the thread and its composer",
      all(x in page for x in ('id="head-av"', 'id="head-talk"', 'id="deck"', 'id="msgs"', 'id="chat-msg"', "/chat.js")))
check("no second composer (the mini bar)", '<div class="minibar">' not in page)
check("it says who you're talking to", 'placeholder="Talk or type to Theta"' in page)
s, chat = call("GET", "/chat")
check("/chat is the same page in single-head mode", 'id="deck"' in chat and 'id="head-talk"' in chat)
h.HEAD_MODE = "crew"
s, chat = call("GET", "/chat")
check("...and the plain chat with the crew on", 'id="deck"' not in chat and 'id="msgs"' in chat)
h.HEAD_MODE = "single"
js = h._CHAT_JS
check("the chat tells the Head page about the thread", "window.thetaChat" in js and js.count("announce()") >= 4)
check("voice replies land in the thread", "window.thetaChat.take(d.messages)" in h._HEAD_JS)
check("cards are never read aloud", "replace(/```[\\s\\S]*?```/g" in h._HEAD_JS)
check('"close the panels" works without asking Theta', "theta:clear-panels" in h._HEAD_JS and "theta:clear-panels" in h._DECK_JS)
check("spoken answers stay short and can add a card", "shows on their screen as a panel" in h.HEAD_SPOKEN_RULE
      and "ONE card" in h.HEAD_SPOKEN_RULE)
print("done")
