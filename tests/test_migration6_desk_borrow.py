"""Stage 4 P1 migrations #6 and #7.

#6: Mistral's desk path takes its models from route() through
desk_route(): desk_reply ("desk"), the SEARCH turn ("search"),
round_summary ("round"), and #2's allchat turn ("allchat", pure).
#7: borrow_help's candidates come from route()'s config.
Also: route_drift() and the checkup flag legacy model settings that the
moved paths no longer read.

Stubs: claude_chat and _llm_call record (provider, model) and follow a
script; notify and master_ready are spied. No live network.
"""
import sys, json, os, contextlib, threading
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
DB = {}
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n)) if n else {}
        op, k, a = body[0], body[1], body[2:]
        if op == "INCR": DB[k] = DB.get(k, 0) + 1; r = DB[k]
        elif op == "LPUSH": DB.setdefault(k, []).insert(0, a[0]); r = 1
        elif op == "LTRIM": DB[k] = DB.get(k, [])[int(a[0]):int(a[1]) + 1]; r = "OK"
        elif op == "LRANGE":
            l = DB.get(k, []); e = int(a[1]); r = l[int(a[0]):(None if e == -1 else e + 1)]
        elif op == "HSET":
            h_ = DB.setdefault(k, {}); r = sum(1 for x in a[::2] if x not in h_); h_.update(zip(a[::2], a[1::2]))
        elif op == "HGET": r = DB.get(k, {}).get(a[0])
        elif op == "HMGET": r = [DB.get(k, {}).get(x) for x in a]
        elif op == "HGETALL": r = [x for kv in DB.get(k, {}).items() for x in kv]
        elif op == "SMEMBERS": r = []
        else: r = None
        self._send(200, {"result": r})
srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
os.environ.update(DASHBOARD_KEY="dk", ANTHROPIC_API_KEY="ak", GROQ_API_KEY="qk", GEMINI_API_KEY="gk",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="t")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.LLM_RETRY_DELAY = 0
h.notify = lambda *a, **k: 0
h.refresh_windows = lambda deadline=None: ""


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


CALLS, FAIL = [], set()  # FAIL: models that raise a retryable error


def fake_claude(messages, max_tokens, model=None, effort=None):
    model = model or h.MASTER_MODEL_ID
    CALLS.append(("anthropic", model))
    if model in FAIL:
        raise h.LLMError(f"anthropic {model} returned 529", retryable=True)
    return f"reply from {model}"


def fake_llm(provider, model, messages, max_tokens):
    CALLS.append((provider, model))
    if model in FAIL:
        raise h.LLMError(f"{provider} returned 503", retryable=True)
    return f"reply from {model}"


h.claude_chat = fake_claude
h._llm_call = fake_llm
READY = []
_real_ready = h.master_ready
def spy_ready():
    READY.append(1)
    return _real_ready()
h.master_ready = spy_ready

ROUTE_VARS = [v for pair in h.ROUTE_CONFIG_VARS.values() for v in pair] + list(h.ROUTE_FALLBACK_VARS.values())


@contextlib.contextmanager
def setup(fail=(), desk_model=None, fallback_llm=None, **env):
    """Clean ROUTE_* env, a fresh call log, and optional legacy values."""
    saved_env = {k: os.environ.get(k) for k in ROUTE_VARS}
    saved = (h.DESK_MODEL, dict(h.TIER_LLM), dict(h.FALLBACK_LLM))
    for k in ROUTE_VARS:
        os.environ.pop(k, None)
    os.environ.update(env)
    if desk_model is not None:
        h.DESK_MODEL = desk_model
    if fallback_llm:
        h.FALLBACK_LLM.update(fallback_llm)
    CALLS.clear(); READY.clear(); FAIL.clear(); FAIL.update(fail)
    h._ROOM.clear()
    try:
        yield
    finally:
        for k, v in saved_env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        h.DESK_MODEL, tier, fb = saved
        h.TIER_LLM.clear(); h.TIER_LLM.update(tier); h.FALLBACK_LLM.clear(); h.FALLBACK_LLM.update(fb)


