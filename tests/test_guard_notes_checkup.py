"""Typing guard, agents' own notes, and the checkup (Diagnostics → Checkup,
/checkup). No live network: models, pushes and wiring are stubbed."""
import sys, json, os, io, time
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
DB = {}
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self): self._send(404, {})
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n)) if n else {}
        if self.path.startswith("/redis"):
            op, k, a = body[0], body[1], body[2:]
            if op == "INCR": DB[k] = DB.get(k, 0) + 1; r = DB[k]
            elif op == "LPUSH": DB.setdefault(k, []).insert(0, a[0]); r = 1
            elif op == "LTRIM": DB[k] = DB.get(k, [])[int(a[0]):int(a[1]) + 1]; r = "OK"
            elif op == "LRANGE":
                l = DB.get(k, []); e = int(a[1]); r = l[int(a[0]):(None if e == -1 else e + 1)]
            elif op == "HSET":
                h_ = DB.setdefault(k, {}); r = sum(1 for x in a[::2] if x not in h_); h_.update(zip(a[::2], a[1::2]))
            elif op == "HGET": r = DB.get(k, {}).get(a[0])
            elif op == "HMGET": r = [DB.get(k, {}).get(x) for x in a]
            elif op == "HGETALL": r = [x for kv in DB.get(k, {}).items() for x in kv]
            elif op == "SMEMBERS": r = []
            else: r = None
            return self._send(200, {"result": r})
        self._send(404, {})
srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk-long-enough-key", NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="t")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
from wsgiref.util import setup_testing_defaults
PUSHES = []
h.refresh_windows = lambda deadline=None: ""
h.wiring = lambda: [{"name": "Mistral", "model": "m", "state": "ok", "note": "connected"},
                    {"name": "Lenz's TMDB", "model": "TMDB trending", "state": "off", "note": "Not linked: set TMDB_API_KEY"}]
K = {"x-dashboard-key": "dk-long-enough-key"}
def call(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s)))
    return int(got["s"][:3]), json.loads(out) if out[:1] == b"{" else out
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
print("mode:", mode)

# ---- typing guard
# pushes past the guard are counted here instead of sent
real_notify = h.notify
def notify_spy(title, body, url="/"):
    if not h._urgent(title, body, url) and h.user_typing():
        return real_notify(title, body, url)  # the real guard holds it
    PUSHES.append((title, body, url)); return 1
h.notify = notify_spy

check("the guard is on by default (2 minutes)", h.TYPING_GUARD_SECONDS == 120)
check("/api/typing needs the dashboard key", call("POST", "/api/typing", body={})[0] == 401)
check("not typing until the composer says so", not h.user_typing())
s, d = call("POST", "/api/typing", headers=K, body={})
check("/api/typing marks you as typing", s == 200 and d["ok"] and h.user_typing())

h.ROUND_JOBS = {"glass": lambda ctx: (h.store().add_chat("glass", "Heads up: Dining is at 92%.", channel="money"), "posted")[1]}
h.llm_chat = lambda tier, messages, max_tokens=None, **kw: "Dining is at 92% (Glass)."
h.desk_chat = lambda msgs, *a, **k: "Dining is at 92% (Glass)."
def mistral_posts(): return [m for m in h.allchat_view(200) if m["from"] == "mistral" and "Dining" in m["text"]]  # the tick may post a digest too
before = len(mistral_posts())
h.run_round()
check("a scheduled round while you type holds its update", len(mistral_posts()) == before and len(h.held()["posts"]) == 1)
h.notify("Lenz", "New upload")
check("a non-urgent push waits too", not PUSHES and h.held()["pushes"][0]["title"] == "Lenz")
h.notify("Remi", "Reminder: call Mom", h.REMINDER_URL)
h.notify("QWERTY", "New sign-in from Chrome", "/settings#devices")
check("reminders and security alerts still go out at once", [p[0] for p in PUSHES] == ["Remi", "QWERTY"])
PUSHES.clear()
check("nothing is released while you're still typing", h.release_held() is None and h.held()["posts"])
h.run_round(force=True)
check("a round you ask for (/round) posts now", len(mistral_posts()) == before + 1)
# you stop typing: the next tick posts what was held, with one push
h.store().set_meta("user:typing", str(time.time() - 200))
check("the guard ends 2 minutes after the last keystroke", not h.user_typing())
h.run_tick()
check("the next tick posts the held update", len(mistral_posts()) == before + 2 and not h.held()["posts"])
check("...and sends the held push", ("Lenz", "New upload", "/") in PUSHES)
check("held items go out once", h.release_held() is None)
h.TYPING_GUARD_SECONDS = 0
call("POST", "/api/typing", headers=K, body={})
check("TYPING_GUARD_SECONDS=0 turns it off", not h.user_typing())
h.TYPING_GUARD_SECONDS = 120
h.store().set_meta("user:typing", "0")
chat_js = call("GET", "/chat.js")[1].decode()
check("the composer pings /api/typing, at most every 30 s", 'fetch("/api/typing"' in chat_js and "typedAt < 30000" in chat_js)

