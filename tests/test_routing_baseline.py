"""Stage 4A P0 baseline: pin CURRENT routing, registration, fallback, and
execution behavior before any P1 change. No behavior is changed to make
these pass; they document what the code does today on main.

Stubs: _llm_call / claude_chat / master_ready / gemini_search / desk_chat
(module attributes, restored after each section). No live network: the
only HTTP is the fake Upstash server in redis mode, as in the other
test files.
"""
import sys, json, threading, os
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer

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
os.environ.update(DASHBOARD_KEY="dk", ANTHROPIC_API_KEY="", GROQ_API_KEY="<redacted>", GEMINI_API_KEY="<redacted>")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="<redacted>")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h

h.LLM_RETRY_DELAY = 0  # keep retry tests fast; the delay itself is unchanged


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


def msgs():
    return [{"role": "user", "content": "hi"}]


# --- diag recorder (restored at the end) ---
_orig_diag = h._diag
diags = []


def _rec(stage, **fields):
    diags.append((stage, fields))


h._diag = _rec


def selected():
    return [f for s, f in diags if s == "model.selected"]


def applied():
    return [f for s, f in diags if s == "tools.applied"]


def tool_done():
    return [f for s, f in diags if s == "tool.done"]


# --- A. Tool registration, as it stands on main ---
INTERNAL = ["remember", "forget", "cancel", "remind", "check", "note", "self_note", "spend",
            "watched", "project", "propose", "ask_qwerty", "ask", "chart", "workout"]
BRIDGE = ["web_search", "fetch_page", "task_create", "task_list", "task_complete",
          "task_reopen", "task_note", "follow_create", "follow_list", "follow_cancel"]
check("TOOLS holds exactly the 15 internal tools", sorted(
    k for k in h.TOOLS if k in INTERNAL) == sorted(INTERNAL) and len(h.TOOLS) == 25)
check("BRIDGE_TOOLS holds exactly the 10 bridge tools (incl. 3 follow tools)",
      sorted(h.BRIDGE_TOOLS) == sorted(BRIDGE))
mp = h.tools_prompt("mistral")
check("mistral prompt offers every bridge tool",
      all(f"ACTION: {t} |" in mp for t in BRIDGE))
check("mistral prompt offers project/ask/chart/workout but not propose (qwerty-only)",
      "ACTION: project |" in mp and "ACTION: ask |" in mp and "ACTION: chart |" in mp
      and "ACTION: workout |" in mp and "ACTION: propose |" not in mp)
gp = h.tools_prompt("glass")
check("glass prompt offers bridge tools but not gated project/ask",
      "ACTION: web_search |" in gp and "ACTION: project |" not in gp and "ACTION: ask |" not in gp)
check("qwerty prompt offers propose", "ACTION: propose |" in h.tools_prompt("qwerty"))
diag = h.tools_diag()
check("tools_diag checks all 10 bridge tools in the prompt (B1 fix)",
      set(diag["mistral_prompt"]) == set(BRIDGE) and all(diag["mistral_prompt"].values()))
check("tools_diag bridge_tools lists the registered bridge tools",
      diag["bridge_tools"] == sorted(BRIDGE))

# --- B. Routing: tier selection, desk override, fallback, borrowing ---
check("TIER_LLM defaults: miner groq 20b, manager groq 120b, low_brain gemini flash",
      h.TIER_LLM["miner"] == ("groq", "openai/gpt-oss-20b")
      and h.TIER_LLM["manager"] == ("groq", "openai/gpt-oss-120b")
      and h.TIER_LLM["low_brain"] == ("gemini", "gemini-3.8-flash"))

_orig_llm = h._llm_call
_orig_claude = h.claude_chat
_orig_ready = h.master_ready
_orig_desk_model = h.DESK_MODEL
calls = []


def llm_ok(provider, model, messages, max_tokens):
    calls.append((provider, model))
    return "ok-text"


def llm_fail_then_ok(failures):
    def f(provider, model, messages, max_tokens):
        calls.append((provider, model))
        if failures:
            raise failures.pop(0)
        return "ok-text"
    return f


def err(msg, retryable=True, timed_out=False, status=None):
    e = h.LLMError(msg, retryable=retryable, timed_out=timed_out)
    if status is not None:
        e.status = status
    return e


diags.clear()
h._llm_call = llm_ok
check("miner primary uses groq 20b",
      h.llm_chat("miner", msgs()) == "ok-text" and calls == [("groq", "openai/gpt-oss-20b")])
