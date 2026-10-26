"""Stage 4 P1 migration #2: Mistral's allchat first turn via desk_chat (D5).

Proves the unified path preserves behavior in BOTH desk states, preserves
the legacy side-effect profile (no master_ready() cap-notify calls on a
path that never made them), and keeps single-pass tool behavior.
No production path except Mistral's allchat first turn is touched; the
SEARCH second turn, desk_reply, and every other agent are untouched.

Stubs: _llm_call scripted per (provider, model); claude_chat stubbed;
_diag recorded; notify + master_ready spied. No live network: the only
HTTP is the fake Upstash server in redis mode, as in the other test
files. Both modes take sys.argv[1] ("memory"/"redis"), as run_all.sh
passes it.

Env hygiene: route() reads ROUTE_* vars at call time, so every test
runs inside clean_env(), which pops all ROUTE_* vars (plus the key
vars a test deliberately dirties) and restores them after.
"""
import sys, json, os, contextlib
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer

mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
DB, H, L = {}, {}, {}


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
        elif op == "HGETALL":
            flat = []
            for fk, fv in H.get(k, {}).items():
                flat += [fk, fv]
            r = flat
        elif op == "INCR":
            DB[k] = int(DB.get(k) or 0) + 1
            r = DB[k]
        elif op == "LPUSH":
            L.setdefault(k, []).insert(0, a[0])
            r = len(L[k])
        elif op == "LRANGE":
            rows = L.get(k, [])
            r = rows[int(a[0]):int(a[1]) + 1]
        elif op == "LTRIM":
            L[k] = L.get(k, [])[int(a[0]):int(a[1]) + 1]
            r = "OK"
        else:
            r = None
        self._send(200, {"result": r})


srv = HTTPServer(("127.0.0.1", 0), Fake)
import threading
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


ROUTE_VARS = ["ROUTE_MINER_PROVIDER", "ROUTE_MINER_MODEL", "ROUTE_MANAGER_PROVIDER", "ROUTE_MANAGER_MODEL",
              "ROUTE_LOW_BRAIN_PROVIDER", "ROUTE_LOW_BRAIN_MODEL", "ROUTE_MASTER_PROVIDER", "ROUTE_MASTER_MODEL",
              "ROUTE_DESK_PROVIDER", "ROUTE_DESK_MODEL", "ROUTE_MINER_FALLBACK_MODEL",
              "ROUTE_MANAGER_FALLBACK_MODEL", "ROUTE_LOW_BRAIN_FALLBACK_MODEL"]
KEY_VARS = ["GROQ_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"]


@contextlib.contextmanager
def clean_env(**overrides):
    saved = {k: os.environ.get(k) for k in ROUTE_VARS + KEY_VARS}
    for k in ROUTE_VARS + KEY_VARS:
        os.environ.pop(k, None)
    os.environ.update(DASHBOARD_KEY="dk", ANTHROPIC_API_KEY="", GROQ_API_KEY="<redacted>", GEMINI_API_KEY="<redacted>")
    for k, v in overrides.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def err(msg, retryable=True, timed_out=False):
    return h.LLMError(msg, retryable=retryable, timed_out=timed_out)


# --- diag recorder (restored at the end) ---
_orig_diag = h._diag
diags = []


def _rec(stage, **fields):
    diags.append((stage, fields))


h._diag = _rec


def route_diags():
    return [f for s, f in diags if s == "model.selected" and f.get("via") == "route"]


_orig_llm = h._llm_call
calls = []


def scripted(plan):
    def f(provider, model, messages, max_tokens):
        calls.append((provider, model))
        outs = plan.get((provider, model))
        if not outs:
            raise RuntimeError(f"unexpected call {(provider, model)}")
        out = outs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out
    return f


_orig_claude = h.claude_chat
CLAUDE_CALLS = []
CLAUDE_PLAN = []
CLAUDE_MSGS = []


def fake_claude(messages, max_tokens, model=None, effort=None):
    CLAUDE_CALLS.append(model)
    CLAUDE_MSGS.append(messages)
    if not CLAUDE_PLAN:
        raise RuntimeError("unexpected claude_chat call")
    out = CLAUDE_PLAN.pop(0)
    if isinstance(out, Exception):
        raise out
    return out


h.claude_chat = fake_claude

_orig_notify = h.notify
PUSHED = []
h.notify = lambda title, body, url="/": PUSHED.append((title, body, url)) or 1


def _cap_month():
    return h.datetime.now(h.hub_tz()).strftime("%Y-%m")


def _set_spend(usd):
    h.store().set_meta("claude:spend", json.dumps({_cap_month(): {"usd": usd, "calls": 0, "input": 0, "output": 0}}))


def _capped():
    return h.store().get_meta("claude:capped") or ""


def _fb_model():
    raw = h.store().get_meta("llm:fallback") or ""
    return json.loads(raw).get("model") if raw else ""


def thread(text="hello"):
    return [{"from": "you", "text": text}]


def reset_run():
    diags.clear()
    calls.clear()
    CLAUDE_CALLS.clear()
    CLAUDE_PLAN.clear()
    CLAUDE_MSGS.clear()
    PUSHED.clear()
    h.store().set_meta("llm:fallback", "")
    h.store().set_meta("claude:capped", "")
    _set_spend(0.0)


FLASH = ("gemini", "gemini-3.8-flash")
GROQ120 = ("groq", "openai/gpt-oss-120b")
HAIKU = "claude-haiku-5-5"



