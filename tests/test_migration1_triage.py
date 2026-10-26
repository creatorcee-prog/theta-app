"""Stage 4 P1 migration #1: _triage_escalations low_brain via route().

Proves the migrated site preserves legacy selection, fallback and
failure behavior, and pins the route() fallback_off contract extension.
No production path calls route() except the migrated triage site, and
no other call site is touched by this PR.

Stubs: _llm_call scripted per (provider, model); _diag recorded.
No live network: the only HTTP is the fake Upstash server in redis
mode, as in the other test files. Both modes take sys.argv[1]
("memory"/"redis"), as run_all.sh passes it.

Env hygiene: route() reads ROUTE_* vars at call time, so every test
runs inside clean_env(), which pops all ROUTE_* vars (plus the key
vars a test deliberately dirties) and restores them after.
"""
import sys, json, time, os, contextlib
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


def msgs():
    return [{"role": "user", "content": "hi"}]


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


def selected():
    return [(f.get("via"), f.get("model")) for s, f in diags if s == "model.selected"]


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


def fb_meta():
    return h.store().get_meta("llm:fallback") or ""


def fb_meta_cmp():
    # Compare the meaningful fields only: "at" timestamps differ run to run.
    raw = fb_meta()
    if not raw:
        return ""
    d = json.loads(raw)
    return (d.get("tier"), d.get("model"), d.get("why"))


def reset_run():
    diags.clear()
    calls.clear()
    h.store().set_meta("llm:fallback", "")
    h.store().set_meta("llm:last_selection", "sentinel")


FLASH = ("gemini", "gemini-3.8-flash")
FB120 = ("groq", "openai/gpt-oss-120b")


# --- A. route() fallback_off parameter (contract extension) ---
with clean_env():
    d = h.route("low_brain", desk_up=False, master_up=False)
    check("fallback_off default: env behavior (default fallback present)",
          [(c["provider"], c["model"]) for c in d["fallbacks"]] == [FB120])
with clean_env():
    d = h.route("low_brain", desk_up=False, master_up=False, fallback_off=("low_brain",))
    check("fallback_off param suppresses the fallback step", d["fallbacks"] == [])
with clean_env(ROUTE_LOW_BRAIN_FALLBACK_MODEL="groq-custom"):
    d = h.route("low_brain", desk_up=False, master_up=False, fallback_off=("low_brain",))
    check("fallback_off param wins over a ROUTE_* fallback model", d["fallbacks"] == [])
with clean_env(ROUTE_LOW_BRAIN_FALLBACK_MODEL="groq-custom"):
    d = h.route("low_brain", desk_up=False, master_up=False)
    check("no param: ROUTE_* fallback model is used",
          [(c["provider"], c["model"]) for c in d["fallbacks"]] == [("groq", "groq-custom")])
with clean_env(ROUTE_LOW_BRAIN_FALLBACK_MODEL="off"):
    d = h.route("low_brain", desk_up=False, master_up=False)
    check("no param: ROUTE_* fallback off still suppresses", d["fallbacks"] == [])
with clean_env():
    d = h.route("low_brain", desk_up=False, master_up=False, fallback_off=("miner",))
    check("fallback_off is per-role: miner off does not suppress low_brain",
          [(c["provider"], c["model"]) for c in d["fallbacks"]] == [FB120])
with clean_env():
    try:
        h.route("low_brain", desk_up=False, master_up=False, fallback_off=("master",))
        ok = False
    except h.RouteConfigError:
        ok = True
    check("fallback_off with a role that has no fallback var raises", ok)
with clean_env():
    try:
        h.route("low_brain", desk_up=False, master_up=False, fallback_off=("nope",))
        ok = False
    except h.RouteConfigError:
        ok = True
    check("fallback_off with an unknown role raises", ok)
with clean_env():
    d = h.route("low_brain", desk_up=False, master_up=False, fallback_off=None)
    check("fallback_off None means env behavior",
          [(c["provider"], c["model"]) for c in d["fallbacks"]] == [FB120])


# --- B. llm_chat primary/fallback overrides (low_brain) ---
def run_llm(plan, **kw):
    reset_run()
    h._llm_call = scripted(plan)
    try:
        return ("ok", h.llm_chat("low_brain", msgs(), **kw))
    except Exception as e:  # noqa: BLE001 - the test compares the raised error
        return ("raise", f"{type(e).__name__}: {e}")


with clean_env():
    status, text = run_llm({("gemini", "custom-prim"): ["prim-ok"]}, primary=("gemini", "custom-prim"))
    check("override primary is used", status == "ok" and text == "prim-ok"
          and calls == [("gemini", "custom-prim")]
          and selected() == [("primary", "custom-prim")])
