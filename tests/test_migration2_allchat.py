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


# --- A. route() D5 hinge: allchat takes the desk path for DESK only ---
with clean_env():
    check("hinge: allchat IS a desk entry point", "allchat" in h.DESK_ENTRY_POINTS)
    d = h.route("low_brain", agent="mistral", entry_point="allchat", desk_up=True, master_up=False)
    check("hinge: mistral allchat desk on is desk path, haiku primary",
          d["path"] == "desk" and (d["primary"]["provider"], d["primary"]["model"]) == ("anthropic", HAIKU))
    check("hinge: mistral allchat desk on chain",
          [(c["provider"], c["model"]) for c in d["candidates"]] == [("anthropic", HAIKU), FLASH, GROQ120])
    d = h.route("low_brain", agent="mistral", entry_point="allchat", desk_up=False, master_up=False)
    check("hinge: mistral allchat desk off is desk path, flash primary",
          d["path"] == "desk" and (d["primary"]["provider"], d["primary"]["model"]) == FLASH)
    d = h.route("low_brain", agent="glass", entry_point="allchat", desk_up=True, master_up=False)
    check("hinge: non-desk agent allchat stays tier path", d["path"] == "tier")

# --- B. desk_chat overrides (migration #2 plumbing) ---
with clean_env():
    reset_run()
    h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
    CLAUDE_PLAN.append("haiku answer")
    out = h.desk_chat([{"role": "user", "content": "hi"}], desk_up=True, desk_model=HAIKU,
                      primary=FLASH, fallback=GROQ120)
    check("desk_chat override: desk leg uses the route desk model",
          out == "haiku answer" and CLAUDE_CALLS == [HAIKU] and calls == [])

with clean_env():
    reset_run()
    h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
    out = h.desk_chat([{"role": "user", "content": "hi"}], desk_up=False, desk_model=None,
                      primary=FLASH, fallback=GROQ120)
    check("desk_chat override: desk_up False skips the desk leg",
          out == "flash answer" and CLAUDE_CALLS == [] and calls == [FLASH])

with clean_env():
    reset_run()
    h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
    CLAUDE_PLAN.append(err("haiku down"))
    out = h.desk_chat([{"role": "user", "content": "hi"}], desk_up=True, desk_model=HAIKU,
                      primary=FLASH, fallback=GROQ120)
    check("desk_chat override: desk failure falls through to the low_brain chain",
          out == "flash answer" and calls == [FLASH])
    check("desk_chat override: fallback meta names the low_brain primary", _fb_model() == FLASH[1])

with clean_env(ANTHROPIC_API_KEY=None):
    reset_run()
    h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
    out = h.desk_chat([{"role": "user", "content": "hi"}])
    check("desk_chat legacy: no key means low_brain chain, no overrides needed",
          out == "flash answer" and CLAUDE_CALLS == [] and calls == [FLASH])

with clean_env(ANTHROPIC_API_KEY="sk-test"):
    reset_run()
    _set_spend(0.0)
    h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
    CLAUDE_PLAN.append("haiku answer")
    out = h.desk_chat([{"role": "user", "content": "hi"}])
    check("desk_chat legacy: key + under cap still takes the desk leg",
          out == "haiku answer" and CLAUDE_CALLS == [HAIKU])

# --- C. allchat_reply unified first turn, both desk states ---
with clean_env(ANTHROPIC_API_KEY="sk-test"):
    reset_run()
    _set_spend(0.0)
    h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
    CLAUDE_PLAN.append("haiku answer")
    out = h.allchat_reply("mistral", thread())
    check("allchat desk on: Haiku answers (D5 unification)",
          out == "haiku answer" and CLAUDE_CALLS == [HAIKU] and calls == [])
    check("allchat desk on: one route diag, haiku primary",
          len(route_diags()) == 1 and route_diags()[0].get("model") == HAIKU)

with clean_env(ANTHROPIC_API_KEY=None):
    reset_run()
    h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
    out = h.allchat_reply("mistral", thread())
    check("allchat desk off: flash answers, exactly as legacy",
          out == "flash answer" and CLAUDE_CALLS == [] and calls == [FLASH])
    check("allchat desk off: one route diag, flash primary",
          len(route_diags()) == 1 and route_diags()[0].get("model") == FLASH[1])

