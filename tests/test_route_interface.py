"""Stage 4 P1 interface: route() contract tests (no production path calls
route() yet — this file tests the selection function (side-effect-free
apart from one diagnostic line) only).

Stubs: none needed for selection itself; _diag is recorded, and
_llm_call / claude_chat are armed to raise, proving route() never
calls a model. No live network: the only HTTP is the fake Upstash
server in redis mode, as in the other test files. Both modes take
sys.argv[1] ("memory"/"redis"), as run_all.sh passes it.

Env hygiene: route() reads ROUTE_* vars at call time, so every test
runs inside clean_env(), which pops all ROUTE_* vars (plus the
SETTABLE vars a test deliberately dirties) and restores them after.
"""
import sys, json, threading, os, contextlib
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


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


ROUTE_VARS = ["ROUTE_MINER_PROVIDER", "ROUTE_MINER_MODEL", "ROUTE_MANAGER_PROVIDER", "ROUTE_MANAGER_MODEL",
              "ROUTE_LOW_BRAIN_PROVIDER", "ROUTE_LOW_BRAIN_MODEL", "ROUTE_MASTER_PROVIDER", "ROUTE_MASTER_MODEL",
              "ROUTE_DESK_PROVIDER", "ROUTE_DESK_MODEL", "ROUTE_MINER_FALLBACK_MODEL",
              "ROUTE_MANAGER_FALLBACK_MODEL", "ROUTE_LOW_BRAIN_FALLBACK_MODEL"]
SETTABLE_DIRTY = ["LOW_BRAIN_MODEL", "DESK_MODEL", "MASTER_MONTHLY_CAP_USD", "MINER_FALLBACK_MODEL",
                  "MANAGER_FALLBACK_MODEL", "LOW_BRAIN_FALLBACK_MODEL"]


@contextlib.contextmanager
def clean_env(**overrides):
    saved = {k: os.environ.get(k) for k in ROUTE_VARS + SETTABLE_DIRTY}
    for k in ROUTE_VARS + SETTABLE_DIRTY:
        os.environ.pop(k, None)
    for k, v in overrides.items():
        os.environ[k] = v
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def cands(d):
    return [(c["provider"], c["model"]) for c in d["candidates"]]


def prim(d):
    return (d["primary"]["provider"], d["primary"]["model"])


def raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


GROQ20 = ("groq", "openai/gpt-oss-20b")
GROQ120 = ("groq", "openai/gpt-oss-120b")
GEMFLASH = ("gemini", "gemini-3.8-flash")
OPUS = ("anthropic", "claude-opus-5-5")
HAIKU = ("anthropic", "claude-haiku-5-5")

# --- diag recorder (restored at the end) ---
_orig_diag = h._diag
diags = []


def _rec(stage, **fields):
    diags.append((stage, fields))


h._diag = _rec

# --- no-model-call tripwire (restored at the end) ---
_orig_llm_call, _orig_claude_chat = h._llm_call, h.claude_chat


def _boom(*a, **k):
    raise AssertionError("route() called a model")


h._llm_call, h.claude_chat = _boom, _boom

# --- A. primary selection per role, defaults ---
with clean_env():
    d = h.route("miner", desk_up=False, master_up=False)
    check("miner default primary", prim(d) == GROQ20)
    # Dedup is intentional: miner fallback == manager primary (both
    # groq 120b) and manager fallback == low_brain primary (flash),
    # so the tried-set sequence collapses to three distinct models —
    # exactly the sequence llm_chat's `tried` set would attempt.
    check("miner default chain, desk off", cands(d) == [GROQ20, GROQ120, GEMFLASH])
    d = h.route("manager", desk_up=False, master_up=False)
    check("manager default primary", prim(d) == GROQ120)
    check("manager default chain, desk off", cands(d) == [GROQ120, GEMFLASH])
    d = h.route("low_brain", desk_up=False, master_up=False)
    check("low_brain default primary", prim(d) == GEMFLASH)
    check("low_brain default chain", cands(d) == [GEMFLASH, GROQ120])
    d = h.route("master", desk_up=False, master_up=True)
    check("master up: opus primary, not stand-in", prim(d) == OPUS and d["stand_in"] is False and d["tier"] == "master")
    check("master up chain", cands(d) == [OPUS, GEMFLASH, GROQ120])
    d = h.route("master", desk_up=False, master_up=False)
    check("master down: low_brain stand-in", prim(d) == GEMFLASH and d["stand_in"] is True and d["tier"] == "low_brain")
    check("master down chain", cands(d) == [GEMFLASH, GROQ120])
    d = h.route("low_brain", agent=None, entry_point=None, desk_up=False, master_up=False)
    check("agent/entry_point None still tier path", d["path"] == "tier" and prim(d) == GEMFLASH)
    for ep in ("router", "project", "summary", "bench", "other"):
        d = h.route("manager", entry_point=ep, desk_up=False, master_up=False)
        check(f"entry_point {ep} accepted, tier path", d["path"] == "tier")