sel = selected()
check("miner primary emits model.selected primary",
      len(sel) == 1 and sel[0]["tier"] == "miner" and sel[0]["provider"] == "groq"
      and sel[0]["model"] == "openai/gpt-oss-20b" and sel[0]["via"] == "primary")
last = json.loads(h.store().get_meta("llm:last_selection"))
check("llm:last_selection meta records the primary selection",
      last["tier"] == "miner" and last["model"] == "openai/gpt-oss-20b" and last["via"] == "primary")

diags.clear()
calls.clear()
check("low_brain primary uses gemini flash",
      h.llm_chat("low_brain", msgs()) == "ok-text" and calls == [("gemini", "gemini-3.8-flash")])
check("low_brain primary selection noted",
      len(selected()) == 1 and selected()[0]["tier"] == "low_brain" and selected()[0]["via"] == "primary")

diags.clear()
calls.clear()
check("master without a key stands in on low_brain (no Claude call)",
      h.llm_chat("master", msgs()) == "ok-text" and calls == [("gemini", "gemini-3.8-flash")])
check("master stand-in selection is tier low_brain, via primary",
      len(selected()) == 1 and selected()[0]["tier"] == "low_brain" and selected()[0]["via"] == "primary")

claude_calls = []


def claude_ok(messages, max_tokens, model=None, effort=None):
    claude_calls.append(model)
    return "claude-text"


h.master_ready = lambda: True
h.claude_chat = claude_ok
diags.clear()
check("master with a key uses Claude",
      h.llm_chat("master", msgs()) == "claude-text" and claude_calls == [None])
check("master selection noted with the master model id",
      len(selected()) == 1 and selected()[0]["tier"] == "master"
      and selected()[0]["provider"] == "anthropic" and selected()[0]["model"] == h.MASTER_MODEL_ID
      and selected()[0]["via"] == "master")

diags.clear()
claude_calls.clear()
check("manager with the desk on uses Haiku",
      h.llm_chat("manager", msgs()) == "claude-text" and claude_calls == [h.DESK_MODEL])
check("manager desk selection noted",
      len(selected()) == 1 and selected()[0]["tier"] == "manager" and selected()[0]["via"] == "desk")


def claude_down(messages, max_tokens, model=None, effort=None):
    claude_calls.append(model)
    raise h.LLMError("desk down", retryable=True)


h.claude_chat = claude_down
diags.clear()
calls.clear()
check("manager desk failure falls through to groq 120b",
      h.llm_chat("manager", msgs()) == "ok-text" and calls == [("groq", "openai/gpt-oss-120b")])
check("desk-failure selection is manager primary, not desk",
      len(selected()) == 1 and selected()[0]["tier"] == "manager" and selected()[0]["via"] == "primary")

h.master_ready = _orig_ready
h.DESK_MODEL = "off"
diags.clear()
calls.clear()
check("manager with DESK_MODEL=off skips the desk",
      h.llm_chat("manager", msgs()) == "ok-text" and calls == [("groq", "openai/gpt-oss-120b")])
h.DESK_MODEL = _orig_desk_model
h.claude_chat = _orig_claude

diags.clear()
calls.clear()
h._llm_call = llm_fail_then_ok([err("groq 429", timed_out=False, status=429)])
check("retryable error retries the same model once, then succeeds",
      h.llm_chat("miner", msgs()) == "ok-text"
      and calls == [("groq", "openai/gpt-oss-20b"), ("groq", "openai/gpt-oss-20b")])
check("retry selection carries the rate_limit reason",
      len(selected()) == 1 and selected()[0]["via"] == "retry" and selected()[0]["reason"] == "rate_limit")

diags.clear()
calls.clear()


def llm_fb(provider, model, messages, max_tokens):
    calls.append((provider, model))
    if (provider, model) == ("groq", "openai/gpt-oss-20b"):
        raise err("groq out of free quota", timed_out=True)
    return "fallback-text"


h._llm_call = llm_fb
check("timed-out primary skips the retry and uses the tier fallback",
      h.llm_chat("miner", msgs()) == "fallback-text"
      and calls == [("groq", "openai/gpt-oss-20b"), ("groq", "openai/gpt-oss-120b")])
fb = json.loads(h.store().get_meta("llm:fallback"))
check("llm:fallback meta records tier + fallback model",
      fb["tier"] == "miner" and fb["model"] == "openai/gpt-oss-120b")
check("tier_fallback selection carries the quota reason",
      len(selected()) == 1 and selected()[0]["via"] == "tier_fallback" and selected()[0]["reason"] == "quota")

diags.clear()
calls.clear()