THREAD = [{"from": "you", "name": "You", "text": "how's my week looking?", "at": 0, "id": 1}]


def desk():
    return h.desk_reply(list(THREAD))


print("mode:", mode)

# ---- #6: desk_reply
with setup():
    agent, reply = desk()
    check("desk_reply: Mistral answers on the routed desk model (Haiku by default)",
          agent == "mistral" and CALLS == [("anthropic", "claude-haiku-5-5")])
    check("...and desk_reply still calls master_ready() (the monthly cap notice is kept)", READY)
with setup(ROUTE_DESK_PROVIDER="anthropic", ROUTE_DESK_MODEL="claude-sonnet-5-5"):
    desk()
    check("ROUTE_DESK_* moves Mistral's main chat", CALLS == [("anthropic", "claude-sonnet-5-5")])
with setup(desk_model="claude-sonnet-5-5"):
    desk()
    check("the legacy DESK_MODEL id no longer moves it (D6)", CALLS == [("anthropic", "claude-haiku-5-5")])
with setup(desk_model="off"):
    desk()
    check("DESK_MODEL=off still turns the desk off: the low brain answers", CALLS == [("gemini", "gemini-3.8-flash")])
with setup(fail={"claude-haiku-5-5"}):
    desk()
    check("desk down: the routed low brain answers", CALLS == [("anthropic", "claude-haiku-5-5"), ("gemini", "gemini-3.8-flash")])
with setup(fail={"claude-haiku-5-5"}, ROUTE_LOW_BRAIN_PROVIDER="groq", ROUTE_LOW_BRAIN_MODEL="openai/gpt-oss-120b",
           ROUTE_LOW_BRAIN_FALLBACK_MODEL="off"):
    desk()
    check("ROUTE_LOW_BRAIN_* moves the desk's fallback", CALLS[-1] == ("groq", "openai/gpt-oss-120b"))
with setup(fail={"claude-haiku-5-5", "gemini-3.8-flash"}, fallback_llm={"low_brain": ("groq", "off")}):
    try:
        desk()
    except h.LLMError:
        pass
    check("a legacy LOW_BRAIN_FALLBACK_MODEL=off is still honored (no Groq step)", ("groq", "openai/gpt-oss-120b") not in CALLS)
with setup():
    os.environ["ANTHROPIC_API_KEY"] = ""
    try:
        desk()
    finally:
        os.environ["ANTHROPIC_API_KEY"] = "ak"
    check("no Claude key: no desk call at all", CALLS == [("gemini", "gemini-3.8-flash")])
with setup(ROUTE_DESK_PROVIDER="anthropic"):
    try:
        desk(); ok = False
    except h.RouteConfigError:
        ok = True
    check("a half ROUTE_DESK pair fails fast, as route() promises", ok and not CALLS)

# ---- #6: the other desk entry points
with setup(ROUTE_DESK_PROVIDER="anthropic", ROUTE_DESK_MODEL="claude-sonnet-5-5"):
    h._fallback_web_search = lambda agent, q: ("Web search results: x", [("X", "https://example.com/x")])
    h._resolve = lambda u: u
    h.answer_with_search(h.DESK, "You are Mistral.", "who won?", "who won")
    check("the SEARCH turn uses the routed desk model", CALLS == [("anthropic", "claude-sonnet-5-5")])
with setup(ROUTE_DESK_PROVIDER="anthropic", ROUTE_DESK_MODEL="claude-sonnet-5-5"):
    h.round_summary([{"from": "glass", "text": "Dining is at 92%."}])
    check("the round summary uses the routed desk model", CALLS == [("anthropic", "claude-sonnet-5-5")])
with setup():
    kw = h.desk_route("allchat", pure=True)
    check("#2's allchat turn: same values through desk_route(), still no master_ready()",
          not READY and kw == {"desk_up": True, "desk_model": "claude-haiku-5-5",
                               "primary": ("gemini", "gemini-3.8-flash"), "fallback": ("groq", "openai/gpt-oss-120b")})
    kw = h.desk_route("desk")
    check("desk_route() off-pure calls master_ready(), like desk_on() did", READY)
