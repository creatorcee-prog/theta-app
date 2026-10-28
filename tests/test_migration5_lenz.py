"""Stage 4 P1 migration #5: _lenz_pitch primary/fallback via route().

Proves the migrated miner call preserves behavior: same prompt, same
retry/timeout/fallback/error handling, with the borrow chain untouched
(still legacy settings). Only _lenz_pitch's primary/fallback selection
is migrated; every other call site is untouched. A routing failure
(RouteConfigError) escapes _lenz_pitch to _round_lenz (which catches
LLMError only) and then to run_round, which catches ValueError — so a
malformed ROUTE_* config records a lenz job failure, loud, not a
silent "no pitch" note.

Stubs: _llm_call scripted per (provider, model); claude_chat stubbed
(for the borrow desk candidate); _diag recorded; notify spied;
tmdb_trending/widget_items stubbed (no live network). Both modes take
sys.argv[1] ("memory"/"redis"), as run_all.sh passes it.
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
os.environ.update(DASHBOARD_KEY="dk", ANTHROPIC_API_KEY="",
                  GROQ_API_KEY="fake-groq", GEMINI_API_KEY="fake-gemini")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="fake")
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
    os.environ.update(DASHBOARD_KEY="dk", ANTHROPIC_API_KEY="",
                      GROQ_API_KEY="fake-groq", GEMINI_API_KEY="fake-gemini")
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


def reset_run():
    diags.clear()
    calls.clear()
    CLAUDE_CALLS.clear()
    CLAUDE_PLAN.clear()
    CLAUDE_MSGS.clear()
    PUSHED.clear()
    h.store().set_meta("llm:fallback", "")
    h.store().set_meta("claude:capped", "")
    h.store().set_meta("round:lenz:seen", "[]")
    _set_spend(0.0)


_orig_tmdb = h.tmdb_trending
_orig_widget = h.widget_items


def _item(url):
    return {"title": "Test Film", "url": url, "overview": "A test overview.", "image": None,
            "kind": "movie", "date": "2026-01-01", "rating": 8.0}


MINER20 = ("groq", "openai/gpt-oss-20b")
MINER120 = ("groq", "openai/gpt-oss-120b")
GEMINIFLASH = ("gemini", "gemini-3.8-flash")
HAIKU = "claude-haiku-5-5"
_orig_fb = dict(h.FALLBACK_LLM)
_orig_desk = h.DESK_MODEL

# L1. Defaults: one miner call, one route diag, pitch posted, no side effects.
with clean_env():
    reset_run()
    h.tmdb_trending = lambda: [_item("https://example.com/t1")]
    h.widget_items = lambda feeds: []
    h._llm_call = scripted({MINER20: ["Worth a watch."], MINER120: []})
    out = h._lenz_pitch()
    check("lenz defaults: pitched, miner 20b once, one route diag",
          out == 'pitched "Test Film"' and calls == [MINER20] and len(route_diags()) == 1)
    cards = json.loads(h.store().get_meta("cards") or "{}")
    check("lenz defaults: card posted, no notify, no cap write, no Haiku",
          cards.get("lenz", {}).get("title") == "Test Film"
          and PUSHED == [] and _capped() == "" and CLAUDE_CALLS == [])

# L2. Nothing new: no model call, no route decision.
with clean_env():
    reset_run()
    h.tmdb_trending = lambda: []
    h.widget_items = lambda feeds: []
    h._llm_call = scripted({MINER20: ["Worth a watch."], MINER120: []})
    out = h._lenz_pitch()
    check("lenz nothing new: no pitch, no model call, no route diag",
          out == "nothing new to pitch" and calls == [] and route_diags() == [])

# L3. Retryable failure: one retry, then 120b fallback with meta.
with clean_env():
    reset_run()
    h.tmdb_trending = lambda: [_item("https://example.com/t3")]
    h.widget_items = lambda feeds: []
    h._llm_call = scripted({MINER20: [err("down"), err("down")], MINER120: ["Worth a watch."]})
    out = h._lenz_pitch()
    check("lenz fallback: retry then 120b, pitched",
          out == 'pitched "Test Film"' and calls == [MINER20, MINER20, MINER120])
    check("lenz fallback: fallback meta names 120b", _fb_model() == MINER120[1])

# L4. Timeout: skip retry, straight to 120b.
with clean_env():
    reset_run()
    h.tmdb_trending = lambda: [_item("https://example.com/t4")]
    h.widget_items = lambda feeds: []
    h._llm_call = scripted({MINER20: [err("slow", timed_out=True)], MINER120: ["Worth a watch."]})
    out = h._lenz_pitch()
    check("lenz timeout: no retry, 120b answers",
          out == 'pitched "Test Film"' and calls == [MINER20, MINER120])

# L5. Legacy fallback-off: tier fallback skipped, borrow leg answers.
h.FALLBACK_LLM["miner"] = ("groq", "off")
try:
    with clean_env():
        reset_run()
        h.tmdb_trending = lambda: [_item("https://example.com/t5")]
        h.widget_items = lambda feeds: []
        h._llm_call = scripted({MINER20: [err("down"), err("down")], MINER120: ["Worth a watch."]})
        out = h._lenz_pitch()
        check("lenz legacy fallback-off: borrow answers, no fallback meta",
              out == 'pitched "Test Film"' and calls == [MINER20, MINER20, MINER120] and _fb_model() == "")
finally:
    h.FALLBACK_LLM.clear()
    h.FALLBACK_LLM.update(_orig_fb)

# L6. ROUTE fallback-off: same outcome via env.
with clean_env(ROUTE_MINER_FALLBACK_MODEL="off"):
    reset_run()
    h.tmdb_trending = lambda: [_item("https://example.com/t6")]
    h.widget_items = lambda feeds: []
    h._llm_call = scripted({MINER20: [err("down"), err("down")], MINER120: ["Worth a watch."]})
    out = h._lenz_pitch()
    check("lenz ROUTE fallback-off: borrow answers, no fallback meta",
          out == 'pitched "Test Film"' and calls == [MINER20, MINER20, MINER120] and _fb_model() == "")

# L7. Malformed config: half-pair ROUTE var fails fast, no model call.
with clean_env(ROUTE_MINER_MODEL="custom-only"):
    reset_run()
    h.tmdb_trending = lambda: [_item("https://example.com/t7")]
    h.widget_items = lambda feeds: []
    h._llm_call = scripted({MINER20: ["Worth a watch."], MINER120: []})
    try:
        h._lenz_pitch()
        raised = None
    except Exception as e:  # noqa: BLE001 - the point is the type propagates
        raised = type(e).__name__
    check("lenz config error: RouteConfigError propagates, no model call",
          raised == "RouteConfigError" and calls == [])

# L8. Fail-fast radius: unrelated-role config error fails this call too.
with clean_env(ROUTE_LOW_BRAIN_PROVIDER="bogus"):
    reset_run()
    h.tmdb_trending = lambda: [_item("https://example.com/t8")]
    h.widget_items = lambda feeds: []
    h._llm_call = scripted({MINER20: ["Worth a watch."], MINER120: []})
    try:
        h._lenz_pitch()
        raised = None
    except Exception as e:  # noqa: BLE001 - the point is the type propagates
        raised = type(e).__name__
    check("lenz unrelated config error: RouteConfigError propagates",
          raised == "RouteConfigError")

# L9. ROUTE_DESK_* set, legacy DESK_MODEL at default, primary success:
# the ROUTE desk pair is never executed (borrow never runs).
with clean_env(ANTHROPIC_API_KEY="sk-test",
               ROUTE_DESK_PROVIDER="anthropic", ROUTE_DESK_MODEL="claude-sonnet-5-5"):
    reset_run()
    h.tmdb_trending = lambda: [_item("https://example.com/t9")]
    h.widget_items = lambda feeds: []
    h._llm_call = scripted({MINER20: ["Worth a watch."], MINER120: []})
    out = h._lenz_pitch()
    check("lenz ROUTE desk set: primary success, miner once, one route diag",
          out == 'pitched "Test Film"' and calls == [MINER20] and len(route_diags()) == 1)
    check("lenz ROUTE desk set: no Haiku call, no notify",
          CLAUDE_CALLS == [] and PUSHED == [])

# L10. Degenerate corner (from the #85 review fix): primary == fallback
# model, desk_up: the desk pair maps to fallback="off" and borrow tries
# Haiku properly via claude_chat instead of crashing the fallback leg.
with clean_env(ANTHROPIC_API_KEY="sk-test", ROUTE_MINER_FALLBACK_MODEL="openai/gpt-oss-20b"):
    reset_run()
    h.tmdb_trending = lambda: [_item("https://example.com/t10")]
    h.widget_items = lambda feeds: []
    h._llm_call = scripted({MINER20: [err("down"), err("down")]})
    CLAUDE_PLAN.append("Worth a watch.")
    out = h._lenz_pitch()
    check("lenz primary==fallback, desk up: borrow Haiku answers, no fallback meta",
          out == 'pitched "Test Film"' and calls == [MINER20, MINER20]
          and CLAUDE_CALLS == [HAIKU] and _fb_model() == "")

# L11. Same corner, desk off: fallback leg runs the manager primary.
h.DESK_MODEL = "off"
try:
    with clean_env(ANTHROPIC_API_KEY="sk-test", ROUTE_MINER_FALLBACK_MODEL="openai/gpt-oss-20b"):
        reset_run()
        h.tmdb_trending = lambda: [_item("https://example.com/t11")]
        h.widget_items = lambda feeds: []
        h._llm_call = scripted({MINER20: [err("down"), err("down")], MINER120: ["Worth a watch."]})
        out = h._lenz_pitch()
        check("lenz primary==fallback, desk off: manager primary runs as fallback leg",
              out == 'pitched "Test Film"' and calls == [MINER20, MINER20, MINER120]
              and _fb_model() == MINER120[1])
finally:
    h.DESK_MODEL = _orig_desk

# L12. Over cap + primary success: the route decision itself never
# triggers the cap notification or the capped write.
for _extra in ({}, {"ROUTE_DESK_PROVIDER": "anthropic", "ROUTE_DESK_MODEL": "claude-sonnet-5-5"}):
    with clean_env(ANTHROPIC_API_KEY="sk-test", **_extra):
        reset_run()
        _set_spend(20.0)
        h.tmdb_trending = lambda: [_item("https://example.com/t12")]
        h.widget_items = lambda feeds: []
        h._llm_call = scripted({MINER20: ["Worth a watch."], MINER120: []})
        out = h._lenz_pitch()
        check("lenz over cap, primary success, no notify and no cap write",
              out == 'pitched "Test Film"' and PUSHED == [] and _capped() == "")

# L13. Over cap + full failure: exactly one cap notice, from the LEGACY
# borrow path (borrow_help -> desk_on() -> master_ready()), which
# predates this migration and is unchanged by it; Haiku skipped over cap.
with clean_env(ANTHROPIC_API_KEY="sk-test"):
    reset_run()
    _set_spend(20.0)
    h.tmdb_trending = lambda: [_item("https://example.com/t13")]
    h.widget_items = lambda feeds: []
    h._llm_call = scripted({MINER20: [err("down"), err("down")],
                            MINER120: [err("down")],
                            GEMINIFLASH: ["Worth a watch."]})
    out = h._lenz_pitch()
    check("lenz over cap, full failure, manager fallback answers, no Haiku",
          out == 'pitched "Test Film"' and calls == [MINER20, MINER20, MINER120, GEMINIFLASH]
          and CLAUDE_CALLS == [])
    check("lenz over cap, full failure, exactly one legacy cap notice",
          len(PUSHED) == 1 and PUSHED[0][0] == "Theta" and _capped() == _cap_month())

h.FALLBACK_LLM.clear()
h.FALLBACK_LLM.update(_orig_fb)
h._diag = _orig_diag
h._llm_call = _orig_llm
h.claude_chat = _orig_claude
h.notify = _orig_notify
h.tmdb_trending = _orig_tmdb
h.widget_items = _orig_widget
print("test_migration5_lenz done")
