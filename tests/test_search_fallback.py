"""Bridge-first search: answer_with_search tries bridge web_search first;
Gemini runs only if the bridge returns nothing or fails.

This file's guards were updated for the bridge-first change (they used to
pin Gemini-first): a bridge success now preempts Gemini entirely, and a
Gemini budget exhaustion no longer blocks a bridge answer, because the
bridge does not consume the Gemini budget. The guards were changed to the
new state, not weakened: every old scenario still asserts its reply shape,
plus the new preemption/budget facts.

Stubs: gemini_search (fail / ok / must-not-run), the second-turn model
call (desk_chat for mistral), and the bridge tool layer. No live network.
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


def canned_second(msgs, *a, **kw):  # desk_chat now also gets route() keywords
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
    {"title": "Bridge Glass One", "url": "https://example.com/one", "snippet": "Bridge snippet one."},
    {"title": "Bridge Glass Two", "url": "https://example.com/two", "snippet": "Bridge snippet two."},
], "sources": ["https://example.com/one", "https://example.com/two"]}
FB_EMPTY = {"status": "ok", "data": [], "sources": []}
FB_ERR = {"status": "error", "data": None, "sources": [], "error": "duckduckgo blocked", "duration_ms": 3}


def gemini_fail(prompt, timeout=30):
    raise h.LLMError("Gemini search returned 429: quota exhausted")


def gemini_ok(prompt, timeout=30):
    return ("Gemini says: display glasses exist.",
            [(0, 10, "https://example.com/gemini", "Gemini Glass")], 1)


def gemini_boom(prompt, timeout=30):
    raise AssertionError("gemini_search must not run on this path")


def prompt_text():
    return "\n".join(m.get("content", "") for m in CAPTURED[-1] if isinstance(m, dict))


# 1. Bridge answers first -> Gemini never runs, bridge note (not a
# Gemini-failure note) is carried.
h.gemini_search = gemini_boom
h._tb.agent_tools = FakeTools(FB_OK)
CALLS.clear()
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
check("bridge-first results reach the second turn", "Bridge Glass One" in prompt_text() and "Bridge Glass Two" in prompt_text())
check("bridge-first reply cites the bridge source", "https://example.com/one" in r)
check("bridge-first reply carries the bridge note", "bridge web search" in r)
check("second turn was told the results are bridge results", "bridge web search" in prompt_text().lower())
check("bridge-first called bridge web_search once", len(CALLS) == 1 and CALLS[0]["name"] == "web_search")

# 2. Bridge empty -> Gemini runs exactly as before.
h.gemini_search = gemini_ok
h._tb.agent_tools = FakeTools(FB_EMPTY)
CALLS.clear()
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
check("bridge-empty second turn gets the gemini text", "Gemini says" in prompt_text())
check("bridge-empty reply cites the gemini source", "https://example.com/gemini" in r)
check("bridge-empty reply has no bridge note", "bridge web search" not in r)
check("bridge-empty still attempted the bridge once", len(CALLS) == 1)

# 3. Bridge fails + Gemini fails -> graceful failure, bridge tried once
# (not retried after the Gemini error), no note, no crash.
h.gemini_search = gemini_fail
h._tb.agent_tools = FakeTools(FB_ERR)
CALLS.clear()
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
check("double failure still produces a reply", isinstance(r, str) and r)
check("double failure second turn sees the search failure", "the search failed" in prompt_text())
check("double failure reply has no bridge note", "bridge web search" not in r)
check("double failure tried the bridge once, not again", len(CALLS) == 1)

# 4. No bridge layer + Gemini fails -> graceful failure, no crash.
h.gemini_search = gemini_fail
h._tb.agent_tools = None
CALLS.clear()
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
check("missing bridge layer still produces a reply", isinstance(r, str) and r)
check("missing bridge layer second turn sees the search failure", "the search failed" in prompt_text())
check("missing bridge layer reply has no bridge note", "bridge web search" not in r)

# 5. Monthly budget exhausted -> the bridge is NOT blocked (it does not
# consume the Gemini budget); only the Gemini leg is gated.
h.gemini_search = gemini_boom
h._tb.agent_tools = FakeTools(FB_OK)
month = datetime.now(h.hub_tz()).strftime("%Y-%m")
h.store().set_meta("search:used", json.dumps({month: 4000}))
CALLS.clear()
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
check("budget-exhausted bridge success still answers", "Bridge Glass One" in prompt_text())
check("budget-exhausted bridge success has no used-up note", "used up" not in prompt_text())
check("budget-exhausted bridge success carries the bridge note", "bridge web search" in r)
check("budget-exhausted bridge success called the bridge once", len(CALLS) == 1)
# 5b. Budget exhausted + bridge empty -> the used-up note, as before.
h._tb.agent_tools = FakeTools(FB_EMPTY)
CALLS.clear()
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
check("budget-exhausted bridge-empty second turn sees the used-up note", "used up" in prompt_text())
check("budget-exhausted bridge-empty reply has no bridge note", "bridge web search" not in r)
check("budget-exhausted bridge-empty still attempted the bridge once", len(CALLS) == 1)

print("ALL PASS")
