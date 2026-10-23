import sys, json, threading, os, io, time, re
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
DB, CLAUDE, LOW = {}, [], []
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.endswith("/models"): return self._send(200, {"data": [{"id": "openai/gpt-oss-120b"}, {"id": "models/gemini-3.8-flash"}]})
        self._send(404, {})
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n)) if n else {}
        if self.path.startswith("/anthropic/v1/messages"):
            CLAUDE.append(body)
            q = body["messages"][-1]["content"]; q = q if isinstance(q, str) else q[0]["text"]
            off = body.get("thinking", {}).get("type") == "disabled"
            if "plan next month" in q:
                text = "Sure, here's a quick plan." if off else "ESCALATE: planning across budget, trip and calendar"
            elif "Broncos" in q:
                text = "SEARCH: Broncos game score last night"
            elif "car registration" in q:
                text = "On it.\nACTION: remind | friday 3pm | car registration"
            else:
                text = "Here's what I see."
            first = len(CLAUDE) == 1
            usage = {"input_tokens": 300, "output_tokens": 40 if off else 120,
                     "cache_creation_input_tokens": 17000 if first else 0, "cache_read_input_tokens": 0 if first else 17000}
            return self._send(200, {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                                    "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None, "usage": usage})
        if self.path.startswith("/redis"):
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
            return self._send(200, {"result": r})
        LOW.append((self.path, body))  # gemini / groq
        self._send(200, {"choices": [{"message": {"content": "low brain answer"}}]})
srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk-long-enough-key", GROQ_API_KEY="qk", GEMINI_API_KEY="gk",
                  ANTHROPIC_API_KEY="sk-ant-test-0123456789abcdefghijklmnopqrstuvwxyz", ANTHROPIC_BASE_URL=base + "/anthropic",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json", VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="t")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}
h.notify = lambda *a, **k: 0
from wsgiref.util import setup_testing_defaults
def call(method, path, headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s)))
    return int(got["s"][:3]), (json.loads(out) if out[:1] in (b"{", b"[") else out)
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
K = {"x-dashboard-key": "dk-long-enough-key", "host": "theta.example"}
print("mode:", mode)

# caching on the real desk path: the stable prompt is cached, the clock comes after it
h.master_ready = lambda: True
s, d = call("POST", "/api/allchat", headers=K, body={"text": "how's my week looking?", "channel": "all"})
body = CLAUDE[-1]
check("the desk reply came from Haiku", s == 200 and d["messages"][-1]["from"] == "mistral" and body["model"] == "claude-haiku-5-5")
check("system is two blocks: the stable part cached, then the clock (uncached)",
      isinstance(body["system"], list) and len(body["system"]) == 2 and body["system"][0].get("cache_control") == {"type": "ephemeral"}
      and "cache_control" not in body["system"][1] and body["system"][1]["text"].strip().startswith("Right now it's"))
check("the cached part has no clock in it, and the crew's facts are in it",
      "Right now it's" not in body["system"][0]["text"] and "Settings QWERTY can change" in body["system"][0]["text"])
check("thinking stays on in normal chat", "thinking" not in body)
check("the reply carries its tokens and who worked on it", d["messages"][-1]["tokens"] == {"in": 17300, "out": 120}
      and d["messages"][-1]["trail"] == ["mistral"])
spend = h.claude_spend()
check("cache reads and writes are counted", h._meta_json("claude:spend", {}) and
      list(h._meta_json("claude:spend", {}).values())[0].get("cache_write") == 17000)
# without Claude the low brain gets one system message, as before
h.master_ready = lambda: False; LOW.clear()
s, d = call("POST", "/api/allchat", headers=K, body={"text": "how's my week looking?", "channel": "all"})
sysmsgs = [m for m in LOW[-1][1]["messages"] if m["role"] == "system"]
check("Gemini gets one system message, clock included", LOW[-1][0] == "/gemini" and len(sysmsgs) == 1 and "Right now it's" in sysmsgs[0]["content"])
before = len(CLAUDE)
h.master_ready = lambda: True
h.claude_chat([{"role": "system", "content": "You are Theta."}, {"role": "user", "content": "hi"}], 100)
check("a single system prompt isn't marked for caching (no write fee for nothing)", CLAUDE[-1]["system"] == "You are Theta.")

