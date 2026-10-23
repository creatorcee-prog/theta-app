import sys, json, threading, os, io, time
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
DB, CALLS = {}, []
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.endswith("/models"): return self._send(200, {"data": [{"id": "openai/gpt-oss-20b"}, {"id": "openai/gpt-oss-120b"}, {"id": "models/gemini-3.8-flash"}]})
        self._send(404, {})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
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
            return self._send(200, {"result": r})
        CALLS.append(body)
        who = body["messages"][0]["content"].split(",")[0].replace("You are ", "")
        self._send(200, {"choices": [{"message": {"content": f"{who} will do it, within limits."}}]})
srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="glass:gk1,lenz:lk", GROQ_API_KEY="qk", GEMINI_API_KEY="gk",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g",
                  VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="t")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.ROUND_POSTS = "agents"  # these tests read each agent's own round post; test_rounds2 covers the summary
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}
from wsgiref.util import setup_testing_defaults
def call0(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s)))
    return int(got["s"][:3]), json.loads(out) if out[:1] in (b"{", b"[") else out
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
K = {"x-dashboard-key": "dk"}
def cmd(text): return call("POST", "/api/allchat", headers=K, body={"text": text})
print("mode:", mode)
import urllib.error
def call(method, path, qs="", headers=None, body=None, ip="1.2.3.4"):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)),
           "wsgi.input": io.BytesIO(raw), "HTTP_X_FORWARDED_FOR": f"{ip}, 10.0.0.1"}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s, h=dict(hd))))
    return int(got["s"][:3]), (json.loads(out) if out[:1] in (b"{", b"[") else out), got["h"]
PUSHED = []
h.notify = lambda title, body, url="/": PUSHED.append((title, body, url)) or 1
# headers
s, _, hd = call("GET", "/avatar/qwerty.svg")
check("every response carries the security headers", hd["X-Frame-Options"] == "DENY" and hd["X-Content-Type-Options"] == "nosniff"
      and "frame-ancestors 'none'" in hd["Content-Security-Policy"] and hd["Referrer-Policy"] == "strict-origin-when-cross-origin")
check("QWERTY is on the crew with his own avatar and channel", "qwerty" in h.AGENTS and "qwerty" in h.ROUND_JOBS
      and h.home_channel("qwerty") == "dev" and call("GET", "/avatar/qwerty.svg")[1] != call("GET", "/avatar/hub.svg")[1])
# lockout
for i in range(h.SEC_MAX_FAILS - 1):
    assert call("GET", "/", "key=wrong", ip="6.6.6.6")[0] == 401
check("under the limit: still 401s, no alert", not PUSHED and call("GET", "/", "key=wrong", ip="6.6.6.6")[0] == 401)
check("at the limit: locked out, pushed, posted in #dev-and-security", PUSHED and PUSHED[-1][0] == "QWERTY" and "6.6.6.6" in PUSHED[-1][1]
      and any("6.6.6.6" in m["text"] for m in h.allchat_view(channel="dev")))
h._SEC_CACHE["at"] = 0
check("locked: even the right key gets 429", call("GET", "/", "key=dk", ip="6.6.6.6")[0] == 429)
check("locked: the app's assets still load", call("GET", "/ui.css", ip="6.6.6.6")[0] == 200)
check("other addresses unaffected", call("GET", "/", "key=dk", ip="7.7.7.7")[0] == 200)
n = len(PUSHED)
call("GET", "/", "key=wrong", ip="6.6.6.6")
check("no second alert while locked", len(PUSHED) == n)
st = h._meta_json("sec:fails", {})
st["6.6.6.6"]["locked_until"] = time.time() - 1; h.store().set_meta("sec:fails", json.dumps(st)); h._SEC_CACHE["at"] = 0
check("after the lockout ends, the right key works", call("GET", "/", "key=dk", ip="6.6.6.6")[0] == 200)
# secrets in chat
SEEN_PROMPTS = []
real_llm = h.llm_chat
def spy_llm(tier, messages, max_tokens=800):
    SEEN_PROMPTS.append(json.dumps(messages))
    if "GitHub issue" in messages[-1]["content"]:
        return "## What's wrong\nPosters missing.\n## Suggested fix\nRetry Jikan."
    return real_llm(tier, messages, max_tokens)
h.llm_chat = spy_llm
key = "gsk_" + "A1b2C3d4" * 6
s, d, _ = call("POST", "/api/allchat", headers=K, body={"text": f"@mistral here's my groq key {key} and the dashboard key dk1234567890 ok?"})
mine = [m for m in h.allchat_view(200) if m["from"] == "you"][-1]["text"]
check("a pasted Groq key is hidden before it's saved", key not in mine and "[hidden by QWERTY]" in mine)
check("...and before any model sees it", not any(key in p for p in SEEN_PROMPTS))
check("QWERTY warns you to rotate it, with a push", any("rotate it" in m["text"] and "a Groq API key" in m["text"] for m in h.allchat_view(channel="dev"))
      and PUSHED[-1][0] == "QWERTY")
