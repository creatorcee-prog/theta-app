"""Your PC as a provider ("local"): LM Studio / Ollama behind a tunnel.
A fake OpenAI-style server stands in for LM Studio (and for Groq, so the
fallback is real HTTP too). No live network."""
import sys, json, os, io, time, threading
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
SEEN = {"models": 0, "chat": []}
STATE = {"up": True, "loaded": ["qwen3.6-35b-a3b"]}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _authed(self, key):
        return self.headers.get("Authorization") == f"Bearer {key}"
    def do_GET(self):
        if self.path == "/pc/v1/models":
            SEEN["models"] += 1
            if not STATE["up"]: return self._send(502, {})
            if not self._authed("lm-token"): return self._send(401, {"error": "unauthorized"})
            return self._send(200, {"data": [{"id": m} for m in STATE["loaded"]]})
        self._send(404, {})
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n)) if n else {}
        who = "pc" if self.path.startswith("/pc/") else "groq"
        if who == "pc" and not self._authed("lm-token"): return self._send(401, {})
        SEEN["chat"].append((who, body.get("model")))
        q = body["messages"][-1]["content"]
        text = ("SEARCH: Broncos score" if "Broncos" in q else "ESCALATE: big plan" if "plan next month" in q
                else "ACTION: remind | friday 3pm car registration" if "ping me friday" in q else f"{who} says hi")
        self._send(200, {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 10, "completion_tokens": 3}})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ.update(DASHBOARD_KEY="dk", GROQ_API_KEY="qk", GEMINI_API_KEY="gk", ANTHROPIC_API_KEY="",
                  LOCAL_LLM_URL=base + "/pc/v1/", LOCAL_LLM_KEY="lm-token", LOCAL_LLM_MODEL="qwen3.6-35b-a3b",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h  # memory store in both modes: nothing here depends on Redis
from wsgiref.util import setup_testing_defaults
h.PROVIDERS["groq"] = (base + "/groq/chat/completions", "GROQ_API_KEY")
h.LLM_RETRY_DELAY = 0
h.tmdb_trending = lambda: []
h._list_models = lambda p: {"models": ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "gemini-3.8-flash"]}


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


def call(method, path, qs="", body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)),
           "wsgi.input": io.BytesIO(raw), "HTTP_X_DASHBOARD_KEY": "dk"}
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s)))
    return int(got["s"][:3]), json.loads(out) if out[:1] == b"{" else out


def fresh():
    h._LOCAL_STATE.update(at=0.0, ok=False, why="")
    SEEN["models"] = 0; SEEN["chat"].clear()


print("mode:", mode)
check("the trailing slash in LOCAL_LLM_URL is dropped", h.LOCAL_LLM_URL == base + "/pc/v1"
      and h.PROVIDERS["local"][0] == base + "/pc/v1/chat/completions")
check("route() accepts local as a provider", "local" in h.ROUTE_PROVIDERS)

# ---- the check
fresh()
check("PC up with the model loaded", h.local_status() == (True, "answering, qwen3.6-35b-a3b loaded"))
h.local_status()
check("one check is trusted for a minute (no second probe)", SEEN["models"] == 1)
STATE["loaded"] = ["qwen3.5-9b"]; fresh()
up, why = h.local_status()
check("PC up but a different model loaded: says which", not up and "isn't loaded" in why and "qwen3.5-9b" in why)
STATE["loaded"] = ["qwen3.6-35b-a3b"]
os.environ["LOCAL_LLM_KEY"] = "wrong"; fresh()
up, why = h.local_status()
check("a wrong key is named as the problem", not up and "LOCAL_LLM_KEY must match" in why)
os.environ["LOCAL_LLM_KEY"] = "lm-token"
STATE["up"] = False; fresh()
up, why = h.local_status()
check("LM Studio closed behind a live tunnel (502): says so", not up and "LM Studio isn't" in why)

# ---- routing: the miners on your PC, Groq standing in when it's off
os.environ.update(ROUTE_MINER_PROVIDER="local", ROUTE_MINER_MODEL="qwen3.6-35b-a3b")
d = h.route("miner", desk_up=False, master_up=False)
check("ROUTE_MINER_PROVIDER=local makes your PC the miners' first choice",
      d["primary"] == {"provider": "local", "model": "qwen3.6-35b-a3b"} and d["fallbacks"][0]["provider"] == "groq")