with clean_env():
    status, text = run_llm({FLASH: [err("down"), err("down")], FB120: ["fb-ok"]},
                           fallback=FB120)
    check("override fallback is used after primary fails",
          status == "ok" and text == "fb-ok" and calls == [FLASH, FLASH, FB120]
          and selected() == [("tier_fallback", "openai/gpt-oss-120b")]
          and json.loads(fb_meta())["model"] == "openai/gpt-oss-120b")
with clean_env():
    status, text = run_llm({FLASH: [err("down"), err("down")]}, fallback="off")
    check("fallback off suppresses the fallback step",
          status == "raise" and calls == [FLASH, FLASH] and fb_meta() == "")
with clean_env(GROQ_API_KEY=None):
    status, text = run_llm({FLASH: [err("down"), err("down")]})
    check("fallback skipped when its provider key is missing",
          status == "raise" and calls == [FLASH, FLASH])
with clean_env():
    status, text = run_llm({FLASH: [err("fatal", retryable=False)]})
    check("non-retryable primary raises at once, no retry, no fallback",
          status == "raise" and calls == [FLASH])
with clean_env():
    status, text = run_llm({FLASH: [err("429", timed_out=True)], FB120: ["fb-ok"]})
    check("timed_out primary skips the retry but still tries the fallback",
          status == "ok" and text == "fb-ok" and calls == [FLASH, FB120])
with clean_env():
    saved_room = dict(h._ROOM)
    h._ROOM["openai/gpt-oss-120b"] = {"left": 0, "until": time.time() + 120}
    try:
        status, text = run_llm({FLASH: [err("down"), err("down")]})
    finally:
        h._ROOM.clear()
        h._ROOM.update(saved_room)
    check("room-exhausted fallback is skipped, never called",
          status == "raise" and calls == [FLASH, FLASH])


# --- C. Equivalence: legacy llm_chat vs migrated route()+overrides ---
def site_fallback_off():
    return ("low_brain",) if h.FALLBACK_LLM.get("low_brain", (None, "off"))[1] == "off" else ()


def migrated(plan):
    reset_run()
    h._llm_call = scripted(plan)
    d = h.route("low_brain", agent=None, entry_point=None,
                desk_up=False, master_up=False, fallback_off=site_fallback_off())
    prim = (d["primary"]["provider"], d["primary"]["model"])
    fb = d["fallbacks"][0] if d["fallbacks"] else "off"
    fb = (fb["provider"], fb["model"]) if fb != "off" else "off"
    try:
        return ("ok", h.llm_chat("low_brain", msgs(), primary=prim, fallback=fb))
    except Exception as e:  # noqa: BLE001
        return ("raise", f"{type(e).__name__}: {e}")


def legacy(plan):
    reset_run()
    h._llm_call = scripted(plan)
    try:
        return ("ok", h.llm_chat("low_brain", msgs()))
    except Exception as e:  # noqa: BLE001
        return ("raise", f"{type(e).__name__}: {e}")


def equivalence(name, plan_factory, env=None, legacy_fb=None):
    saved_fb = h.FALLBACK_LLM["low_brain"]
    if legacy_fb is not None:
        h.FALLBACK_LLM["low_brain"] = legacy_fb
    try:
        with clean_env(**(env or {})):
            lres = legacy(plan_factory())
            lattempts, lnotes, lmeta = list(calls), selected(), fb_meta_cmp()
            mres = migrated(plan_factory())
            mattempts = list(calls)
            mnotes = [n for n in selected() if n[0] != "route"]
            mmeta = fb_meta_cmp()
            mroute = route_diags()
    finally:
        h.FALLBACK_LLM["low_brain"] = saved_fb
    check(f"equiv {name}: same outcome", lres == mres)
    check(f"equiv {name}: same attempt order", lattempts == mattempts)
    check(f"equiv {name}: same executor notes", lnotes == mnotes)
    check(f"equiv {name}: same fallback meta", lmeta == mmeta)
    check(f"equiv {name}: migrated emits one route diag", len(mroute) == 1)


equivalence("primary success", lambda: {FLASH: ["ok"]})
equivalence("retry success", lambda: {FLASH: [err("down"), "ok"]})
equivalence("fallback success",
            lambda: {FLASH: [err("down"), err("down")], FB120: ["fb-ok"]})
equivalence("all fail",
            lambda: {FLASH: [err("down"), err("down")], FB120: [err("fb down")]})