# --- B. desk path on/off + D5 hinge ---
with clean_env():
    d = h.route("low_brain", agent="mistral", entry_point="desk", desk_up=True, master_up=False)
    check("desk on: path desk, haiku primary", d["path"] == "desk" and prim(d) == HAIKU and d["tier"] == "low_brain")
    check("desk on chain", cands(d) == [HAIKU, GEMFLASH, GROQ120])
    d = h.route("low_brain", agent="mistral", entry_point="desk", desk_up=False, master_up=False)
    check("desk off: path desk, low_brain primary", d["path"] == "desk" and prim(d) == GEMFLASH)
    check("desk off chain", cands(d) == [GEMFLASH, GROQ120])
    for ep in ("round", "search"):
        d = h.route("low_brain", agent="mistral", entry_point=ep, desk_up=True, master_up=False)
        check(f"desk entry {ep} takes desk path", d["path"] == "desk" and prim(d) == HAIKU)
    check("D5 hinge flipped (migration #2): allchat IS a desk entry point", "allchat" in h.DESK_ENTRY_POINTS)
    d = h.route("low_brain", agent="mistral", entry_point="allchat", desk_up=True, master_up=False)
    check("D5 hinge flipped: mistral allchat desk on takes desk path", d["path"] == "desk" and prim(d) == HAIKU)
    check("D5 hinge flipped: mistral allchat desk on chain", cands(d) == [HAIKU, GEMFLASH, GROQ120])
    d = h.route("low_brain", agent="mistral", entry_point="allchat", desk_up=False, master_up=False)
    check("D5 hinge flipped: mistral allchat desk off is desk path, low_brain primary", d["path"] == "desk" and prim(d) == GEMFLASH)
    check("D5 hinge flipped: mistral allchat desk off chain", cands(d) == [GEMFLASH, GROQ120])
    d = h.route("low_brain", agent="glass", entry_point="allchat", desk_up=True, master_up=False)
    check("D5 hinge flipped: non-desk agent allchat stays tier path", d["path"] == "tier" and prim(d) == GEMFLASH)
    d = h.route("manager", desk_up=True, master_up=False)
    check("manager desk up chain", cands(d) == [HAIKU, GROQ120, GEMFLASH])
    d = h.route("miner", desk_up=True, master_up=False)
    check("miner desk up chain", cands(d) == [GROQ20, GROQ120, HAIKU, GEMFLASH])

# --- C. policy encoding ---
with clean_env():
    d = h.route("miner", desk_up=False, master_up=False)
    p = d["policy"]
    check("policy: one retry", p["retries"] == 1)
    check("policy: retry delay is the module constant", p["retry_delay_s"] == h.LLM_RETRY_DELAY)
    check("policy: retry rule is primary-only, timed_out skips", "primary only" in p["retry_rule"] and "timed_out" in p["retry_rule"])
    check("policy: tried-set once each", "at most once" in p["tried_set"])
    check("policy: single-pass", p["single_pass"] is True)
    check("policy: borrow miner+manager only",
          h.route("miner", desk_up=False, master_up=False)["policy"]["borrow"] is True and
          h.route("manager", desk_up=False, master_up=False)["policy"]["borrow"] is True and
          h.route("low_brain", desk_up=False, master_up=False)["policy"]["borrow"] is False and
          h.route("master", desk_up=False, master_up=True)["policy"]["borrow"] is False)
    for role in ("miner", "manager", "low_brain", "master"):
        for du in (False, True):
            for mu in (False, True):
                cs = cands(h.route(role, desk_up=du, master_up=mu))
                check(f"no duplicate candidates {role} desk={du} master={mu}", len(cs) == len(set(cs)))
                if not (role == "master" and mu):
                    check(f"never-Theta {role} desk={du} master={mu}", OPUS not in cs)
    with clean_env(ROUTE_MANAGER_PROVIDER="anthropic", ROUTE_MANAGER_MODEL="claude-opus-5-5"):
        cs = cands(h.route("miner", desk_up=False, master_up=False))
        check("never-Theta under overrides: opus manager primary dropped from miner chain", OPUS not in cs)

# --- D. config precedence + errors ---
with clean_env():
    check("missing config -> literal defaults", prim(h.route("miner", desk_up=False, master_up=False)) == GROQ20)
with clean_env(ROUTE_MINER_PROVIDER="gemini", ROUTE_MINER_MODEL="gemini-x"):
    check("complete pair wins", prim(h.route("miner", desk_up=False, master_up=False)) == ("gemini", "gemini-x"))
