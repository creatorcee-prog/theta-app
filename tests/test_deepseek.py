"""DeepSeek as a provider (Stage 8.1): route() accepts it, Diagnostics checks
the key and model without spending tokens, and the benchmark gets a DeepSeek
column. A fake OpenAI-format server stands in for api.deepseek.com."""
import sys, json, os, io, threading
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
SEEN, BODIES, STATE = [], [], {"models": ["deepseek-flash", "deepseek-v4-pro"], "key": "dsk"}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.headers.get("Authorization") != f"Bearer {STATE['key']}":
            return self._send(401, {"error": {"message": "Authentication Fails"}})
        if self.path == "/models":
            return self._send(200, {"object": "list", "data": [{"id": m} for m in STATE["models"]]})
        self._send(404, {})
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n))
        SEEN.append(body["model"]); BODIES.append(body)
        q = body["messages"][-1]["content"]
        text = ("ACTION: web_search | Broncos score" if "Broncos" in q else "ESCALATE: big plan" if "plan next month" in q
                else "ACTION: remind | friday 3pm car registration" if "ping me friday" in q else "Hey! Doing well.")
        self._send(200, {"choices": [{"message": {"role": "assistant", "content": text}}],
                         "usage": {"prompt_tokens": 100, "completion_tokens": 9}})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ.update(DASHBOARD_KEY="dk", GROQ_API_KEY="qk", GEMINI_API_KEY="gk", ANTHROPIC_API_KEY="", DEEPSEEK_API_KEY="dsk",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
for k in ("LOCAL_LLM_URL", "LOCAL_LLM_KEY", "LOCAL_LLM_MODEL"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h  # memory store in both modes: nothing here depends on Redis
from wsgiref.util import setup_testing_defaults
h.PROVIDERS["deepseek"] = (base + "/chat/completions", "DEEPSEEK_API_KEY")
h.LLM_RETRY_DELAY = 0
h.tmdb_trending = lambda: []
_real_list = h._list_models
h._list_models = lambda p: _real_list(p) if p == "deepseek" else {"models": ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "gemini-3.8-flash"]}


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


def row():
    h._MODELS_CACHE.clear()
    return next(r for r in h.wiring() if r["agent"] == "deepseek")


print("mode:", mode)
check("the default model is DeepSeek's deepseek-flash (V4.1 Flash 1017)", h.DEEPSEEK_MODEL == "deepseek-flash")
check("route() accepts deepseek", "deepseek" in h.ROUTE_PROVIDERS)
check("the real endpoint is DeepSeek's OpenAI-format one",
      h.PROVIDERS["deepseek"][1] == "DEEPSEEK_API_KEY")

# ---- Diagnostics: key and model, no tokens spent
r = row()
check("Diagnostics: key works, model available", r["state"] == "ok" and "Key works, deepseek-flash available" in r["note"] and not SEEN)
STATE["key"] = "other"
r = row()
check("a refused key is flagged", r["state"] == "bad" and "401" in r["note"] and "DEEPSEEK_API_KEY" in r["note"])
STATE["key"] = "dsk"; STATE["models"] = ["deepseek-v5"]
r = row()
check("a model DeepSeek doesn't offer is named, with the fix", r["state"] == "bad" and "set DEEPSEEK_MODEL" in r["note"] and "deepseek-v5" in r["note"])
STATE["models"] = ["deepseek-flash"]
os.environ.pop("DEEPSEEK_API_KEY")
check("no key: not linked", row()["state"] == "off")
os.environ["DEEPSEEK_API_KEY"] = "dsk"

# ---- routing: one setting moves a tier to DeepSeek
os.environ.update(ROUTE_MANAGER_PROVIDER="deepseek", ROUTE_MANAGER_MODEL="deepseek-flash")
SEEN.clear()
out = h.llm_chat("manager", [{"role": "user", "content": "hi"}])
check("ROUTE_MANAGER_PROVIDER=deepseek: the managers answer on DeepSeek", out == "Hey! Doing well." and SEEN == ["deepseek-flash"])
check("...and Diagnostics says so", "answers for: manager" in row()["note"])
for k in ("ROUTE_MANAGER_PROVIDER", "ROUTE_MANAGER_MODEL"):
    os.environ.pop(k)

# ---- thinking: off by default (it made replies slow and short), a setting turns it back on
check("thinking is off by default: replies start at once and the tokens go to the answer",
      BODIES[-1].get("thinking") == {"type": "disabled"} and "reasoning_effort" not in BODIES[-1])
h.DEEPSEEK_THINKING = "low"
h.llm_chat("manager", [{"role": "user", "content": "hi"}], primary=("deepseek", "deepseek-flash"))
check("DEEPSEEK_THINKING=low turns it back on at that effort",
      BODIES[-1].get("thinking") == {"type": "enabled"} and BODIES[-1].get("reasoning_effort") == "low")
h.DEEPSEEK_THINKING = "off"
check("QWERTY can propose changing it", "DEEPSEEK_THINKING" in h.SETTABLE)
check("other providers don't get DeepSeek's fields", "thinking" not in h.provider_extra("groq", "openai/gpt-oss-20b"))

# ---- benchmark: a DeepSeek column (no Claude here, so it runs alone)
SEEN.clear()
env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/bench", "QUERY_STRING": "", "CONTENT_LENGTH": "2",
       "wsgi.input": io.BytesIO(b"{}"), "HTTP_X_DASHBOARD_KEY": "dk"}
setup_testing_defaults(env); got = {}
d = json.loads(b"".join(h.app(env, lambda s, hd: got.update(s=s))))
ds = [x for x in d.get("rows", []) if x["mode"] == "deepseek"]
check("the benchmark runs on DeepSeek", got["s"].startswith("200") and d["modes"] == [["deepseek", "DeepSeek (deepseek-flash)"]]
      and len(ds) == len(h.BENCH_QUESTIONS) and len(SEEN) == len(h.BENCH_QUESTIONS))
check("...scored the same way (search by tool, reminder, hand-off)",
      next(x for x in ds if x["want"] == "search")["ok"] and next(x for x in ds if x["want"] == "remind")["ok"]
      and next(x for x in ds if x["want"] == "escalate")["ok"])
print("ALL PASS")