h.DASHBOARD_KEY = "dk1234567890"
t, found = h.redact_secrets("my key is dk1234567890, also -----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY----- and AKIAABCDEFGHIJKLMNOP")
check("your own dashboard key, private keys and AWS keys are hidden too", "dk1234567890" not in t and "abc" not in t and "AKIA" not in t
      and set(found) == {"your dashboard key", "a private key", "an AWS access key"})
h.DASHBOARD_KEY = "dk"
n = len([m for m in h.allchat_view(200, channel="dev")])
s, _, _ = call("POST", "/api/allchat", body={"text": f"no key here but {key}"}, ip="9.9.9.9")
check("without the key: refused, and nothing posted or warned", s == 401 and len(h.allchat_view(200, channel="dev")) == n)
check("normal text untouched", h.redact_secrets("ask-a-question about sk-ills") == ("ask-a-question about sk-ills", []))
# library vulnerabilities (OSV)
class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass
real_urlopen = h.urllib.request.urlopen
GH = {"mode": "ok"}
def fake_urlopen(req, timeout=None):
    url = getattr(req, "full_url", req)
    if "api.osv.dev" in url:
        qs = json.loads(req.data)["queries"]
        return Resp(json.dumps({"results": [{"vulns": [{"id": "GHSA-test-0001"}]} if q["package"]["name"] == "pywebpush" else {}
                                            for q in qs]}).encode())
    if "api.github.com" in url:
        assert req.headers["Authorization"] == "Bearer ghtok"
        if GH["mode"] == "denied":
            raise urllib.error.HTTPError(url, 403, "nope", {}, None)
        body = json.loads(req.data)
        assert "[hidden" not in body["title"]
        return Resp(json.dumps({"html_url": "https://github.com/x/y/issues/7"}).encode())
    return real_urlopen(req, timeout=timeout)
h.urllib.request.urlopen = fake_urlopen
vulns = h.dependency_vulns()
check("OSV: finds the vulnerable package among what's installed", any(n == "pywebpush" and ids == ["GHSA-test-0001"] for n, v, ids in vulns))
PUSHED.clear()
h.store().set_meta("sec:osv_at", "0")
r = h.run_round(force=True, only=["qwerty"])
check("QWERTY's round checks the libraries weekly: " + r["ran"]["qwerty"]["did"], "with known holes" in r["ran"]["qwerty"]["did"])
qw = [m for m in h.allchat_view(200, channel="dev") if m["from"] == "qwerty"][-1]["text"]

check("his report lists it as fix-now, and pushes it", "[!] pywebpush" in qw and any("pywebpush" in p[1] for p in PUSHED))
n = len(h.allchat_view(200, channel="dev"))
r = h.run_round(force=True, only=["qwerty"])
check("same findings next round: no repeat post", r["ran"]["qwerty"]["did"] == "nothing new" and len(h.allchat_view(200, channel="dev")) == n)
r = h.run_round(force=True, only=["qwerty"])
check("within the week and nothing updated: no new library check", "checked the libraries" not in r["ran"]["qwerty"]["did"])
h.store().set_meta("sec:osv_fp", "an-older-deploy")
r = h.run_round(force=True, only=["qwerty"])
check("a deploy that changed the packages: checked again at once", "checked the libraries" in r["ran"]["qwerty"]["did"]
      and h.store().get_meta("sec:osv_fp") == h.installed_fingerprint())
check("short key flagged", any("only 2 characters" in t for _, t in h.watchdog_findings()))
# coding help
h.GITHUB_TOKEN = ""  # (this sandbox has one in its environment)
s, d, _ = call("POST", "/api/allchat", headers=K, body={"text": "/issue Lenz posters missing - Jikan seems down"})
check("/issue without a token: QWERTY writes it up in #dev-and-security", s == 200 and "wrote it up" in d["result"]
      and "Retry Jikan" in h.allchat_view(channel="dev")[-1]["text"])
h.GITHUB_TOKEN = "ghtok"
s, d, _ = call("POST", "/api/allchat", headers=K, body={"text": "/issue Lenz posters missing - Jikan seems down"})
check("/issue with a token: filed, link posted", "https://github.com/x/y/issues/7" in d["result"])
GH["mode"] = "denied"
s, d, _ = call("POST", "/api/allchat", headers=K, body={"text": "/issue another one"})
check("GitHub refusal explained", s == 400 and "GITHUB_TOKEN" in d["error"])
s, d, _ = call("POST", "/api/allchat", headers=K, body={"text": "/security"})
check("/security posts what he sees", s == 200 and "Security and health right now" in h.allchat_view(channel="dev")[-1]["text"])
check("his prompt knows how the hub is built and what's wrong", "api/index.py" in h.system_prompt("qwerty") and "pywebpush" in h.system_prompt("qwerty"))
s, page, _ = call("GET", "/settings", headers=K)
check("Settings has QWERTY's Security card", b'id="security"' in page and b"pywebpush" in page and b"Fix now" in page)
s, page, _ = call("GET", "/", headers=K)
check("Home has QWERTY's window", b'href="/settings#security"' in page)
h.urllib.request.urlopen = real_urlopen
print("done")
