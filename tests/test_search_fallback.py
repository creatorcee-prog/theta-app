"""Search fallback: answer_with_search falls back to bridge web_search
when gemini_search fails (429 included), and only then.

Stubs: gemini_search (fail / ok), the second-turn model call
(desk_chat for mistral), and the bridge tool layer. No live network.
"""
import sys, json, threading, os
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
DB, H = {}, {}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else []
        op, k, a = body[0], body[1], body[2:]
        if op == "GET":
            r = DB.get(k)
        elif op == "SET":
            DB[k] = a[0]
            r = "OK"
        elif op == "HSET":
            d = H.setdefault(k, {})
            for i in range(0, len(a) - 1, 2):
                d[a[i]] = a[i + 1]
            r = 1
        elif op == "HMGET":
            r = [H.get(k, {}).get(f) for f in a]
        elif op == "HGET":
            r = H.get(k, {}).get(a[0])
        else:
            r = None
        self._send(200, {"result": r})


srv = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="mistral:mk", GEMINI_API_KEY="g", GROQ_API_KEY="q",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="t")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


CAPTURED, CALLS = [], []


def canned_second(msgs):
    CAPTURED.append(msgs)
    return "Answer from search [1]."


h.desk_chat = canned_second
h.llm_chat = lambda tier, msgs, **kw: canned_second(msgs)


class FakeTools:
    def __init__(self, result):
        self.result = result

    def run_tool(self, store, call, agent_id="hub"):
        CALLS.append(call)
        return self.result


FB_OK = {"status": "ok", "data": [
    {"title": "Fallback Glass One", "url": "https://example.com/one", "snippet": "Fallback snippet one."},
    {"title": "Fallback Glass Two", "url": "https://example.com/two", "snippet": "Fallback snippet two."},
], "sources": ["https://example.com/one", "https://example.com/two"]}
FB_ERR = {"status": "error", "data": None, "sources": [], "error": "duckduckgo blocked", "duration_ms": 3}


def gemini_fail(prompt, timeout=30):
    raise h.LLMError("Gemini search returned 429: quota exhausted")


def gemini_ok(prompt, timeout=30):
    return ("Gemini says: display glasses exist.",
            [(0, 10, "https://example.com/gemini", "Gemini Glass")], 1)


def prompt_text():
    return "\n".join(m.get("content", "") for m in CAPTURED[-1] if isinstance(m, dict))


# 1. Gemini 429 -> fallback results are used, and the reply says so.
h.gemini_search = gemini_fail
h._tb.agent_tools = FakeTools(FB_OK)
CALLS.clear()
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
check("fallback results reach the second turn", "Fallback Glass One" in prompt_text() and "Fallback Glass Two" in prompt_text())
check("fallback reply cites the fallback source", "https://example.com/one" in r)
check("fallback reply carries the fallback note", "fallback web search" in r)
check("second turn was told the results are fallback", "fallback" in prompt_text().lower())
check("fallback called bridge web_search once", len(CALLS) == 1 and CALLS[0]["name"] == "web_search")

# 2. Gemini ok -> no fallback, no note.
h.gemini_search = gemini_ok
CALLS.clear()
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
check("gemini success second turn gets the gemini text", "Gemini says" in prompt_text())
check("gemini success reply cites the gemini source", "https://example.com/gemini" in r)
check("gemini success reply has no fallback note", "fallback web search" not in r)
check("gemini success never calls the fallback", len(CALLS) == 0)

# 3. Gemini 429 + fallback also fails -> graceful failure, no note, no crash.
h.gemini_search = gemini_fail
h._tb.agent_tools = FakeTools(FB_ERR)
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
check("double failure still produces a reply", isinstance(r, str) and r)
check("double failure second turn sees the search failure", "the search failed" in prompt_text())
check("double failure reply has no fallback note", "fallback web search" not in r)

# 4. Gemini 429 + no bridge layer -> graceful failure, no crash.
h._tb.agent_tools = None
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
check("missing bridge layer still produces a reply", isinstance(r, str) and r)
check("missing bridge layer second turn sees the search failure", "the search failed" in prompt_text())
check("missing bridge layer reply has no fallback note", "fallback web search" not in r)

# 5. Monthly budget exhausted -> neither gemini nor fallback runs.
def gemini_boom(prompt, timeout=30):
    raise AssertionError("gemini_search must not run when the budget is used up")

h.gemini_search = gemini_boom
h._tb.agent_tools = FakeTools(FB_OK)
month = datetime.now(h.hub_tz()).strftime("%Y-%m")
h.store().set_meta("search:used", json.dumps({month: 4000}))
CALLS.clear()
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
check("budget-exhausted second turn sees the used-up note", "used up" in prompt_text())
check("budget-exhausted never calls the fallback", len(CALLS) == 0)
check("budget-exhausted reply has no fallback note", "fallback web search" not in r)

print("ALL PASS")