# the managers (QWERTY, Glass, Remi) on Haiku while Claude is up; Groq when it isn't
h.master_ready = lambda: True; LOW.clear(); n = len(CLAUDE)
out = h.llm_chat("manager", [{"role": "system", "content": "You are QWERTY."}, {"role": "user", "content": "status?"}])
check("QWERTY's tier answers on Haiku", len(CLAUDE) == n + 1 and CLAUDE[-1]["model"] == "claude-haiku-5-5" and not LOW)
check("Wiring names Haiku for QWERTY, not for James", h.agent_model("qwerty").startswith("claude-haiku-5-5") and "coach" in h.agent_model("james"))
h.master_ready = lambda: False
h.llm_chat("manager", [{"role": "user", "content": "status?"}])
check("without Claude, the managers stay on Groq", len(CLAUDE) == n + 1 and LOW and LOW[-1][0] == "/groq")
h.master_ready = lambda: True

# the benchmark
check("GET with nothing run yet", call("GET", "/api/bench", headers=K) == (200, {"ok": True}))
check("needs the dashboard key", call("POST", "/api/bench", body={})[0] == 401)
h.master_ready = lambda: False
s, d = call("POST", "/api/bench", headers=K, body={})
check("without Claude it says why", s == 400 and "Claude isn't available" in d["error"])
h.master_ready = lambda: True
CLAUDE.clear(); chat_before = len(h.store().list_chat(500)); rem_before = len(h.reminders())
s, d = call("POST", "/api/bench", headers=K, body={})
check("runs 6 questions both ways: 12 calls", s == 200 and d["ok"] and len(d["rows"]) == 12 and len(CLAUDE) == 12)
check("all on Haiku at low effort, without the Opus-only fallback", all(b["model"] == "claude-haiku-5-5" and b["output_config"] == {"effort": "low"}
      and "fallbacks" not in b for b in CLAUDE))
off = [b for b in CLAUDE if b.get("thinking") == {"type": "disabled"}]
check("half with thinking off, half with it on", len(off) == 6 and sum(1 for b in CLAUDE if "thinking" not in b) == 6)
check("the first call runs alone (writes the cache), the rest read it", CLAUDE[0]["messages"][0]["content"].count("hey, how's it going?") == 1
      and d["rows"][0]["cache_write"] == 17000 and all(r["cache_read"] == 17000 for r in d["rows"][1:]))
check("the benchmark uses Mistral's real, cached prompt", CLAUDE[0]["system"][0].get("cache_control") and "You're the front desk" in CLAUDE[0]["system"][0]["text"])
on = {r["q"]: r for r in d["rows"] if r["mode"] == "on"}; offr = {r["q"]: r for r in d["rows"] if r["mode"] == "off"}
check("scores what he did against what he should", on["help me plan next month: a trip, my budget and my calendar all together"]["ok"]
      and not offr["help me plan next month: a trip, my budget and my calendar all together"]["ok"]
      and on["who won the Broncos game last night?"]["did"] == "search"
      and on["can you ping me friday afternoon about the car registration?"]["did"] == "remind" and on["hey, how's it going?"]["did"] == "plain")
check("times, tokens and cost on each row", all(isinstance(r["secs"], float) and r["out"] > 0 and r["usd"] > 0 for r in d["rows"]) and d["usd"] > 0)
check("nothing posted to chat and no reminder set", len(h.store().list_chat(500)) == chat_before and len(h.reminders()) == rem_before)
check("the run counts toward the shared Claude spend", h.claude_spend()["calls"] >= 12)
s, d2 = call("GET", "/api/bench", headers=K)
check("Settings can read the last run back", s == 200 and len(d2["rows"]) == 12 and d2["model"] == "claude-haiku-5-5")
check("running again within a minute is refused", call("POST", "/api/bench", headers=K, body={})[0] == 429)
s, page = call("GET", "/settings", headers=K)
check("Settings has the benchmark card", s == 200 and b'id="bench-run"' in page and b"Mistral benchmark" in page)
print("ALL PASS")
