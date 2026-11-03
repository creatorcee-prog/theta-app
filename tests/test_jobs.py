"""(Background jobs) Native tool calling for the single head (2026-11-03): Theta gets its tools
as real function tools, sees every result (failures too) and keeps going for
several rounds; actions show as receipts; a model that refuses tools falls
back to the ACTION-line way; every call carries the writing rule. A fake
OpenAI-format server scripts the model's turns; no live network."""
import sys, json, os, io, threading
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
BODIES, SCRIPT, STATE = [], [], {"refuse_tools": False}


def call(name, arg, cid):
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


PUSH = []
h.notify = lambda title, body, url="/": PUSH.append((title, body, url)) or 1
h.TOOLS["web_search"] = (h.TOOLS["web_search"][0], lambda arg, agent: f"Results for {arg}: 1. Vacuum A $199 https://a.example 2. Vacuum B $249 https://b.example", h.TOOLS["web_search"][2])

# ---- Theta hands a big job to the background
SCRIPT[:] = [{"text": "", "calls": [call("background", "research the best robot vacuums under $300 and compare 3", "j1")]},
             "On it. I'll ping you when it's done."]
post("research the best robot vacuums under $300 and compare 3 for me")
r = last_reply()["text"]
js = h.jobs()
check("a background job is saved", len(js) == 1 and js[0]["status"] == "queued" and "robot vacuums" in js[0]["task"])
check("the reply says so", "Started background job #1" in r)
check("background is one of Theta's tools", "background" in h.head_tools())

# ---- tick 1: one round, then out of time: it stops and keeps its place
BODIES.clear()
SCRIPT[:] = [{"text": "", "calls": [call("web_search", "best robot vacuum under $300", "s1")]}]
SEARCHED = []
_search = h.TOOLS["web_search"][1]
h.TOOLS["web_search"] = (h.TOOLS["web_search"][0], lambda arg, agent: SEARCHED.append(arg) or _search(arg, agent), h.TOOLS["web_search"][2])
real_left = h._time_left
h._time_left = lambda: 5 if SEARCHED else 30  # the clock runs low once the search is done
check("tick 1: still running", h.jobs_tick(seconds=35) == "running")
h._time_left = real_left
job = h.jobs()[0]
check("its place is kept: the search and its result", any(m["role"] == "tool" and "Vacuum A" in m["content"] for m in job["msgs"])
      and job["ticks"] == 1 and job["rounds"] == 1)
check("the job prompt says it's background work", "background job" in BODIES[0][1]["messages"][0]["content"]
      or any("background job" in m["content"] for m in BODIES[0][1]["messages"] if m["role"] == "system"))
check("a job can't start another job", "background" not in [t["function"]["name"] for t in BODIES[0][1]["tools"]])

# ---- tick 2: picks up where it left off and finishes
BODIES.clear(); PUSH.clear()
SCRIPT[:] = ["Best pick: Vacuum A ($199), then Vacuum B ($249). Sources: https://a.example https://b.example"]
check("tick 2: done", h.jobs_tick(seconds=35) == "done")
sent = BODIES[0][1]["messages"]
check("it went on from the saved conversation", any(m["role"] == "tool" and "Vacuum A" in (m.get("content") or "") for m in sent))
r = last_reply()["text"]
check("the result is posted", r.startswith("Background job #1 is done") and "Vacuum A ($199)" in r)
check("and pushed", PUSH and PUSH[-1][1].startswith("Done: research the best robot vacuums"))
check("nothing left to do", h.jobs_tick(seconds=35) is None)

# ---- not enough time in the tick: it waits
SCRIPT[:] = [{"text": "", "calls": [call("background", "plan my week", "j2")]}, "Will do."]
post("plan my week around my calendar, take your time")
check("too little tick time: it waits", h.jobs_tick(seconds=10) is None and h.jobs()[-1]["status"] == "queued")

# ---- /jobs and cancel
out = h.run_command("/jobs")
check("/jobs lists them", out == "Background jobs:" and "#2 plan my week" in last_reply()["text"])
h.run_command("/jobs cancel 2")
check("/jobs cancel", h.jobs()[-1]["status"] == "cancelled" and h.jobs_tick(seconds=35) is None)
try:
    h.run_command("/jobs cancel 99"); check("unknown job refused", False)
except h.CommandError:
    check("unknown job refused", True)

# ---- three model failures: it gives up and says so
SCRIPT[:] = [{"text": "", "calls": [call("background", "dig through my mail", "j3")]}, "Okay."]
post("go through everything in my mail when you can")
STATE["refuse_tools"] = True  # every call now fails (400)
for _ in range(3):
    h.jobs_tick(seconds=35)
STATE["refuse_tools"] = False
check("after 3 failures: failed, and said so", h.jobs()[-1]["status"] == "failed" and "didn't work out" in last_reply()["text"])
check("the tick runs jobs last, in what's left", "jobs_tick(seconds=min(JOB_TICK_SECONDS, 50 - (time.time() - t_start)))"
      in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api", "_parts", "reminders.py")).read())
print("done")