def llm_borrow(provider, model, messages, max_tokens):
    calls.append((provider, model))
    if (provider, model) == ("gemini", "gemini-3.8-flash"):
        return "borrowed-text"
    raise err("down", timed_out=True)


h._llm_call = llm_borrow
check("miner borrows upward to the manager fallback (gemini flash) when its own models fail",
      h.llm_chat("miner", msgs()) == "borrowed-text"
      and ("gemini", "gemini-3.8-flash") in calls)
check("borrow selection is tier miner, via borrow",
      len(selected()) == 1 and selected()[0]["tier"] == "miner" and selected()[0]["via"] == "borrow")

diags.clear()
calls.clear()
claude_calls.clear()
h.master_ready = lambda: True
h.claude_chat = claude_down
h._llm_call = lambda *a: (_ for _ in ()).throw(err("down", timed_out=True))
raised = False
try:
    h.llm_chat("miner", msgs())
except h.LLMError:
    raised = True
check("exhausted chain raises instead of looping",
      raised)
check("upward borrowing never reaches the master model (Opus)",
      all(m != h.MASTER_MODEL_ID for m in claude_calls))
h.master_ready = _orig_ready
h.claude_chat = _orig_claude
h._llm_call = _orig_llm

# --- C. Execution: single-pass receipts, 3-cap, SEARCH: second turn ---
diags.clear()
out = h.run_actions("mistral", "Hello\nACTION: task_create | Baseline task")
check("run_actions replaces ACTION lines with receipts",
      "✓" in out and "Baseline task" in out and "id t" in out and "ACTION:" not in out)
check("single pass: tools.applied reports returned_to_model=0",
      len(applied()) == 1 and applied()[0]["returned_to_model"] == 0)

diags.clear()
out = h.run_actions("mistral", "\n".join(f"ACTION: task_create | Cap {i}" for i in range(4)))
check("at most 3 actions run per reply",
      out.count("✓") == 3)

prompts = []


def canned_second(msgs):
    prompts.append(msgs)
    return "Answer [1]."


_orig_gemini = h.gemini_search
_orig_desk = h.desk_chat
h.gemini_search = lambda prompt, timeout=30: ("Found: python docs text",
                                              [("", "", "https://example.com/one", "One")], 1)
h.desk_chat = canned_second
reply = h.answer_with_search("mistral", "You are Mistral.", "What is it?", "python docs")
check("SEARCH: second turn receives the search text",
      any("Found: python docs text" in (m.get("content") or "") for m in prompts[0]))
check("SEARCH: reply cites only the search sources",
      "https://example.com/one" in reply and "Sources:" in reply)
h.gemini_search = _orig_gemini
h.desk_chat = _orig_desk

# --- D. Tool telemetry: sanitized error categories ---
_orig_ws = h.TOOLS["web_search"]
diags.clear()


def search_boom(arg, agent):
    raise ValueError("Search failed (rate_limit): provider rate limit reached (HTTP 429)")


h.TOOLS["web_search"] = ("web_search | <query>", search_boom, None)
out = h.run_actions("mistral", "ACTION: web_search | x")
done = tool_done()
check("search failure receipt is an error, not a result",
      "✗" in out)
check("tool.done carries search:rate_limit category",
      len(done) == 1 and done[0]["status"] == "error" and done[0]["error_category"] == "search:rate_limit")


def generic_boom(arg, agent):
    raise ValueError("boom")


h.TOOLS["web_search"] = ("web_search | <query>", generic_boom, None)
diags.clear()
h.run_actions("mistral", "ACTION: web_search | x")
done = tool_done()
check("generic tool failure category is the exception class",
      len(done) == 1 and done[0]["error_category"] == "ValueError")
h.TOOLS["web_search"] = _orig_ws

check("model error categories: auth/rate_limit/timeout/quota/capacity/empty/network/malformed/unknown",
      h._model_error_category(err("x", status=401)) == "auth"
      and h._model_error_category(err("x", status=429)) == "rate_limit"
      and h._model_error_category(err("timed out", timed_out=True)) == "timeout"
      and h._model_error_category(err("groq out of free quota")) == "quota"
      and h._model_error_category(err("Groq has 5 tokens left")) == "capacity"
      and h._model_error_category(err("model returned an empty reply")) == "empty"
      and h._model_error_category(err("groq call failed: URLError")) == "network"
      and h._model_error_category(err("groq call failed: ValueError")) == "malformed"
      and h._model_error_category(err("something else")) == "unknown")

h._diag = _orig_diag
print("routing-baseline: all checks passed")