# --- Migration #3: send_digest digest-opener via route() (option A) ---
# Only the opener call is migrated; the digest post, card, id meta and
# notify are the legacy behavior. Stubs: morning_digest + news_items +
# save_card captured; _llm_call scripted; claude_chat stubbed (any
# Haiku call would be a failure — this site never takes the desk path).
_orig_morning = h.morning_digest
_orig_news = h.news_items
_orig_card = h.save_card
_orig_fb = dict(h.FALLBACK_LLM)
CARD = []
h.morning_digest = lambda today: ("DIGEST-POST", "DIGEST-BRIEF")
h.news_items = lambda now=None: ([], [])
h.save_card = lambda *a, **k: CARD.append(a)


def reset_digest():
    reset_run()
    CARD.clear()
    h.store().set_meta("round:mistral:digest_day", "")
    h.store().set_meta("round:mistral:digest_id", "")


def posted():
    return CARD[-1][2] if CARD else ""


# D1. Defaults: opener present, digest posts, one route diag, no desk.
with clean_env():
    reset_digest()
    h._llm_call = scripted({FLASH: ["Good morning."], GROQ120: []})
    ok = h.send_digest()
    check("digest defaults: sends, opener on top of digest post",
          ok is True and posted() == "Good morning.\nDIGEST-POST")
    check("digest defaults: flash called once, no Haiku, one route diag",
          calls == [FLASH] and CLAUDE_CALLS == [] and len(route_diags()) == 1)
    check("digest defaults: notify brief sent, digest id recorded, no cap write",
          PUSHED == [("Mistral", "DIGEST-BRIEF", "/")]
          and (h.store().get_meta("round:mistral:digest_id") or "") != ""
          and _capped() == "")
    check("digest defaults: second call same day is a no-op (guard untouched)",
          h.send_digest() is False and len(CARD) == 1)

# D2. Retryable flash failure: one retry, then Groq fallback.
with clean_env():
    reset_digest()
    h._llm_call = scripted({FLASH: [err("down"), err("down")], GROQ120: ["Groq morning."]})
    ok = h.send_digest()
    check("digest fallback: retry then Groq, opener is the Groq line",
          ok is True and calls == [FLASH, FLASH, GROQ120]
          and posted() == "Groq morning.\nDIGEST-POST")
    check("digest fallback: fallback meta names Groq",
          _fb_model() == GROQ120[1])

# D3a. Legacy fallback-off: opener dropped, digest still posts, no Groq.
# (FALLBACK_LLM values are (provider, model) tuples; "off" is the model.)
h.FALLBACK_LLM["low_brain"] = ("groq", "off")
try:
    with clean_env():
        reset_digest()
        h._llm_call = scripted({FLASH: [err("down"), err("down")], GROQ120: ["Groq morning."]})
        ok = h.send_digest()
        check("digest legacy fallback-off: opener dropped, digest posts, no Groq",
              ok is True and calls == [FLASH, FLASH] and posted() == "DIGEST-POST")
finally:
    h.FALLBACK_LLM.clear()
    h.FALLBACK_LLM.update(_orig_fb)

# D3b. ROUTE fallback-off: same outcome via env.
with clean_env(ROUTE_LOW_BRAIN_FALLBACK_MODEL="off"):
    reset_digest()
    h._llm_call = scripted({FLASH: [err("down"), err("down")], GROQ120: ["Groq morning."]})
    ok = h.send_digest()
    check("digest ROUTE fallback-off: opener dropped, digest posts, no Groq",
          ok is True and calls == [FLASH, FLASH] and posted() == "DIGEST-POST")

# D4. Option A core: half-pair ROUTE var fails routing, digest survives.
with clean_env(ROUTE_LOW_BRAIN_MODEL="custom-only"):
    reset_digest()
    h._llm_call = scripted({FLASH: ["Good morning."], GROQ120: []})
    ok = h.send_digest()
    check("digest config error: opener dropped, digest posts, no model call",
          ok is True and calls == [] and posted() == "DIGEST-POST"
          and PUSHED == [("Mistral", "DIGEST-BRIEF", "/")])

# D5. Fail-fast radius contained: unrelated-role config error, same outcome.
with clean_env(ROUTE_MINER_PROVIDER="bogus"):
    reset_digest()
    h._llm_call = scripted({FLASH: ["Good morning."], GROQ120: []})
    ok = h.send_digest()
    check("digest unrelated config error: opener dropped, digest posts",
          ok is True and calls == [] and posted() == "DIGEST-POST")

# D6. Desk up: still no desk leg (bare tier call, agent/entry_point None).
with clean_env(ANTHROPIC_API_KEY="sk-test"):
    reset_digest()
    h._llm_call = scripted({FLASH: ["Good morning."], GROQ120: []})
    ok = h.send_digest()
    check("digest desk-up: flash answers, Haiku never called",
          ok is True and calls == [FLASH] and CLAUDE_CALLS == []
          and posted() == "Good morning.\nDIGEST-POST")

# D7. opener=False (round caller): no model call at all.
with clean_env():
    reset_digest()
    h._llm_call = scripted({FLASH: ["Good morning."], GROQ120: []})
    ok = h.send_digest(opener=False)
    check("digest opener=False: digest posts bare, no model call",
          ok is True and calls == [] and posted() == "DIGEST-POST")

# D8. Timeout: skip retry, straight to Groq.
with clean_env():
    reset_digest()
    h._llm_call = scripted({FLASH: [err("slow", timed_out=True)], GROQ120: ["Groq morning."]})
    ok = h.send_digest()
    check("digest timeout: no retry, Groq opener",
          ok is True and calls == [FLASH, GROQ120]
          and posted() == "Groq morning.\nDIGEST-POST")

h.morning_digest = _orig_morning
h.news_items = _orig_news
h.save_card = _orig_card
h.FALLBACK_LLM.clear()
h.FALLBACK_LLM.update(_orig_fb)
h._diag = _orig_diag
h._llm_call = _orig_llm
h.claude_chat = _orig_claude
h.notify = _orig_notify
print("test_migration3_digest done")
