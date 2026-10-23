import sys, json, threading, os, io, time
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
SEEN, DB, GYM = [], {}, []
ROUTE = ["remi, glass"]  # what fake Mistral answers when asked to route
GEMINI_MODELS = ["models/gemini-3.8-flash"]
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/gym/api/hub": return self._send(200, {"coach": "James", "summary": "Units: lb."})
        if self.path.endswith("/models"):
            ids = GEMINI_MODELS if "gemini" in self.path else ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
            return self._send(200, {"data": [{"id": i} for i in ids]})
        self._send(404, {})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/gym/api/hub":
            GYM.append(body); return self._send(200, {"outcome": "answered", "answer": "Train legs today!", "proposedChanges": 0})
        if self.path.startswith("/redis"):
            op, k, a = body[0], body[1], body[2:]
            if op == "INCR": DB[k] = DB.get(k, 0) + 1; r = DB[k]
            elif op == "LPUSH": DB.setdefault(k, []).insert(0, a[0]); r = 1
            elif op == "LTRIM": DB[k] = DB.get(k, [])[int(a[0]):int(a[1]) + 1]; r = "OK"
            elif op == "LRANGE":
                l = DB.get(k, []); e = int(a[1]); r = l[int(a[0]):(None if e == -1 else e + 1)]
            elif op == "HSET": DB.setdefault(k, {}).update(zip(a[::2], a[1::2])); r = 1
            elif op == "HGET": r = DB.get(k, {}).get(a[0])
            elif op == "HMGET": r = [DB.get(k, {}).get(x) for x in a]
            elif op == "HGETALL": r = [x for kv in DB.get(k, {}).items() for x in kv]
            elif op == "SMEMBERS": r = []
            return self._send(200, {"result": r})
        SEEN.append((self.path, body))
        if "You route messages" in body["messages"][-1]["content"]:
            return self._send(200, {"choices": [{"message": {"content": ROUTE[0]}}]})
        who = body["messages"][0]["content"].split(",")[0].replace("You are ", "")
        self._send(200, {"choices": [{"message": {"content": f"{who} here."}}]})
srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="lenz:lk", GEMINI_API_KEY="gk", GROQ_API_KEY="qk",
                  GARAGE_GYM_URL=base + "/gym", GARAGE_GYM_SECRET="gs",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json", RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="t")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.CHAT_MODE = "crew"  # these tests cover each agent answering (CHAT_MODE=crew); test_desk.py covers the front desk
