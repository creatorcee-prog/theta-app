"""Stage 4 P1 migration #4: classify_mail primary/fallback via route().

Proves the migrated miner call preserves behavior: same prompt, same
parsing, same retry/timeout/fallback/error handling, with the borrow
chain untouched (still legacy settings). Only classify_mail's
primary/fallback selection is migrated; every other call site is
untouched.

Stubs: _llm_call scripted per (provider, model); claude_chat stubbed
(for the borrow desk candidate); _diag recorded; notify spied. No
live network: the only HTTP is the fake Upstash server in redis mode,
as in the other test files. Both modes take sys.argv[1]
("memory"/"redis"), as run_all.sh passes it.
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



# --- Migration #4: classify_mail primary/fallback via route() ---
# Only the primary/fallback selection is migrated. Prompt, parsing,
# retry, timeout, fallback and error behavior are preserved; the
# borrow chain is untouched (still legacy settings) and is proven
# still working, not removed.
MINER20 = ("groq", "openai/gpt-oss-20b")
MINER120 = ("groq", "openai/gpt-oss-120b")
GEMINIFLASH = ("gemini", "gemini-3.8-flash")
_orig_fb = dict(h.FALLBACK_LLM)

ROWS = [
    {"id": "t1", "name": "Alice", "email": "alice@example.com",
     "subject": "Q about the report", "snippet": "Can you send it?", "auto": False},
    {"id": "t2", "name": "Shop", "email": "noreply@shop.com",
     "subject": "Your order shipped", "snippet": "Tracking...", "auto": True},
]


def _rows():
    return [dict(r) for r in ROWS]


# D1. Defaults: parsed dict, miner 20b once, one route diag, no side effects.
with clean_env():
    reset_run()
    h._llm_call = scripted({MINER20: ["1|work|yes\n2|shopping|no"], MINER120: []})
    out = h.classify_mail(_rows())
    check("classify defaults: parsed dict, miner 20b once, one route diag",
          out == {"t1": ("work", True), "t2": ("shopping", False)}
          and calls == [MINER20] and len(route_diags()) == 1)
    check("classify defaults: no notify, no cap write, no Haiku",
          PUSHED == [] and _capped() == "" and CLAUDE_CALLS == [])

# D2. Parsing guards (untouched code): unknown cat -> other, bad number ignored.
with clean_env():
    reset_run()
    h._llm_call = scripted({MINER20: ["1|bogus|YES\n9|work|yes"], MINER120: []})
    out = h.classify_mail(_rows())
    check("classify parsing: unknown category -> other, out-of-range ignored",
          out == {"t1": ("other", True)})

# D3. Empty input: no model call, no route decision.
with clean_env():
    reset_run()
    h._llm_call = scripted({MINER20: ["1|work|yes"], MINER120: []})
    out = h.classify_mail([])
    check("classify empty: {} with no model call and no route diag",
          out == {} and calls == [] and route_diags() == [])

# D4. Retryable failure: one retry, then 120b fallback.
with clean_env():
    reset_run()
    h._llm_call = scripted({MINER20: [err("down"), err("down")],
                            MINER120: ["1|work|yes\n2|shopping|no"]})
    out = h.classify_mail(_rows())
    check("classify fallback: retry then 120b, dict correct",
          out == {"t1": ("work", True), "t2": ("shopping", False)}
          and calls == [MINER20, MINER20, MINER120])
    check("classify fallback: fallback meta names 120b",
          _fb_model() == MINER120[1])

# D5. Timeout: skip retry, straight to 120b.
with clean_env():
    reset_run()
    h._llm_call = scripted({MINER20: [err("slow", timed_out=True)],
                            MINER120: ["1|work|yes\n2|shopping|no"]})
    out = h.classify_mail(_rows())
    check("classify timeout: no retry, 120b answers",
          out == {"t1": ("work", True), "t2": ("shopping", False)}
          and calls == [MINER20, MINER120])

# D6a. Legacy fallback-off: tier fallback skipped, borrow leg answers.
# (For miner, unlike low_brain, "off" does NOT raise: the fallback leg
# is skipped and borrow_help runs. The proof it was borrow, not the
# tier fallback, is the absent fallback meta.)
h.FALLBACK_LLM["miner"] = ("groq", "off")
try:
    with clean_env():
        reset_run()
        h._llm_call = scripted({MINER20: [err("down"), err("down")],
                                MINER120: ["1|work|yes\n2|shopping|no"]})
        out = h.classify_mail(_rows())
        check("classify legacy fallback-off: borrow answers, no fallback meta",
              out == {"t1": ("work", True), "t2": ("shopping", False)}
              and calls == [MINER20, MINER20, MINER120] and _fb_model() == "")
finally:
    h.FALLBACK_LLM.clear()
    h.FALLBACK_LLM.update(_orig_fb)

# D6b. Fallback-off + desk on: borrow's desk candidate still goes first.
h.FALLBACK_LLM["miner"] = ("groq", "off")
try:
    with clean_env(ANTHROPIC_API_KEY="sk-test"):
        reset_run()
        h._llm_call = scripted({MINER20: [err("down"), err("down")],
                                MINER120: ["1|work|yes\n2|shopping|no"]})
        CLAUDE_PLAN.append(err("haiku down"))
        out = h.classify_mail(_rows())
        check("classify fallback-off desk-on: Haiku tried first, manager answers",
              out == {"t1": ("work", True), "t2": ("shopping", False)}
              and CLAUDE_CALLS == [HAIKU] and calls == [MINER20, MINER20, MINER120]
              and _fb_model() == "")
finally:
    h.FALLBACK_LLM.clear()
    h.FALLBACK_LLM.update(_orig_fb)

# D6c. ROUTE fallback-off: same outcome via env.
with clean_env(ROUTE_MINER_FALLBACK_MODEL="off"):
    reset_run()
    h._llm_call = scripted({MINER20: [err("down"), err("down")],
                            MINER120: ["1|work|yes\n2|shopping|no"]})
    out = h.classify_mail(_rows())
    check("classify ROUTE fallback-off: borrow answers, no fallback meta",
          out == {"t1": ("work", True), "t2": ("shopping", False)}
          and calls == [MINER20, MINER20, MINER120] and _fb_model() == "")

# D7. Malformed config: half-pair ROUTE var fails fast, no model call.
with clean_env(ROUTE_MINER_MODEL="custom-only"):
    reset_run()
    h._llm_call = scripted({MINER20: ["1|work|yes"], MINER120: []})
    try:
        h.classify_mail(_rows())
        raised = None
    except Exception as e:  # noqa: BLE001 - the point is the type propagates
        raised = type(e).__name__
    check("classify config error: RouteConfigError propagates, no model call",
          raised == "RouteConfigError" and calls == [])

# D8. Fail-fast radius: unrelated-role config error fails this call too.
with clean_env(ROUTE_LOW_BRAIN_PROVIDER="bogus"):
    reset_run()
    h._llm_call = scripted({MINER20: ["1|work|yes"], MINER120: []})
    try:
        h.classify_mail(_rows())
        raised = None
    except Exception as e:  # noqa: BLE001 - the point is the type propagates
        raised = type(e).__name__
    check("classify unrelated config error: RouteConfigError propagates",
          raised == "RouteConfigError" and calls == [])

# D9. Borrow unchanged, desk off: tier legs fail, manager fallback answers.
# (The tried-set skips manager primary — already tried as the tier
# fallback — so borrow's first live leg is the manager fallback.)
with clean_env():
    reset_run()
    h._llm_call = scripted({MINER20: [err("down"), err("down")],
                            MINER120: [err("down")],
                            GEMINIFLASH: ["1|work|yes\n2|shopping|no"]})
    out = h.classify_mail(_rows())
    check("classify borrow desk-off: manager fallback answers, dict correct",
          out == {"t1": ("work", True), "t2": ("shopping", False)}
          and calls == [MINER20, MINER20, MINER120, GEMINIFLASH])
    check("classify borrow desk-off: exactly one route diag (borrow adds none)",
          len(route_diags()) == 1)
    check("classify borrow desk-off: no fallback meta (borrow, not tier fallback)",
          _fb_model() == "")

# D10. Borrow unchanged, desk on: Haiku tried, then manager fallback.
with clean_env(ANTHROPIC_API_KEY="sk-test"):
    reset_run()
    h._llm_call = scripted({MINER20: [err("down"), err("down")],
                            MINER120: [err("down")],
                            GEMINIFLASH: ["1|work|yes\n2|shopping|no"]})
    CLAUDE_PLAN.append(err("haiku down"))
    out = h.classify_mail(_rows())
    check("classify borrow desk-on: Haiku tried, manager fallback answers",
          out == {"t1": ("work", True), "t2": ("shopping", False)}
          and CLAUDE_CALLS == [HAIKU] and calls == [MINER20, MINER20, MINER120, GEMINIFLASH])
    check("classify borrow desk-on: no fallback meta (borrow, not tier fallback)",
          _fb_model() == "")

# E1a. ROUTE_DESK_* set, legacy DESK_MODEL at its default: the route
# decision resolves the ROUTE desk pair into the chain tail, while the
# primary stays the miner pair. (desk_up here is passed exactly as
# classify_mail passes it; the decision itself is side-effect-free.)
with clean_env(ANTHROPIC_API_KEY="sk-test",
               ROUTE_DESK_PROVIDER="anthropic", ROUTE_DESK_MODEL="claude-sonnet-5-5"):
    reset_run()
    check("desk review: legacy DESK_MODEL is the default Haiku",
          h.DESK_MODEL == HAIKU)
    d = h.route("miner", agent=None, entry_point=None,
                desk_up=h.DESK_MODEL.lower() != "off" and h._master_under_cap(),
                master_up=h._master_under_cap())
    check("desk review: ROUTE desk pair sits in the chain tail, primary unchanged",
          d["primary"] == {"provider": "groq", "model": "openai/gpt-oss-20b"}
          and [(c["provider"], c["model"]) for c in d["candidates"]] ==
          [MINER20, MINER120, ("anthropic", "claude-sonnet-5-5"), GEMINIFLASH])
    check("desk review: route decision adds no notify or cap write",
          PUSHED == [] and _capped() == "")

# E1b. Same config through classify_mail, primary success: the ROUTE
# desk pair is never executed (borrow never runs), no Haiku, no notify.
with clean_env(ANTHROPIC_API_KEY="sk-test",
               ROUTE_DESK_PROVIDER="anthropic", ROUTE_DESK_MODEL="claude-sonnet-5-5"):
    reset_run()
    h._llm_call = scripted({MINER20: ["1|work|yes\n2|shopping|no"], MINER120: []})
    out = h.classify_mail(_rows())
    check("desk review: ROUTE desk set, primary success, dict correct",
          out == {"t1": ("work", True), "t2": ("shopping", False)} and calls == [MINER20])
    check("desk review: ROUTE desk set, primary success, no Haiku call",
          CLAUDE_CALLS == [])
    check("desk review: ROUTE desk set, primary success, no notify, one route diag",
          PUSHED == [] and _capped() == "" and len(route_diags()) == 1)

# E2. ROUTE_DESK_* set, desk on, primary + tier fallback fail: borrow
# still uses the LEGACY desk model (Haiku), not the ROUTE desk model,
# and the order is primary, retry, tier fallback, Haiku, manager fallback.
with clean_env(ANTHROPIC_API_KEY="sk-test",
               ROUTE_DESK_PROVIDER="anthropic", ROUTE_DESK_MODEL="claude-sonnet-5-5"):
    reset_run()
    h._llm_call = scripted({MINER20: [err("down"), err("down")],
                            MINER120: [err("down")],
                            GEMINIFLASH: ["1|work|yes\n2|shopping|no"]})
    CLAUDE_PLAN.append(err("haiku down"))
    out = h.classify_mail(_rows())
    check("desk review: ROUTE desk set, borrow order is legacy Haiku then manager fallback",
          out == {"t1": ("work", True), "t2": ("shopping", False)}
          and calls == [MINER20, MINER20, MINER120, GEMINIFLASH])
    check("desk review: borrow desk candidate is legacy Haiku, not the ROUTE model",
          CLAUDE_CALLS == [HAIKU])
    check("desk review: borrow win writes no fallback meta",
          _fb_model() == "")
    check("desk review: under cap, no notify",
          PUSHED == [] and _capped() == "")

# E3. Desk disabled via legacy DESK_MODEL="off", ROUTE_DESK_* still set:
# the ROUTE desk pair leaves the chain, and borrow skips Haiku entirely.
_orig_desk = h.DESK_MODEL
h.DESK_MODEL = "off"
try:
    with clean_env(ANTHROPIC_API_KEY="sk-test",
                   ROUTE_DESK_PROVIDER="anthropic", ROUTE_DESK_MODEL="claude-sonnet-5-5"):
        reset_run()
        d = h.route("miner", agent=None, entry_point=None,
                    desk_up=h.DESK_MODEL.lower() != "off" and h._master_under_cap(),
                    master_up=h._master_under_cap())
        check("desk review: legacy desk off, ROUTE desk pair leaves the chain",
              ("anthropic", "claude-sonnet-5-5") not in
              [(c["provider"], c["model"]) for c in d["candidates"]])
        reset_run()
        h._llm_call = scripted({MINER20: [err("down"), err("down")],
                                MINER120: [err("down")],
                                GEMINIFLASH: ["1|work|yes\n2|shopping|no"]})
        out = h.classify_mail(_rows())
        check("desk review: legacy desk off, order has no Haiku step",
              out == {"t1": ("work", True), "t2": ("shopping", False)}
              and calls == [MINER20, MINER20, MINER120, GEMINIFLASH]
              and CLAUDE_CALLS == [])
        check("desk review: legacy desk off, borrow win writes no fallback meta",
              _fb_model() == "")
finally:
    h.DESK_MODEL = _orig_desk

# E4. Over cap + primary success: the route decision itself never
# triggers the cap notification or the capped write (the pure
# predicate, not master_ready()). Proves no readiness side effect
# from #85, with and without ROUTE_DESK_* set.
for _extra in ({}, {"ROUTE_DESK_PROVIDER": "anthropic", "ROUTE_DESK_MODEL": "claude-sonnet-5-5"}):
    with clean_env(ANTHROPIC_API_KEY="sk-test", **_extra):
        reset_run()
        _set_spend(20.0)
        h._llm_call = scripted({MINER20: ["1|work|yes\n2|shopping|no"], MINER120: []})
        out = h.classify_mail(_rows())
        check("desk review: over cap, primary success, no notify and no cap write",
              out == {"t1": ("work", True), "t2": ("shopping", False)}
              and PUSHED == [] and _capped() == "")

# E5. Over cap + full failure: exactly one cap notice, from the LEGACY
# borrow path (borrow_help -> desk_on() -> master_ready()), which
# predates #85 and is unchanged by it; the route decision adds none
# (proven by E4, where borrow never runs). Haiku is skipped over cap.
with clean_env(ANTHROPIC_API_KEY="sk-test"):
    reset_run()
    _set_spend(20.0)
    h._llm_call = scripted({MINER20: [err("down"), err("down")],
                            MINER120: [err("down")],
                            GEMINIFLASH: ["1|work|yes\n2|shopping|no"]})
    out = h.classify_mail(_rows())
    check("desk review: over cap, full failure, manager fallback answers, no Haiku",
          out == {"t1": ("work", True), "t2": ("shopping", False)}
          and calls == [MINER20, MINER20, MINER120, GEMINIFLASH]
          and CLAUDE_CALLS == [])
    check("desk review: over cap, full failure, exactly one legacy cap notice",
          len(PUSHED) == 1 and PUSHED[0][0] == "Theta" and _capped() == _cap_month())

# E6. Degenerate corner, pinned as accepted: primary == tier-fallback
# model (dedup) makes fallbacks[0] the desk pair when desk_up. That pair
# cannot run as an llm_chat fallback leg (PROVIDERS has no anthropic
# entry — it would raise KeyError, not LLMError), so it maps to
# fallback="off" and borrow tries Haiku properly via claude_chat.
# Desk off: fallbacks[0] is the manager primary and runs as the leg.
with clean_env(ANTHROPIC_API_KEY="sk-test", ROUTE_MINER_FALLBACK_MODEL="openai/gpt-oss-20b"):
    reset_run()
    h._llm_call = scripted({MINER20: [err("down"), err("down")]})
    CLAUDE_PLAN.append("1|work|yes\n2|shopping|no")
    out = h.classify_mail(_rows())
    check("desk review: primary==fallback, desk pair skipped as leg, borrow Haiku answers",
          out == {"t1": ("work", True), "t2": ("shopping", False)}
          and calls == [MINER20, MINER20] and CLAUDE_CALLS == [HAIKU]
          and _fb_model() == "")
h.DESK_MODEL = "off"
try:
    with clean_env(ANTHROPIC_API_KEY="sk-test", ROUTE_MINER_FALLBACK_MODEL="openai/gpt-oss-20b"):
        reset_run()
        h._llm_call = scripted({MINER20: [err("down"), err("down")],
                                MINER120: ["1|work|yes\n2|shopping|no"]})
        out = h.classify_mail(_rows())
        check("desk review: primary==fallback, desk off, fallback leg runs manager primary",
              out == {"t1": ("work", True), "t2": ("shopping", False)}
              and calls == [MINER20, MINER20, MINER120]
              and _fb_model() == MINER120[1])
finally:
    h.DESK_MODEL = _orig_desk

h.FALLBACK_LLM.clear()
h.FALLBACK_LLM.update(_orig_fb)
h._diag = _orig_diag
h._llm_call = _orig_llm
h.claude_chat = _orig_claude
h.notify = _orig_notify
print("test_migration4_classify done")