with clean_env(ANTHROPIC_API_KEY="sk-test"):
    reset_run()
    _set_spend(0.0)
    h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
    CLAUDE_PLAN.append("haiku answer")
    out = h.allchat_reply("mistral", thread())
    check("allchat desk on: prompt framing unchanged (All Agents)",
          out == "haiku answer" and CLAUDE_MSGS and "All Agents" in CLAUDE_MSGS[0][0]["content"])

# --- D. Side-effect profile: no master_ready() calls on this path ---
_orig_master_ready = h.master_ready
MR_CALLS = []


def _spy_master_ready():
    MR_CALLS.append(1)
    return _orig_master_ready()


h.master_ready = _spy_master_ready
with clean_env(ANTHROPIC_API_KEY="sk-test"):
    reset_run()
    _set_spend(9999.0)
    MR_CALLS.clear()
    h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
    out = h.allchat_reply("mistral", thread())
    check("side effects, over cap: desk down via flash, no notify, no capped write",
          out == "flash answer" and PUSHED == [] and _capped() == "")
    check("side effects, over cap: master_ready never called", MR_CALLS == [])
with clean_env(ANTHROPIC_API_KEY="sk-test"):
    reset_run()
    _set_spend(0.0)
    MR_CALLS.clear()
    h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
    CLAUDE_PLAN.append("haiku answer")
    out = h.allchat_reply("mistral", thread())
    check("side effects, desk on: Haiku answers with no master_ready call",
          out == "haiku answer" and MR_CALLS == [])
h.master_ready = _orig_master_ready

# --- E. Fallback + failure behavior, unified path ---
with clean_env(ANTHROPIC_API_KEY="sk-test"):
    reset_run()
    _set_spend(0.0)
    h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
    CLAUDE_PLAN.append(err("haiku down"))
    out = h.allchat_reply("mistral", thread())
    check("fallback: Haiku failure is absorbed, flash chain answers",
          out == "flash answer" and calls == [FLASH])
    check("fallback: fallback meta names the flash primary", _fb_model() == FLASH[1])

with clean_env(ANTHROPIC_API_KEY=None):
    reset_run()
    h._llm_call = scripted({FLASH: [err("down"), err("down")], GROQ120: ["groq answer"]})
    out = h.allchat_reply("mistral", thread())
    check("fallback: flash retry then Groq fallback, as legacy",
          out == "groq answer" and calls == [FLASH, FLASH, GROQ120])

with clean_env(ANTHROPIC_API_KEY=None):
    reset_run()
    h._llm_call = scripted({FLASH: [err("slow", timed_out=True)], GROQ120: ["groq answer"]})
    out = h.allchat_reply("mistral", thread())
    check("fallback: timed_out skips the retry, straight to Groq",
          out == "groq answer" and calls == [FLASH, GROQ120])

with clean_env(ANTHROPIC_API_KEY=None):
    reset_run()
    h._llm_call = scripted({FLASH: [err("down"), err("down")], GROQ120: [err("fb down")]})
    try:
        h.allchat_reply("mistral", thread())
        raised = False
    except h.LLMError:
        raised = True
    check("failure: all legs down raises out of allchat, as legacy", raised)

with clean_env(ANTHROPIC_API_KEY=None, ROUTE_LOW_BRAIN_FALLBACK_MODEL="off"):
    reset_run()
    h._llm_call = scripted({FLASH: [err("down"), err("down")], GROQ120: ["groq answer"]})
    try:
        h.allchat_reply("mistral", thread())
        raised = False
    except h.LLMError:
        raised = True
    check("fallback-off (ROUTE): flash down with fallback off raises, no Groq call",
          raised and calls == [FLASH, FLASH])

with clean_env(ANTHROPIC_API_KEY=None):
    reset_run()
    saved = os.environ.get("LOW_BRAIN_FALLBACK_MODEL")
    os.environ["LOW_BRAIN_FALLBACK_MODEL"] = "off"
    # FALLBACK_LLM is import-time frozen: patch the dict entry itself,
    # as a prod deploy with the env var set would build it.
    saved_fb = h.FALLBACK_LLM.get("low_brain")
    h.FALLBACK_LLM["low_brain"] = ("groq", "off")
    try:
        h._llm_call = scripted({FLASH: [err("down"), err("down")], GROQ120: ["groq answer"]})
        try:
            h.allchat_reply("mistral", thread())
            raised = False
        except h.LLMError:
            raised = True
    finally:
        h.FALLBACK_LLM["low_brain"] = saved_fb
        if saved is None:
            os.environ.pop("LOW_BRAIN_FALLBACK_MODEL", None)
        else:
            os.environ["LOW_BRAIN_FALLBACK_MODEL"] = saved
    check("fallback-off (legacy translation): fallback off raises, no Groq call",
          raised and calls == [FLASH, FLASH])