h.list_models = h._list_models  # these tests swap keys mid-run; a deploy would start fresh
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}
from wsgiref.util import setup_testing_defaults
def call(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs,
           "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s)))
    return int(got["s"][:3]), json.loads(out) if out[:1] == b"{" else out
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
K = {"x-dashboard-key": "dk"}
def post(text): return call("POST", "/api/allchat", headers=K, body={"text": text})
print("mode:", mode, h.STORAGE_MODE)

check("mentions: id/name, case, punctuation, dedupe, unknown ignored",
      h.mentioned_agents("hey @Remi, and @james! also @REMI @bob a@red") == ["remi", "james"])
check("mentions capped at 3", h.mentioned_agents("@red @blue @gray @lenz") == ["red", "blue", "gray"])

s, d = post("Morning all, no mentions here")
route_req = SEEN[0][1]
check("no mention: Mistral routes it (on Groq, roster includes James)", SEEN[0][0] == "/groq" and "You route messages" in route_req["messages"][-1]["content"] and "- remi:" in route_req["messages"][-1]["content"] and "- james:" in route_req["messages"][-1]["content"])
check("routed agents reply, status names them", s == 200 and [m["name"] for m in d["messages"][-3:]] == ["You", "Remi", "Glass"] and d["routed"] == ["Remi", "Glass"] and not GYM)
ROUTE[0] = "bob, james, remi, charter"
s, d = post("lift plans and a chart?")
check("routing can pick James (via Garage Gym), capped at 2, unknown ids ignored", d["routed"] == ["James", "Remi"] and GYM[-1]["question"] == "lift plans and a chart?" and d["messages"][-2]["name"] == "James")
GYM.clear()
ROUTE[0] = "Hmm, nobody really."
s, d = post("lol")
check("nothing fits -> Mistral acknowledges it herself", d["routed"] == ["Mistral"] and d["messages"][-1]["name"] == "Mistral")
ROUTE[0] = "remi, glass"
SEEN.clear()
s, d = post("@remi @james what should I do today?")
names = [m["name"] for m in d["messages"]]
check("each mentioned agent replies once, in order, no routing", s == 200 and names[-3:] == ["You", "Remi", "James"] and d["errors"] == {} and d["routed"] == [] and not any("You route" in b["messages"][-1]["content"] for _, b in SEEN))
remi_req = [b for p, b in SEEN if p == "/groq"][-1]
check("Remi sees the thread and knows it's the group chat", "All Agents" in remi_req["messages"][0]["content"] and "You: lol" in remi_req["messages"][1]["content"] and remi_req["model"] == "openai/gpt-oss-120b")
check("James gets the latest message as his question", GYM[-1] == {"question": "@remi @james what should I do today?", "history": []})
check("James's reply text stored", d["messages"][-1]["text"] == "Train legs today!")
n = len(SEEN)
k = os.environ.pop("GROQ_API_KEY"); s, d = post("@glass @mistral budget?"); os.environ["GROQ_API_KEY"] = k
check("a failing agent reports an error, others still reply", s == 200 and "GROQ_API_KEY" in d["errors"]["Glass"] and d["messages"][-1]["name"] == "Mistral")

s, d = call("POST", "/api/allchat", headers={"x-bot-key": "lk"}, body={"bot_id": "lenz", "text": "@remi new movie out! @theta"})
check("bot posts with its key; its mentions trigger nothing", s == 200 and d["messages"][-1]["name"] == "Lenz" and len(SEEN) == n + 1)
check("bot with wrong key 401", call("POST", "/api/allchat", headers={"x-bot-key": "no"}, body={"bot_id": "lenz", "text": "x"})[0] == 401)
check("user post needs dashboard key", call("POST", "/api/allchat", body={"text": "x"})[0] == 401)
check("empty text 400", post("   ")[0] == 400)
s, d = call("GET", "/api/allchat", "key=dk"); check("dashboard reads thread", s == 200 and d["messages"][-1]["name"] == "Lenz")
s, d = call("GET", "/api/allchat", "bot_id=lenz", headers={"x-bot-key": "lk"}); check("bot reads thread with its key", s == 200)
check("reading needs a key", call("GET", "/api/allchat")[0] == 401)
k = os.environ.pop("GROQ_API_KEY"); s, d = post("anyone?"); os.environ["GROQ_API_KEY"] = k
check("routing failure is reported, message still saved", s == 200 and "GROQ_API_KEY" in d["errors"]["Mistral (picking who answers)"] and d["messages"][-1]["text"] == "anyone?")
h.ALLCHAT_AUTO = False; n = len(SEEN); s, d = post("quiet please")
check("ALLCHAT_AUTO off: un-mentioned messages get no replies", d["routed"] == [] and len(SEEN) == n and d["messages"][-1]["text"] == "quiet please")
h.ALLCHAT_KEEP = 4
for i in range(6): post(f"m{i}")
s, d = call("GET", "/api/allchat", "key=dk")
check("thread trimmed to ALLCHAT_KEEP, oldest first", [m["text"] for m in d["messages"]] == ["m2", "m3", "m4", "m5"])

# wiring
s, d = call("GET", "/api/wiring", "key=dk"); w = {r["agent"]: r for r in d["agents"]}
check("wiring: groq agents wired", w["remi"]["state"] == "ok" and w["red"]["state"] == "ok")
check("wiring: gemini agents wired, Theta noted as stand-in", w["mistral"]["state"] == "ok" and "standing in" in w["theta"]["note"])
check("wiring: James via Garage Gym", w["james"]["state"] == "ok")
GEMINI_MODELS[:] = ["models/gemini-4-flash"]
s, d = call("GET", "/api/wiring", "key=dk"); w = {r["agent"]: r for r in d["agents"]}
check("wiring: model not available -> bad with pointer", w["mistral"]["state"] == "bad" and "/api/models" in w["mistral"]["note"])
k = os.environ.pop("GROQ_API_KEY"); s, d = call("GET", "/api/wiring", "key=dk"); os.environ["GROQ_API_KEY"] = k
w = {r["agent"]: r for r in d["agents"]}
check("wiring: missing key -> not set up", w["glass"]["state"] == "off" and w["glass"]["note"] == "GROQ_API_KEY is not set")
h.GARAGE_GYM_SECRET = ""; s, d = call("GET", "/api/wiring", "key=dk"); h.GARAGE_GYM_SECRET = "gs"
check("wiring: James unlinked -> not set up", {r["agent"]: r for r in d["agents"]}["james"]["state"] == "off")
check("wiring needs key", call("GET", "/api/wiring")[0] == 401)
s, page = call("GET", "/", "key=dk"); page = page.decode()
check("chat page defaults to #all-agents; settings has the wiring table", "Message #all-agents" in call("GET", "/chat", "key=dk")[1].decode() and 'id="wiring-rows"' in call("GET", "/settings", "key=dk")[1].decode())
