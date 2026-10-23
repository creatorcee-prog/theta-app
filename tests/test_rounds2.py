import sys, json, os, time
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
h.notify = lambda *a, **k: 0
h.refresh_windows = lambda deadline=None: ""
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
print("mode:", mode)

# the crew's round jobs, as they'd post
def job(agent, text, **kw):
    def run(ctx):
        h.store().add_chat(agent, text, channel=h.home_channel(agent), **kw)
        return f"posted ({agent})"
    return run
h.ROUND_JOBS = {
    "remi": job("remi", "Today: dentist at 3 PM, and Sam's birthday is in 7 days."),
    "glass": job("glass", "Heads up: Dining is at 92% of its budget ($184 of $200)."),
    "charter": job("charter", "Your spending this month, by category.", image="/chart/abc.png"),
    "qwerty": job("qwerty", "I can update GLASS_BUDGETS for you.", buttons=[{"id": "qp:x:yes", "label": "Approve"}]),
}
ASKED = []
def fake_chat(tier, messages, max_tokens=None, **kw):
    ASKED.append(messages)
    return "Two things need you: Dining is at 92% (Glass), and the dentist is at 3 PM (Remi). Charter posted this month's chart."
h.llm_chat = fake_chat
check("summary is the default", h.ROUND_POSTS == "summary")
r = h.run_round(force=True)
chat = h.allchat_view(200)
mine = [m for m in chat if m.get("kind") != "event"]
check("the crew's text posts don't go to the chat", not any(m["from"] in ("remi", "glass") for m in mine))
summary = [m for m in mine if m["from"] == "mistral" and not m.get("image")]
check("Mistral posts one round update", len(summary) == 1 and "Dining is at 92%" in summary[0]["text"])
check("...built from their reports, word for word", "dentist at 3 PM" in ASKED[-1][1]["content"] and "## Glass" in ASKED[-1][1]["content"]
      and "never add facts" in ASKED[-1][0]["content"])
check("...with the crew who reported in its trail, Mistral last", summary[0]["trail"][-1] == "mistral" and {"remi", "glass", "charter"} <= set(summary[0]["trail"]))
pic = [m for m in mine if m["from"] == "mistral" and m.get("image")]
check("Charter's chart comes along as Mistral's post", len(pic) == 1 and pic[0]["image"] == "/chart/abc.png" and pic[0]["text"].startswith("From Charter:"))
check("posts with buttons stay the agent's own (Approve only works there)", any(m["from"] == "qwerty" and m.get("buttons") for m in mine))
check("every job still ran and counted", all(r["ran"][a]["ok"] for a in ("remi", "glass", "charter", "qwerty")))
check("Mistral keeps the reports for follow-up questions", "## The crew's last round reports" in h.crew_facts()
      and "Sam's birthday is in 7 days" in h.crew_facts())
# if the summary call fails, the reports still go out
def down(*a, **k): raise h.LLMError("gemini returned 503")
h.llm_chat = down
h.run_round(force=True)
last = [m for m in h.allchat_view(200) if m["from"] == "mistral" and not m.get("image")][-1]
check("model down: a plain update from the reports instead", last["text"].startswith("Round update from the crew:") and "**Glass:** Heads up" in last["text"])
# the old way is one setting away
h.ROUND_POSTS = "agents"; h.llm_chat = fake_chat
h.run_round(force=True)
check("ROUND_POSTS=agents: each agent posts its own again", any(m["from"] == "remi" for m in h.allchat_view(200))
      and any(m["from"] == "glass" for m in h.allchat_view(200)))
check("QWERTY can switch it on approval", "ROUND_POSTS" in h.SETTABLE)
print("ALL PASS")