# --- F. Env combinations + non-Mistral unchanged ---
with clean_env(ANTHROPIC_API_KEY="sk-test", ROUTE_DESK_PROVIDER="anthropic",
               ROUTE_DESK_MODEL="claude-sonnet-5-5"):
    reset_run()
    _set_spend(0.0)
    h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
    CLAUDE_PLAN.append("sonnet answer")
    out = h.allchat_reply("mistral", thread())
    check("env: custom ROUTE_DESK pair drives the desk leg",
          out == "sonnet answer" and CLAUDE_CALLS == ["claude-sonnet-5-5"])

with clean_env(ANTHROPIC_API_KEY="sk-test", ROUTE_DESK_MODEL="claude-sonnet-5-5"):
    reset_run()
    _set_spend(0.0)
    try:
        h.allchat_reply("mistral", thread())
        raised = False
    except h.RouteConfigError:
        raised = True
    check("env: ROUTE_DESK_MODEL alone is a half pair and fails the run before any model call",
          raised and calls == [] and CLAUDE_CALLS == [])

with clean_env(ANTHROPIC_API_KEY=None, ROUTE_LOW_BRAIN_PROVIDER="gemini",
               ROUTE_LOW_BRAIN_MODEL="gemini-2.5-flash"):
    reset_run()
    h._llm_call = scripted({("gemini", "gemini-2.5-flash"): ["custom flash answer"], GROQ120: []})
    out = h.allchat_reply("mistral", thread())
    check("env: custom ROUTE_LOW_BRAIN_MODEL drives the desk-off leg",
          out == "custom flash answer" and calls == [("gemini", "gemini-2.5-flash")])

with clean_env(ANTHROPIC_API_KEY="sk-test"):
    reset_run()
    _set_spend(0.0)
    saved_desk = h.DESK_MODEL
    h.DESK_MODEL = "off"
    try:
        h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
        out = h.allchat_reply("mistral", thread())
    finally:
        h.DESK_MODEL = saved_desk
    check("env: DESK_MODEL off means desk down even with a key",
          out == "flash answer" and CLAUDE_CALLS == [])

with clean_env(ANTHROPIC_API_KEY=None):
    reset_run()
    h._llm_call = scripted({GROQ120: ["glass answer"], FLASH: []})
    out = h.allchat_reply("glass", thread())
    check("non-Mistral unchanged: glass still takes her manager tier path, no route diag",
          out == "glass answer" and route_diags() == [])

# --- G. Malformed-response correction (review follow-up) ---
# Promoted from the verification scratch file, adapted to the corrected
# behavior: a malformed Haiku response now FALLS BACK (it escaped
# before the trailing APIError clause landed in claude_request).
# Plus master/Theta regression: the broader claude_request change
# must not bypass the specific handlers.
@contextlib.contextmanager
def fb_write_counter():
    st = h.store()
    orig = st.set_meta
    count = [0]

    def counting(key, value, *a, **k):
        if key == "llm:fallback":
            count[0] += 1
        return orig(key, value, *a, **k)

    st.set_meta = counting
    try:
        yield count
    finally:
        st.set_meta = orig


def _msgs():
    return [{"role": "user", "content": "hi"}]


# G1. Desk leg: every LLMError kind falls through to the low chain.
for _kind, _e in [("timeout", err("slow", timed_out=True)),
                  ("retryable provider error", err("down")),
                  ("non-retryable auth error", err("auth", retryable=False))]:
    with clean_env(ANTHROPIC_API_KEY="sk-test"):
        reset_run()
        h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
        CLAUDE_PLAN.append(_e)
        with fb_write_counter() as _n:
            out = h.allchat_reply("mistral", thread())
        check(f"desk leg {_kind}: absorbed, flash answers, Haiku tried once",
              out == "flash answer" and CLAUDE_CALLS == [HAIKU] and calls == [FLASH])
        check(f"desk leg {_kind}: exactly one fallback-meta write (desk record)",
              _n[0] == 1 and _fb_model() == FLASH[1])
        check(f"desk leg {_kind}: one route diag, no notify, no capped write",
              len(route_diags()) == 1 and PUSHED == [] and _capped() == "")