prim = (d["primary"]["provider"], d["primary"]["model"])
fb = (d["fallbacks"][0]["provider"], d["fallbacks"][0]["model"])
STATE["up"] = True; fresh()
out = h.llm_chat("miner", [{"role": "user", "content": "hello"}], primary=prim, fallback=fb)
check("PC up: your PC answers, with the token sent", out == "pc says hi" and SEEN["chat"] == [("pc", "qwen3.6-35b-a3b")])
STATE["up"] = False; fresh()
out = h.llm_chat("miner", [{"role": "user", "content": "hello"}], primary=prim, fallback=fb)
check("PC off: Groq answers instead, no error", out == "groq says hi" and SEEN["chat"] == [("groq", "openai/gpt-oss-120b")])
SEEN["chat"].clear(); probes = SEEN["models"]
h.llm_chat("miner", [{"role": "user", "content": "again"}], primary=prim, fallback=fb)
check("...and the next call doesn't wait on the PC again", SEEN["models"] == probes)
for k in ("ROUTE_MINER_PROVIDER", "ROUTE_MINER_MODEL"):
    os.environ.pop(k)

# ---- one setting moves the whole tier: unmigrated miner calls (Red, Blue, Gray) follow it too
os.environ.update(ROUTE_MINER_PROVIDER="local", ROUTE_MINER_MODEL="qwen3.6-35b-a3b")
STATE["up"] = True; fresh()
out = h.llm_chat("miner", [{"role": "user", "content": "story brief"}])  # no route() values passed: legacy caller
check("an explicit ROUTE_MINER pair reaches every miner call", out == "pc says hi" and SEEN["chat"] == [("pc", "qwen3.6-35b-a3b")])
STATE["up"] = False; fresh()
out = h.llm_chat("miner", [{"role": "user", "content": "story brief"}])
check("...with the legacy fallback when the PC is off", out == "groq says hi" and SEEN["chat"] == [("groq", "openai/gpt-oss-120b")])
check("...and the old MINER_MODEL isn't flagged as drift (it's unused now)", not [d for d in h.route_drift() if d[0] == "MINER_MODEL"])
for k in ("ROUTE_MINER_PROVIDER", "ROUTE_MINER_MODEL"):
    os.environ.pop(k)
fresh()
h.llm_chat("manager", [{"role": "user", "content": "hi"}])
check("unset: the legacy lookup is unchanged", SEEN["chat"] == [("groq", "openai/gpt-oss-120b")])

# ---- Diagnostics row
STATE["up"] = True; fresh()
row = next(r for r in h.wiring() if r["agent"] == "local")
check("Diagnostics: Your PC answering, and for whom", row["state"] == "ok" and "not answering for anyone yet" in row["note"])
os.environ.update(ROUTE_MINER_PROVIDER="local", ROUTE_MINER_MODEL="qwen3.6-35b-a3b")
STATE["up"] = False
row = next(r for r in h.wiring(fresh=True) if r["agent"] == "local")
check("Recheck: PC off is flagged, with who's covering", row["state"] == "bad" and "answers for: miner" in row["note"]
      and "Groq and Gemini stand in" in row["note"])
for k in ("ROUTE_MINER_PROVIDER", "ROUTE_MINER_MODEL"):
    os.environ.pop(k)
url = h.LOCAL_LLM_URL; h.LOCAL_LLM_URL = ""; key = os.environ.pop("LOCAL_LLM_KEY")
row = next(r for r in h.wiring() if r["agent"] == "local")
check("not linked: tells you the three settings", row["state"] == "off" and "LOCAL_LLM_URL, LOCAL_LLM_KEY and LOCAL_LLM_MODEL" in row["note"])
h.LOCAL_LLM_URL = url; os.environ["LOCAL_LLM_KEY"] = key

# ---- benchmark: your PC's column (no Claude here, so it runs alone)
STATE["up"] = True; fresh()
s, d = call("POST", "/api/bench", body={})
local = [r for r in d.get("rows", []) if r["mode"] == "local"]
check("the benchmark runs on your PC without Claude", s == 200 and len(local) == len(h.BENCH_QUESTIONS)
      and d["modes"] == [["local", "Your PC (qwen3.6-35b-a3b)"]])
check("...one question at a time, scored the same way",
      all(w == "pc" for w, _ in SEEN["chat"]) and sum(r["ok"] for r in local) >= 4
      and next(r for r in local if r["want"] == "search")["did"] == "search")
page = call("GET", "/settings", "key=dk")[1].decode()
check("the results table takes its columns from the run", "d.modes ||" in page and "modes.map(m => m[1])" in page)
print("ALL PASS")