equivalence("fallback off via legacy translation",
            lambda: {FLASH: [err("down"), err("down")]},
            legacy_fb=("groq", "off"))


# --- C2. Authority: migrated follows route() config, not legacy vars ---
# (These pin the intended authority rule, so they assert DIFFERENT
# attempts for legacy vs migrated where the configs differ. They are
# not equivalence cases.)
def run_migrated_only(plan, env):
    with clean_env(**env):
        mres = migrated(plan)
        return mres, list(calls)


def run_legacy_only(plan):
    with clean_env():
        lres = legacy(plan)
        return lres, list(calls)


def authority_route_override():
    saved_prim, saved_fb = h.TIER_LLM["low_brain"], h.FALLBACK_LLM["low_brain"]
    h.TIER_LLM["low_brain"] = ("gemini", "legacy-custom")
    h.FALLBACK_LLM["low_brain"] = ("groq", "legacy-fb")
    try:
        _, mattempts = run_migrated_only(
            {("gemini", "gemini-custom"): [err("down"), err("down")],
             ("groq", "groq-custom"): [err("x")]},
            {"ROUTE_LOW_BRAIN_PROVIDER": "gemini", "ROUTE_LOW_BRAIN_MODEL": "gemini-custom",
             "ROUTE_LOW_BRAIN_FALLBACK_MODEL": "groq-custom"})
        _, lattempts = run_legacy_only(
            {("gemini", "legacy-custom"): [err("down"), err("down")],
             ("groq", "legacy-fb"): [err("x")]})
    finally:
        h.TIER_LLM["low_brain"], h.FALLBACK_LLM["low_brain"] = saved_prim, saved_fb
    check("authority ROUTE_* overrides: migrated uses route() models",
          mattempts == [("gemini", "gemini-custom")] * 2 + [("groq", "groq-custom")])
    check("authority ROUTE_* overrides: legacy uses legacy models",
          lattempts == [("gemini", "legacy-custom")] * 2 + [("groq", "legacy-fb")])


def authority_legacy_custom_alone():
    saved_prim, saved_fb = h.TIER_LLM["low_brain"], h.FALLBACK_LLM["low_brain"]
    h.TIER_LLM["low_brain"] = ("gemini", "legacy-custom")
    h.FALLBACK_LLM["low_brain"] = ("groq", "legacy-fb")
    try:
        _, mattempts = run_migrated_only(
            {FLASH: [err("down"), err("down")], FB120: [err("x")]}, {})
        _, lattempts = run_legacy_only(
            {("gemini", "legacy-custom"): [err("down"), err("down")],
             ("groq", "legacy-fb"): [err("x")]})
    finally:
        h.TIER_LLM["low_brain"], h.FALLBACK_LLM["low_brain"] = saved_prim, saved_fb
    check("authority legacy custom alone: migrated still uses route() defaults",
          mattempts == [FLASH, FLASH, FB120])
    check("authority legacy custom alone: legacy uses its custom models",
          lattempts == [("gemini", "legacy-custom")] * 2 + [("groq", "legacy-fb")])


def authority_route_fb_model():
    _, mattempts = run_migrated_only(
        {FLASH: [err("down"), err("down")], ("groq", "groq-custom"): ["fb-ok"]},
        {"ROUTE_LOW_BRAIN_FALLBACK_MODEL": "groq-custom"})
    _, lattempts = run_legacy_only(
        {FLASH: [err("down"), err("down")], FB120: ["fb-ok"]})
    check("authority ROUTE_* fallback model: migrated uses it",
          mattempts == [FLASH, FLASH, ("groq", "groq-custom")])
    check("authority ROUTE_* fallback model: legacy uses its own fallback",
          lattempts == [FLASH, FLASH, FB120])


authority_route_override()
authority_legacy_custom_alone()
authority_route_fb_model()


# --- D. Site end-to-end: _triage_escalations ---
def seed_escalation(issue):
    st = h.store()
    return st.add_escalation("qwerty", "miner", "low_brain", issue, {}, "open")


def triaged_ids():
    return set(json.loads(h.store().get_meta("mistral:triaged") or "[]"))


with clean_env():
    diags.clear()
    eid = seed_escalation("handled issue")
    h._llm_call = scripted({FLASH: ["handled reply"], FB120: []})
    did = []
    h._triage_escalations(did)
    check("site handled: did records the escalation", did == [f"handled #{eid}"])
    check("site handled: escalation marked triaged", eid in triaged_ids())
    check("site handled: chat records the reply",
          any(f"On #{eid}" in (m.get("text") or "") for m in h.store().list_chat(200)))
    check("site handled: one route diag for the run",
          len(route_diags()) == 1 and route_diags()[0].get("model") == "gemini-3.8-flash")