# G2. Low leg (desk-ON): timeout / retryable / non-retryable.
with clean_env(ANTHROPIC_API_KEY="sk-test"):
    reset_run()
    h._llm_call = scripted({FLASH: [err("slow", timed_out=True)], GROQ120: ["groq answer"]})
    CLAUDE_PLAN.append(err("haiku down"))
    with fb_write_counter() as _n:
        out = h.allchat_reply("mistral", thread())
    check("low leg timeout: skips retry, straight to Groq",
          out == "groq answer" and calls == [FLASH, GROQ120])
    check("low leg timeout: two meta writes (desk record overwritten by low record)",
          _n[0] == 2 and _fb_model() == GROQ120[1])

with clean_env(ANTHROPIC_API_KEY="sk-test"):
    reset_run()
    h._llm_call = scripted({FLASH: [err("down"), err("down")], GROQ120: ["groq answer"]})
    CLAUDE_PLAN.append(err("haiku down"))
    with fb_write_counter() as _n:
        out = h.allchat_reply("mistral", thread())
    check("low leg retryable: one retry, then Groq",
          out == "groq answer" and calls == [FLASH, FLASH, GROQ120])
    check("low leg retryable: two meta writes, final record is Groq",
          _n[0] == 2 and _fb_model() == GROQ120[1])

with clean_env(ANTHROPIC_API_KEY="sk-test"):
    reset_run()
    h._llm_call = scripted({FLASH: [err("auth", retryable=False)], GROQ120: ["groq answer"]})
    CLAUDE_PLAN.append(err("haiku down"))
    with fb_write_counter() as _n:
        try:
            h.allchat_reply("mistral", thread())
            raised = False
        except h.LLMError:
            raised = True
    check("low leg non-retryable: raises at once, no retry, no Groq",
          raised and calls == [FLASH])
    check("low leg non-retryable: exactly one meta write (desk record only)",
          _n[0] == 1 and _fb_model() == FLASH[1])

# G3. Desk-OFF malformed: raises, no fallback, no side effects.
with clean_env():
    reset_run()
    h._llm_call = scripted({FLASH: [err("garbage", retryable=False)], GROQ120: ["groq answer"]})
    with fb_write_counter() as _n:
        try:
            h.allchat_reply("mistral", thread())
            raised = False
        except h.LLMError:
            raised = True
    check("desk-off malformed (non-retryable): raises, no Groq, no meta write",
          raised and calls == [FLASH] and _n[0] == 0 and _fb_model() == "")

# G4. Malformed Haiku response FALLS BACK after the correction.
# Real claude_request + real claude_chat; only the SDK client is stubbed
# to raise a validation error, so the trailing APIError clause is what
# converts it. (Before the correction this escaped desk_chat raw.)
import anthropic as _anthropic
_caught_specific = (_anthropic.AuthenticationError, _anthropic.PermissionDeniedError,
                    _anthropic.NotFoundError, _anthropic.RateLimitError,
                    _anthropic.APIStatusError, _anthropic.APIConnectionError)
check("correction: validation error is an APIError but not a specifically-handled one",
      issubclass(_anthropic.APIResponseValidationError, _anthropic.APIError)
      and not issubclass(_anthropic.APIResponseValidationError, _caught_specific))


class _FakeSDKResp:
    def __init__(self):
        self.request = type("Req", (), {"method": "POST",
                                        "url": "https://api.anthropic.com/v1/messages"})()
        self.status_code = 200
        self.headers = {}


class _RaisingMsgs:
    def __init__(self, exc):
        self._exc = exc

    def create(self, *a, **k):
        raise self._exc


class _RaisingClient:
    def __init__(self, exc):
        self.messages = _RaisingMsgs(exc)
        # Master/Theta calls go through client.beta.messages.create
        # (server-side fallback); desk calls use client.messages.create.
        self.beta = type("Beta", (), {"messages": _RaisingMsgs(exc)})()


_orig_client = h._anthropic_client
with clean_env(ANTHROPIC_API_KEY="sk-test"):
    reset_run()
    h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
    h._anthropic_client = lambda max_retries=1: _RaisingClient(
        _anthropic.APIResponseValidationError(_FakeSDKResp(), {"id": "x"}))
    _harness_fake_claude = h.claude_chat
    h.claude_chat = _orig_claude
    try:
        with fb_write_counter() as _n:
            out = h.allchat_reply("mistral", thread())
    finally:
        h._anthropic_client = _orig_client
        h.claude_chat = _harness_fake_claude
    check("malformed Haiku falls back: flash answers, route diag names Haiku",
          out == "flash answer" and calls == [FLASH]
          and len(route_diags()) == 1 and route_diags()[0].get("model") == HAIKU)
    check("malformed Haiku falls back: desk meta written, no notify",
          _n[0] == 1 and _fb_model() == FLASH[1] and PUSHED == [])

