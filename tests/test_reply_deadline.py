"""Regression test: a slow model chain must not hang a chat reply past
Vercel's 60s function wall (the Phase 4 tool test stall).

A fake provider server sleeps 30s on every completion call. With a
6s request deadline, llm_chat("low_brain") must fail fast: the primary
Gemini call times out at the deadline, and the Groq fallback finds no
time left, instead of burning LLM_TIMEOUT per attempt across the
chain. Elapsed must be at least the deadline (proving the call really
waited) and well under the 25s default LLM_TIMEOUT (proving the
deadline, not the per-call timeout, cut the chain).

Also proves app() wires the deadline: an /api/allchat request (even
one rejected for a bad key) leaves _REQ.deadline set on the request
thread.

Storage-independent (memory store in both modes); the mode argv is
accepted and ignored.
"""
import sys, os, io, time, threading, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.dont_write_bytecode = True


class Slow(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        time.sleep(30)  # the provider answers, far too late for a chat reply
        body = json.dumps({"choices": [{"message": {"content": "slow ok"}}]}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            pass  # the client gave up long ago; that is the point


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        if detail:
            print(detail[-2000:])
        sys.exit(1)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="glass:gk1,lenz:lk", GROQ_API_KEY="<redacted>", GEMINI_API_KEY="<redacted>",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g",
                  VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}

# 1. The chain is bounded by the deadline.
h._REQ.deadline = time.time() + 6
t0 = time.perf_counter()
try:
    h.llm_chat("low_brain", [{"role": "user", "content": "hi"}])
    raised = None
except h.LLMError as e:
    raised = str(e)
dt = time.perf_counter() - t0
print(f"  (elapsed {dt:.1f}s with a 6s deadline; default LLM_TIMEOUT is {h.LLM_TIMEOUT}s)")
check("slow model chain fails within the deadline, not after LLM_TIMEOUT x chain",
      raised is not None and "deadline" in raised and 4 <= dt < 20,
      f"elapsed={dt:.1f}s raised={raised!r}")

# 2. app() wires the deadline for chat requests.
h._REQ.deadline = None
env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/allchat", "QUERY_STRING": "",
       "CONTENT_LENGTH": "2", "wsgi.input": io.BytesIO(b"{}"),
       "HTTP_X_DASHBOARD_KEY": "wrong"}
seen = {}
h.app(env, lambda s, hdrs: seen.setdefault("status", s))
check("app() sets _REQ.deadline for /api/allchat",
      seen["status"][:1] == "4" and getattr(h._REQ, "deadline", None) is not None
      and time.time() < h._REQ.deadline < time.time() + 61,
      f"status={seen} deadline={getattr(h._REQ, 'deadline', None)}")
print("done")