with clean_env(ROUTE_MINER_PROVIDER="gemini"):
    check("half pair (provider only) raises", raises(lambda: h.route("miner", desk_up=False, master_up=False), h.RouteConfigError))
with clean_env(ROUTE_MINER_MODEL="gemini-x"):
    check("half pair (model only) raises", raises(lambda: h.route("miner", desk_up=False, master_up=False), h.RouteConfigError))
with clean_env(ROUTE_MINER_PROVIDER="gemini", ROUTE_MINER_MODEL="   "):
    check("half pair (blank model) raises", raises(lambda: h.route("miner", desk_up=False, master_up=False), h.RouteConfigError))
with clean_env(ROUTE_MINER_PROVIDER="deepseek", ROUTE_MINER_MODEL="deepseek-chat"):
    check("DeepSeek absent: unknown provider raises", raises(lambda: h.route("miner", desk_up=False, master_up=False), h.RouteConfigError))
check("DeepSeek not in provider registry", "deepseek" not in h.ROUTE_PROVIDERS)
with clean_env(ROUTE_MINER_PROVIDER="bogus", ROUTE_MINER_MODEL="x"):
    check("unknown provider raises", raises(lambda: h.route("miner", desk_up=False, master_up=False), h.RouteConfigError))
with clean_env(ROUTE_LOW_BRAIN_PROVIDER="gemini", ROUTE_LOW_BRAIN_MODEL="gemini-y", LOW_BRAIN_MODEL="junk-model"):
    check("conflicting: route pair wins over SETTABLE", prim(h.route("low_brain", desk_up=False, master_up=False)) == ("gemini", "gemini-y"))
with clean_env(LOW_BRAIN_MODEL="junk-model", DESK_MODEL="off", MASTER_MONTHLY_CAP_USD="999",
              MINER_FALLBACK_MODEL="off", MANAGER_FALLBACK_MODEL="off", LOW_BRAIN_FALLBACK_MODEL="off"):
    d = h.route("miner", desk_up=True, master_up=False)
    check("SETTABLE no-leak: defaults unchanged", prim(d) == GROQ20 and cands(d) == [GROQ20, GROQ120, HAIKU, GEMFLASH])
    d = h.route("low_brain", agent="mistral", entry_point="desk", desk_up=True, master_up=False)
    check("SETTABLE no-leak: desk path still haiku with DESK_MODEL=off in env", prim(d) == HAIKU)
    d = h.route("master", desk_up=False, master_up=True)
    check("SETTABLE no-leak: master still opus with cap var dirtied", prim(d) == OPUS)
check("invalid role raises", raises(lambda: h.route("nope", desk_up=False, master_up=False), h.RouteConfigError))
check("invalid agent raises", raises(lambda: h.route("miner", agent="nobody", desk_up=False, master_up=False), h.RouteConfigError))
check("invalid entry_point raises", raises(lambda: h.route("miner", entry_point="nope", desk_up=False, master_up=False), h.RouteConfigError))
check("desk_up/master_up are required keywords", raises(lambda: h.route("miner"), TypeError))

# --- E. fallback-off modeling ---
# NOTE: with pure defaults, miner fallback-off and manager fallback-off
# are invisible after dedup (miner fallback == manager primary, manager
# fallback == low_brain primary), so these tests use distinct override
# models to make the suppressed step observable.
with clean_env(ROUTE_MINER_FALLBACK_MODEL="custom-fb", ROUTE_MANAGER_PROVIDER="groq", ROUTE_MANAGER_MODEL="mgr-x"):
    check("miner fallback present with distinct overrides",
          cands(h.route("miner", desk_up=False, master_up=False)) == [GROQ20, ("groq", "custom-fb"), ("groq", "mgr-x"), GEMFLASH, GROQ120])
with clean_env(ROUTE_MINER_FALLBACK_MODEL="off", ROUTE_MANAGER_PROVIDER="groq", ROUTE_MANAGER_MODEL="mgr-x"):
    check("miner fallback-off: miner fallback gone, borrow intact",
          cands(h.route("miner", desk_up=False, master_up=False)) == [GROQ20, ("groq", "mgr-x"), GEMFLASH, GROQ120])
with clean_env(ROUTE_MANAGER_FALLBACK_MODEL="mgr-fb", ROUTE_LOW_BRAIN_PROVIDER="gemini", ROUTE_LOW_BRAIN_MODEL="lb-x"):
    check("manager fallback present with distinct overrides",
          cands(h.route("manager", desk_up=False, master_up=False)) == [GROQ120, ("gemini", "mgr-fb"), ("gemini", "lb-x")])
