import sys, json, threading, os, io, time
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as HTTPServer
PLAN = {"gemini": [], "groq": []}  # per provider: list of status codes to return, then 200
HITS = []
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prov = self.path.strip("/")
        HITS.append((prov, body["model"]))
        code = PLAN[prov].pop(0) if PLAN[prov] else 200
        if code == "sleep":
            time.sleep(3); code = 200
        if code == "empty":
            out = json.dumps({"choices": [{"message": {"content": None}}]}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out); return
        if code == 200:
            out = json.dumps({"choices": [{"message": {"content": f"hi from {body['model']}"}}]}).encode()
        else:
            out = json.dumps([{"error": {"code": code, "message": "This model is currently experiencing high demand.", "status": "UNAVAILABLE"}}]).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ.update(DASHBOARD_KEY="dk", GROQ_API_KEY="qk", GEMINI_API_KEY="gk", LLM_TIMEOUT_SECONDS="1",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.PROVIDERS = {"groq": (f"http://127.0.0.1:{port}/groq", "GROQ_API_KEY"), "gemini": (f"http://127.0.0.1:{port}/gemini", "GEMINI_API_KEY")}
h.LLM_RETRY_DELAY = 0
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
M = [{"role": "user", "content": "hi"}]
def run(tier, gemini=(), groq=()):
    PLAN["gemini"], PLAN["groq"] = list(gemini), list(groq); HITS.clear(); h.store().set_meta("llm:cooldown", "{}")
    try:
        return h.llm_chat(tier, M), None
    except h.LLMError as e:
        return None, str(e)

r, e = run("low_brain")
check("healthy: one call, no fallback", r == "hi from gemini-3.8-flash" and len(HITS) == 1)
r, e = run("low_brain", gemini=[503])
check("one 503: retried on Gemini, answered there", r == "hi from gemini-3.8-flash" and HITS == [("gemini", "gemini-3.8-flash")] * 2)
r, e = run("master", gemini=[503, 503])
check("Gemini busy twice: Groq's gpt-oss-120b answers (Theta too)", r == "hi from openai/gpt-oss-120b" and HITS[-1] == ("groq", "openai/gpt-oss-120b"))
fb = json.loads(h.store().get_meta("llm:fallback"))
check("fallback noted for Wiring, with a readable reason", fb["tier"] == "low_brain" and fb["model"] == "openai/gpt-oss-120b"
      and fb["why"] == "gemini returned 503: This model is currently experiencing high demand.")
check("recent_fallback for both Mistral's and Theta's tiers", h.recent_fallback("low_brain")["model"] == "openai/gpt-oss-120b" and h.recent_fallback("master") and not h.recent_fallback("miner"))
r, e = run("low_brain", gemini=[400])
check("a 400 is our mistake: no retry, no fallback", r is None and "400" in e and len(HITS) == 1)
r, e = run("manager", groq=[429, 429])
check("Groq rate-limited: managers fall back to Gemini", r == "hi from gemini-3.8-flash")
r, e = run("low_brain", gemini=[503, 503], groq=[503])
check("both busy: one message naming both", r is None and "gemini returned 503" in e and "fallback, openai/gpt-oss-120b, failed too" in e)
t0 = time.time(); r, e = run("low_brain", gemini=["sleep"])
check("timeout: straight to the fallback, no same-model retry", r == "hi from openai/gpt-oss-120b" and [p for p, _ in HITS] == ["gemini", "groq"] and time.time() - t0 < 2.5)
r, e = run("low_brain", gemini=["empty"])
check("empty reply (spent on thinking): straight to the fallback", r == "hi from openai/gpt-oss-120b" and [p for p, _ in HITS] == ["gemini", "groq"])
h.FALLBACK_LLM["low_brain"] = ("groq", "off")
r, e = run("low_brain", gemini=[503, 503])
check("fallback 'off': the error comes through", r is None and e.startswith("gemini returned 503"))
h.FALLBACK_LLM["low_brain"] = ("groq", "openai/gpt-oss-120b")
k = os.environ.pop("GROQ_API_KEY")
r, e = run("low_brain", gemini=[503, 503])
check("no key for the fallback: the original error, no call to it", r is None and e.startswith("gemini returned 503") and all(p == "gemini" for p, _ in HITS))
os.environ["GROQ_API_KEY"] = k

import json as _j
check("Groq's wording: 'try again in 7.66s' waits ~9s", 8 <= h._quota_wait('Rate limit reached. Please try again in 7.66s.') <= 9.5)
check("'try again in 1m30s' waits ~91s", 90 <= h._quota_wait('Please try again in 1m30.5s.') <= 92.5)
check("unknown 429 waits 30s", h._quota_wait('Too many requests') == 30)
print("done")