with setup(desk_model="off"):
    check("desk off: primary is the low brain, fallback its fallback",
          h.desk_route("desk") == {"desk_up": False, "desk_model": None, "primary": ("gemini", "gemini-3.8-flash"),
                                   "fallback": ("groq", "openai/gpt-oss-120b")})

# ---- #7: borrow
BIG = [{"role": "user", "content": "x" * 40000}]  # ~10k tokens: more than Groq's free minute
with setup(desk_model="off"):
    h.llm_chat("miner", BIG)
    check("borrow: a request too big for Groq goes up to the manager's Gemini fallback",
          CALLS == [("gemini", "gemini-3.8-flash")])
with setup(desk_model="off", ROUTE_MANAGER_FALLBACK_MODEL="gemini-3.9-pro"):
    h.llm_chat("miner", BIG)
    check("borrow follows ROUTE_* (ROUTE_MANAGER_FALLBACK_MODEL)", CALLS == [("gemini", "gemini-3.9-pro")])
with setup(desk_model="off", fallback_llm={"manager": ("gemini", "gemini-legacy")}):
    h.llm_chat("miner", BIG)
    check("...not the legacy MANAGER_FALLBACK_MODEL", CALLS == [("gemini", "gemini-3.8-flash")])
with setup(desk_model="off", ROUTE_MANAGER_FALLBACK_MODEL="off", ROUTE_LOW_BRAIN_PROVIDER="gemini",
           ROUTE_LOW_BRAIN_MODEL="gemini-3.9-pro"):
    h.llm_chat("miner", BIG)
    check("...and on up to route()'s low brain", CALLS == [("gemini", "gemini-3.9-pro")])
with setup():
    h.llm_chat("miner", BIG)
    check("borrow: the desk model helps first while the desk is on", CALLS == [("anthropic", "claude-haiku-5-5")])
with setup(fail={"claude-haiku-5-5", "gemini-3.8-flash", "openai/gpt-oss-120b"}, ROUTE_DESK_PROVIDER="anthropic",
           ROUTE_DESK_MODEL="claude-opus-5-5"):
    try:
        h.llm_chat("miner", BIG)
    except h.LLMError:
        pass
    check("borrow never uses the master model, even when the desk is set to it", ("anthropic", "claude-opus-5-5") not in CALLS)
with setup(desk_model="off", fallback_llm={"manager": ("gemini", "off")}, ROUTE_LOW_BRAIN_PROVIDER="gemini",
           ROUTE_LOW_BRAIN_MODEL="gemini-3.9-pro"):
    h.llm_chat("miner", BIG)
    check("borrow: a legacy fallback 'off' still skips that step (straight to the low brain)",
          CALLS == [("gemini", "gemini-3.9-pro")])

# ---- drift: the checkup says when the two settings systems disagree
with setup():
    check("no drift with the defaults", h.route_drift() == [])
with setup(desk_model="claude-sonnet-5-5"):
    d = h.route_drift()
    check("a legacy DESK_MODEL that differs is flagged, with the exact fix",
          d == [("DESK_MODEL", "claude-sonnet-5-5", "claude-haiku-5-5",
                 "set ROUTE_DESK_PROVIDER=anthropic and ROUTE_DESK_MODEL=claude-sonnet-5-5 to use it everywhere")])
    h.wiring = lambda: []
    c = [x for x in h.doctor_checks() if x["name"] == "Model setting DESK_MODEL"]
    check("...and shows in the checkup as a warning", c and c[0]["state"] == "warn" and "ROUTE_DESK_MODEL" in c[0]["detail"])
with setup(desk_model="claude-sonnet-5-5", ROUTE_DESK_PROVIDER="anthropic", ROUTE_DESK_MODEL="claude-sonnet-5-5"):
    check("following the fix clears it", h.route_drift() == [])
with setup(desk_model="off"):
    check("DESK_MODEL=off isn't drift (route() honors it)", h.route_drift() == [])
with setup(fallback_llm={"manager": ("gemini", "gemini-legacy")}):
    check("a differing legacy fallback is flagged", h.route_drift()[0][0] == "MANAGER_FALLBACK_MODEL")
print("ALL PASS")