with clean_env(ROUTE_MANAGER_FALLBACK_MODEL="off", ROUTE_LOW_BRAIN_PROVIDER="gemini", ROUTE_LOW_BRAIN_MODEL="lb-x"):
    check("manager fallback-off: manager fallback gone, low_brain chain intact",
          cands(h.route("manager", desk_up=False, master_up=False)) == [GROQ120, ("gemini", "lb-x")])
with clean_env(ROUTE_LOW_BRAIN_FALLBACK_MODEL="off"):
    check("low_brain fallback-off: primary only", cands(h.route("low_brain", desk_up=False, master_up=False)) == [GEMFLASH])
    check("master stand-in fallback-off: primary only", cands(h.route("master", desk_up=False, master_up=False)) == [GEMFLASH])
    d = h.route("low_brain", agent="mistral", entry_point="desk", desk_up=True, master_up=False)
    check("desk path fallback-off: haiku + primary", cands(d) == [HAIKU, GEMFLASH])
with clean_env(ROUTE_MINER_FALLBACK_MODEL="custom-fb"):
    cs = cands(h.route("miner", desk_up=False, master_up=False))
    check("fallback model override keeps tier provider", cs[1] == ("groq", "custom-fb"))

# --- F. budget info carried, nothing enforced ---
with clean_env():
    b = h.route("master", desk_up=False, master_up=True)["budget"]
    check("master budget: monthly scope, $15 default, not a hard ceiling",
          b["scope"] == "master-monthly" and b["default_cap_usd"] == 15.0 and b["hard_ceiling"] is False)
    check("non-master budget: no monthly scope", h.route("miner", desk_up=False, master_up=False)["budget"]["scope"] is None)
with clean_env(MASTER_MONTHLY_CAP_USD="0.01"):
    b = h.route("master", desk_up=False, master_up=True)["budget"]
    check("route() enforces nothing: cap var does not move its budget info", b["default_cap_usd"] == 15.0)

# --- G. diag-only effect: no model call, no store touch, one route diag line ---
with clean_env():
    diags.clear()
    d = h.route("miner", desk_up=False, master_up=False)
    check("route() emits exactly one model.selected diag via=route",
          len(diags) == 1 and diags[0][0] == "model.selected" and diags[0][1].get("via") == "route" and
          diags[0][1].get("provider") == "groq" and diags[0][1].get("model") == "openai/gpt-oss-20b")
    st = h.store()
    st.set_meta("llm:last_selection", "sentinel-before")
    h.route("manager", desk_up=False, master_up=False)
    check("route() never writes llm:last_selection", st.get_meta("llm:last_selection") == "sentinel-before")

# --- H. Q2 review: eager cross-role validation (contract, pinned) ---
# route() resolves EVERY role's primary pair (and all three tier
# fallbacks) on each call, before branching on path — see the prim /
# fallback loops at the top of route(). So a malformed pair for an
# UNRELATED role fails the whole decision. That is the current
# contract, pinned here, not a one-test accident: fail-fast
# detection (any bad ROUTE_* var surfaces on the next request of any
# role) traded against blast radius (one bad var blocks every
# migrated role). Per-chain lazy resolution would remove the blast
# radius but let a bad pair hide until its own role is requested;
# that change needs its own reviewed diff and is NOT made here.
with clean_env(ROUTE_MASTER_PROVIDER="not-a-provider", ROUTE_MASTER_MODEL="x"):
    check("unrelated role: malformed ROUTE_MASTER_* pair fails a miner request",
          raises(lambda: h.route("miner", desk_up=False, master_up=False), h.RouteConfigError))
with clean_env(ROUTE_MASTER_PROVIDER="anthropic"):
    check("unrelated role: half ROUTE_MASTER_* pair fails a miner request",
          raises(lambda: h.route("miner", desk_up=False, master_up=False), h.RouteConfigError))
with clean_env(ROUTE_MASTER_PROVIDER="not-a-provider", ROUTE_MASTER_MODEL="x"):
    check("unrelated role: malformed ROUTE_MASTER_* pair fails a low_brain request",
          raises(lambda: h.route("low_brain", desk_up=False, master_up=False), h.RouteConfigError))
with clean_env(ROUTE_MINER_PROVIDER="not-a-provider", ROUTE_MINER_MODEL="x"):
    check("mirror: malformed ROUTE_MINER_* pair fails a low_brain request",
          raises(lambda: h.route("low_brain", desk_up=False, master_up=False), h.RouteConfigError))
with clean_env():
    check("control: clean config still routes a miner request",
          prim(h.route("miner", desk_up=False, master_up=False)) == GROQ20)

h._diag = _orig_diag
h._llm_call, h.claude_chat = _orig_llm_call, _orig_claude_chat
print("test_route_interface done")
