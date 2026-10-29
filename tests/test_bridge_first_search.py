"""Bridge-first search: a bridge success skips Gemini entirely, including
its budget spend; a bridge empty/error falls through to Gemini.

Stubs: gemini_search (ok / must-not-run), the second-turn model call
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
], "sources": ["https://example.com/one"]}
FB_EMPTY = {"status": "ok", "data": [], "sources": []}
FB_ERR = {"status": "error", "data": None, "sources": [], "error": "provider down", "duration_ms": 3}
FB_NOURL = {"status": "ok", "data": [
    {"title": "No link here", "url": "", "snippet": "No URL, so no source."},
], "sources": []}


def gemini_ok(prompt, timeout=30):
    return ("Gemini says: display glasses exist.",
            [(0, 10, "https://example.com/gemini", "Gemini Glass")], 1)


def gemini_boom(prompt, timeout=30):
    raise AssertionError("gemini_search must not run when the bridge answers")


def prompt_text():
    return "\n".join(m.get("content", "") for m in CAPTURED[-1] if isinstance(m, dict))


def reset_budget():
    h.store().set_meta("search:used", json.dumps({}))


# A. Bridge success: Gemini never runs AND its budget is untouched.
reset_budget()
h.gemini_search = gemini_boom
h._tb.agent_tools = FakeTools(FB_OK)
CALLS.clear()
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
check("bridge success skips gemini and answers from the bridge", "Bridge Glass One" in prompt_text())
check("bridge success leaves the gemini budget untouched", h.searches_used() == 0)
check("bridge success called the bridge once", len(CALLS) == 1)

# B. Bridge empty: Gemini runs and its budget advances by exactly one.
reset_budget()
h.gemini_search = gemini_ok
h._tb.agent_tools = FakeTools(FB_EMPTY)
CALLS.clear()
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
check("bridge empty falls through to gemini", "Gemini says" in prompt_text())
check("bridge empty spends exactly one gemini budget unit", h.searches_used() == 1)
check("bridge empty reply has no bridge note", "bridge web search" not in r)

# C. Bridge error: Gemini runs, no bridge note.
reset_budget()
h.gemini_search = gemini_ok
h._tb.agent_tools = FakeTools(FB_ERR)
CALLS.clear()
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
check("bridge error falls through to gemini", "Gemini says" in prompt_text())
check("bridge error reply has no bridge note", "bridge web search" not in r)
check("bridge error attempted the bridge once", len(CALLS) == 1)

# D. Bridge data without URLs yields no sources, so Gemini runs.
reset_budget()
h.gemini_search = gemini_ok
h._tb.agent_tools = FakeTools(FB_NOURL)
CALLS.clear()
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
check("url-less bridge data falls through to gemini", "Gemini says" in prompt_text())
check("url-less bridge data reply cites gemini, not the url-less item", "https://example.com/gemini" in r)

print("ALL PASS")