# G5. Master/Theta regression: specific handlers still win, stand-in works.
def _master_block(sdk_exc, expect_substr):
    with clean_env(ANTHROPIC_API_KEY="sk-test"):
        reset_run()
        h.store().set_meta("claude:last_error", "")
        h._llm_call = scripted({FLASH: ["flash answer"], GROQ120: []})
        h._anthropic_client = lambda max_retries=1: _RaisingClient(sdk_exc)
        _harness_fake_claude = h.claude_chat
        h.claude_chat = _orig_claude
        try:
            out = h.llm_chat("master", _msgs())
        finally:
            h._anthropic_client = _orig_client
            h.claude_chat = _harness_fake_claude
        raw = h.store().get_meta("claude:last_error") or "{}"
        err_text = json.loads(raw).get("error", "") if raw else ""
        return out, err_text


_out, _err_text = _master_block(
    _anthropic.APIResponseValidationError(_FakeSDKResp(), {"id": "x"}), "")
check("master regression: validation error falls back to flash stand-in",
      _out == "flash answer" and calls == [FLASH] and _err_text != "")
_out, _err_text = _master_block(
    _anthropic.AuthenticationError("bad key", response=_FakeSDKResp(), body=None), "rejected")
check("master regression: auth error still uses the specific handler",
      _out == "flash answer" and "rejected" in _err_text)
_out, _err_text = _master_block(
    _anthropic.RateLimitError("slow", response=_FakeSDKResp(), body=None), "rate limit")
check("master regression: rate-limit error still uses the specific handler",
      _out == "flash answer" and "rate limit" in _err_text)

# G6. Real _llm_call error mapping (LAST: the 429 case writes a cooldown).
import io as _io
import urllib.request as _urlreq
import urllib.error as _urlerr


class _Resp:
    def __init__(self, data):
        self._data = data
        self.headers = {}

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_orig_urlopen = _urlreq.urlopen


def _run_mapping(stub, expect_retryable, expect_timed_out, label):
    _urlreq.urlopen = stub
    try:
        _orig_llm("gemini", "gemini-3.8-flash", _msgs(), 800)
        got = None
    except h.LLMError as e:
        got = (e.retryable, e.timed_out)
    except Exception as e:  # noqa: BLE001 - mapping must produce LLMError, anything else fails
        got = ("WRONG-TYPE", type(e).__name__)
    finally:
        _urlreq.urlopen = _orig_urlopen
    check(f"mapping {label}: LLMError retryable={expect_retryable} timed_out={expect_timed_out}",
          got == (expect_retryable, expect_timed_out))


with clean_env():
    reset_run()
    _run_mapping(lambda req, timeout=None: (_ for _ in ()).throw(
        _urlerr.HTTPError(req.full_url, 500, "boom", {}, _io.BytesIO(b"{}"))),
        True, False, "HTTP 500 -> retryable, not timed_out (one retry)")
    _run_mapping(lambda req, timeout=None: (_ for _ in ()).throw(
        _urlerr.HTTPError(req.full_url, 401, "no", {}, _io.BytesIO(b"{}"))),
        False, False, "HTTP 401 -> non-retryable (raise, no fallback)")
    _run_mapping(lambda req, timeout=None: (_ for _ in ()).throw(TimeoutError("slow")),
        True, True, "TimeoutError -> retryable + timed_out")
    _run_mapping(lambda req, timeout=None: _Resp(b"not json"),
        False, False, "malformed JSON -> non-retryable (raise, no fallback)")
    _run_mapping(lambda req, timeout=None: _Resp(b'{"foo": 1}'),
        False, False, "malformed shape (no choices) -> non-retryable (raise, no fallback)")
    _run_mapping(lambda req, timeout=None: (_ for _ in ()).throw(
        _urlerr.HTTPError(req.full_url, 429, "slow", {}, _io.BytesIO(b"{}"))),
        True, True, "HTTP 429 -> retryable + timed_out (skip retry, cooldown)")
    h.store().set_meta("llm:cooldown", "{}")

h._diag = _orig_diag
h._llm_call = _orig_llm
h.claude_chat = _orig_claude
h.notify = _orig_notify
print("test_migration2_allchat done")