# ---- agents' own notes
check("every agent can keep its own notes", "self_note" in h.TOOLS and h.TOOLS["self_note"][2] is None)
check("...and it's in their tools list", "ACTION: self_note |" in h.tools_prompt("glass"))
out = h.run_actions("glass", "Got it.\nACTION: self_note | round totals to the dollar")
check("self_note saves and says so", "✓ Noted for myself: round totals to the dollar" in out)
h.run_actions("glass", "ACTION: self_note | Round totals to the dollar")
check("the same note isn't saved twice", len(h.seat_notes("glass")) == 1)
check("the note is in that agent's prompt", "Your own notes from past chats" in h.system_prompt("glass")
      and "- round totals to the dollar" in h.system_prompt("glass").lower())
check("...and not in anyone else's", "round totals to the dollar" not in h.system_prompt("remi").lower())
for i in range(h.SEAT_NOTES_MAX + 2):
    h.run_actions("remi", f"ACTION: self_note | lesson {i}")
check("only the newest notes are kept", len(h.seat_notes("remi")) == h.SEAT_NOTES_MAX and h.seat_notes("remi")[-1]["text"] == f"lesson {h.SEAT_NOTES_MAX + 1}")
out = h.run_actions("glass", "ACTION: forget | dollar")
check("forget drops the agent's own matching note", "1 of my own note" in out and not h.seat_notes("glass"))
h.run_actions("glass", "ACTION: self_note | user hates emojis")
page = call("GET", "/settings", "key=dk-long-enough-key")[1].decode()
check("Settings shows each agent's own notes", "Agents’ own notes" in page and "user hates emojis" in page)
nid = h.seat_notes("glass")[0]["id"]
check("removing one needs the key", call("POST", "/api/seat/remove", body={"id": nid})[0] == 401)
s, d = call("POST", "/api/seat/remove", headers=K, body={"id": nid})
check("Settings can remove one", s == 200 and not h.seat_notes("glass"))
check("the agent notes survive in the store (not just this process)", h.store().get_meta("seat:remi") is not None)

# ---- checkup
check("/api/doctor needs the key", call("GET", "/api/doctor")[0] == 401)
s, d = call("GET", "/api/doctor", "key=dk-long-enough-key")
names = [c["name"] for c in d["checks"]]
check("checkup lists storage, tick, rounds, models, search and the bridge", s == 200 and {"Storage", "5-minute tick", "Web search", "Mistral (m)"} <= set(names))
order = [c["state"] for c in d["checks"]]
check("worst first", order == sorted(order, key={"bad": 0, "warn": 1, "ok": 2}.get))
st = {c["name"]: c for c in d["checks"]}
if mode == "memory":
    check("memory-only storage is flagged as broken", st["Storage"]["state"] == "bad")
else:
    check("Upstash storage passes", st["Storage"]["state"] == "ok")
check("the tick that just ran passes", st["5-minute tick"]["state"] == "ok")
check("a model that isn't set up is a warning, with a fix link", st["Lenz's TMDB (TMDB trending)"]["state"] == "warn"
      and st["Lenz's TMDB (TMDB trending)"]["fix"] == "/diagnostics#wiring")
h.store().set_meta("round:failures", json.dumps({"glass": "groq returned 503"}))
d = call("GET", "/api/doctor", "key=dk-long-enough-key")[1]
check("a failing round job shows up", any(c["name"] == "Glass's round" and c["state"] == "bad" and "503" in c["detail"] for c in d["checks"]))
check("the summary counts what's wrong", "broken" in d["summary"])
diag = call("GET", "/diagnostics", "key=dk-long-enough-key")[1].decode()
check("Diagnostics has the Run checkup button", 'id="checkup-run"' in diag and 'fetch("/api/doctor"' in diag)
r = h.run_command("/checkup")
dev = [m for m in h.allchat_view(200, channel="dev") if m["from"] == "qwerty"]
check("/checkup: QWERTY posts what's wrong in #dev", "#dev" in r and dev and dev[-1]["text"].startswith("Checkup:")
      and "Glass's round" in dev[-1]["text"])
check("/checkup is in the / menu", any(c["name"] == "checkup" for c in h.COMMANDS))
print("ALL PASS")