with clean_env():
    eid = seed_escalation("theta issue")
    h._llm_call = scripted({FLASH: ["THETA: needs a decision"], FB120: []})
    did = []
    h._triage_escalations(did)
    check("site forward: did records the forward", did == [f"forwarded #{eid} to Theta"])
    check("site forward: a master escalation is created",
          any(e.get("to_role") == "master" and e.get("context", {}).get("from_escalation") == eid
              for e in h.store().list_escalations(50)))
    check("site forward: escalation marked triaged", eid in triaged_ids())

with clean_env():
    eid = seed_escalation("failing issue")
    h._llm_call = scripted({FLASH: [err("down"), err("down")], FB120: [err("fb down")]})
    did = []
    try:
        h._triage_escalations(did)
        raised = False
    except h.LLMError:
        raised = True
    check("site failure: model error propagates out of triage", raised and did == [])
    check("site failure: failed escalation is not marked triaged", eid not in triaged_ids())

# --- E. Review correction: triage never triggers the cap notification ---
# master_ready() writes claude:capped meta + notify() once a month when
# over cap; legacy triage never called it. The site now computes
# desk_up/master_up with the pure _master_under_cap() predicate, so a
# low_brain-only run cannot produce that side effect. route() itself
# is untouched by this correction.
_orig_notify = h.notify
PUSHED = []
h.notify = lambda title, body, url="/": PUSHED.append((title, body, url)) or 1


def _cap_month():
    return h.datetime.now(h.hub_tz()).strftime("%Y-%m")


def _set_spend(usd):
    h.store().set_meta("claude:spend", json.dumps({_cap_month(): {"usd": usd, "calls": 0, "input": 0, "output": 0}}))


def _capped():
    return h.store().get_meta("claude:capped") or ""


with clean_env(ANTHROPIC_API_KEY=None):
    h.store().set_meta("claude:capped", "")
    PUSHED.clear()
    check("pure predicate, no key: False", h._master_under_cap() is False)
    check("pure predicate, no key: no meta write, no notify", _capped() == "" and PUSHED == [])

with clean_env(ANTHROPIC_API_KEY="sk-test"):
    _set_spend(0.0)
    h.store().set_meta("claude:capped", "")
    PUSHED.clear()
    check("pure predicate, under cap: True", h._master_under_cap() is True)
    check("pure predicate, under cap: no meta write, no notify", _capped() == "" and PUSHED == [])

with clean_env(ANTHROPIC_API_KEY="sk-test"):
    _set_spend(9999.0)
    h.store().set_meta("claude:capped", "")
    PUSHED.clear()
    check("pure predicate, over cap: False", h._master_under_cap() is False)
    check("pure predicate, over cap: STILL no meta write, no notify", _capped() == "" and PUSHED == [])

with clean_env(ANTHROPIC_API_KEY="sk-test"):
    _set_spend(9999.0)
    h.store().set_meta("claude:capped", "")
    PUSHED.clear()
    check("master_ready preserved, over cap: False", h.master_ready() is False)
    check("master_ready preserved, over cap: capped meta written", _capped() == _cap_month())
    check("master_ready preserved, over cap: exactly one notify", len(PUSHED) == 1 and "cap" in PUSHED[0][1])
    check("master_ready preserved, month guard: no second notify", (h.master_ready() is False) and len(PUSHED) == 1)

with clean_env(ANTHROPIC_API_KEY="sk-test"):
    _set_spend(9999.0)
    h.store().set_meta("claude:capped", "")
    PUSHED.clear()
    diags.clear()
    eid = seed_escalation("over-cap issue")
    # An earlier section leaves one open escalation behind, so the run
    # handles two; give the script two replies and assert on the new one.
    h._llm_call = scripted({FLASH: ["handled reply", "handled reply"], FB120: []})
    did = []
    h._triage_escalations(did)
    check("site over cap: triage still completes", f"handled #{eid}" in did)
    check("site over cap: new escalation marked triaged", eid in triaged_ids())
    check("site over cap: no capped meta written", _capped() == "")
    check("site over cap: no notify sent", PUSHED == [])
    check("site over cap: selection unaffected (one route diag)", len(route_diags()) == 1)

h.notify = _orig_notify
h.store().set_meta("claude:spend", "{}")
h.store().set_meta("claude:capped", "")

h._diag = _orig_diag
h._llm_call = _orig_llm
print("test_migration1_triage done")
