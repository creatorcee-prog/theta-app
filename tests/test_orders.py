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
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}
from wsgiref.util import setup_testing_defaults
def call(method, path, qs="", headers=None, body=None):
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

# targeted order
s, d = cmd("/commandeer @glass @remi keep dining under $150 this month")
oid = [o for o in h.store().list_active_orders()][0]["id"]
check("targeted: both named agents acknowledge, in character", s == 200 and "Acknowledged by Glass, Remi" in d["result"] and "to Glass, Remi" in d["result"])
acks = [m for m in h.allchat_view() if m["text"].startswith(f"On order #{oid}:")]
check("acks posted in All Agents by each agent", sorted(m["name"] for m in acks) == ["Glass", "Remi"])
ack_prompts = [c["messages"][-1]["content"] for c in CALLS if "The user issued order" in c["messages"][-1]["content"]]
check("ack prompt asks what it will do and what it can't", len(ack_prompts) == 2 and all("outside what you can do" in p for p in ack_prompts))
glass_sys = [c["messages"][0]["content"] for c in CALLS if c["messages"][0]["content"].startswith("You are Glass")][0]
check("Glass's prompt says what he can actually do", "What you can actually do: log expenses" in glass_sys and "can't see bank accounts" in glass_sys)
o = h.store().list_active_orders()[0]
check("acknowledgements recorded on the order", sorted(o["acked_by"]) == ["glass", "remi"] and o["targets"] == ["glass", "remi"])
h._ORDERS_CACHE["at"] = 0
check("standing order in the targets' prompts only", f"#{oid}: @glass @remi keep dining" in h.system_prompt("glass") and f"#{oid}:" not in h.system_prompt("lenz"))
# crew-wide order
n = len(CALLS)
s, d = cmd("/commandeer Everyone be brief today")
oid2 = max(x["id"] for x in h.store().list_active_orders())
check("crew-wide: Theta acknowledges as commander", "Acknowledged by Theta" in d["result"] and len(CALLS) == n + 1)
h._ORDERS_CACHE["at"] = 0
check("crew-wide order reaches everyone's prompt", all(f"#{oid2}: Everyone be brief" in h.system_prompt(a) for a in ("lenz", "glass", "mistral")))
# bots
s, d = call("GET", "/api/orders", "bot_id=lenz", headers={"x-bot-key": "lk"})
check("bots only see their own and crew-wide orders", [x["id"] for x in d] == [oid2])
s, d = call("GET", "/api/orders", "bot_id=glass", headers={"x-bot-key": "gk1"})
check("targeted bot sees both", sorted(x["id"] for x in d) == sorted([oid, oid2]))
# list + close
s, d = cmd("/orders"); listing = h.allchat_view()[-1]["text"]
check("/orders lists targets, sender, expiry, acks", d["result"] == "2 active order(s)." and f"- #{oid} to Glass, Remi (from You, until" in listing and "acknowledged by Glass, Remi" in listing)
s, d = cmd(f"/done #{oid}")
check("/done closes it, event posted", d["result"] == f"Closed order #{oid}." and h.allchat_view()[-1]["text"].startswith(f"You closed order #{oid}"))
h._ORDERS_CACHE["at"] = 0
check("closed order leaves prompts and lists", f"#{oid}:" not in h.system_prompt("glass") and [x["id"] for x in h.store().list_active_orders()] == [oid2])
check("/done twice or junk: clear errors", "No active order" in cmd(f"/done {oid}")[1]["error"] and cmd("/done abc")[1]["error"].startswith("Usage: /done"))
# expiry
check("orders expire after ORDER_DAYS", h.order_live({"expires_at": time.time() - 1}) is False and h.order_live({"expires_at": time.time() + 60}))
check("older orders without expiry count from created_at", not h.order_live({"created_at": "2020-01-01 00:00:00"}) and h.order_live({"created_at": h._now()}))
oid3 = h.store().add_order("old one", "you", expires_at=time.time() - 5)
check("expired orders drop out of the active list", oid3 not in [x["id"] for x in h.store().list_active_orders()])
# Theta's ORDER decisions are standing orders with expiry
call("POST", "/api/escalate", headers={"x-bot-key": "gk1"}, body={"bot_id": "glass", "issue": "x", "target": "master"})
real = h.llm_chat
h.llm_chat = lambda tier, msgs, max_tokens=800: "ORDER: everyone log receipts" if "Escalation #" in msgs[-1]["content"] else "ok"
h.run_round(force=True, only={"theta"}); h.llm_chat = real
t = [x for x in h.store().list_active_orders() if x["issued_by"] == "theta"]
check("Theta's ORDER becomes a standing, expiring order for all", len(t) == 1 and t[0]["expires_at"] and not t[0]["targets"])

# ---- push diagnostics
keys = h.new_vapid_keys()
def diag(pub, priv):
    h.VAPID_PUBLIC_KEY, h.VAPID_PRIVATE_KEY = h._clean_secret(pub), h._clean_secret(priv)
    p = h.push_problem(); return p[0] if p else "ok"
check("no keys", diag("", "") == "no_keys")
check("one key missing", diag(keys["VAPID_PUBLIC_KEY"], "") == "half_keys")
check("swapped", diag(keys["VAPID_PRIVATE_KEY"], keys["VAPID_PUBLIC_KEY"]) == "swapped")
check("garbage", diag("not-a-key!!", keys["VAPID_PRIVATE_KEY"]) in ("bad_format", "bad_public"))
other = h.new_vapid_keys()
check("keys from two different refreshes", diag(keys["VAPID_PUBLIC_KEY"], other["VAPID_PRIVATE_KEY"]) == "mismatch")
check("quotes, spaces and line breaks forgiven", diag(f'"{keys["VAPID_PUBLIC_KEY"][:40]} \n{keys["VAPID_PUBLIC_KEY"][40:]}" ', f"'{keys['VAPID_PRIVATE_KEY']}'\n") == "ok")
s, d = call("GET", "/api/push/health")
check("public health check: status only, no key material", s == 200 and d == {"ok": True, "status": "ok", "devices": 0} and keys["VAPID_PUBLIC_KEY"] not in json.dumps(d))
diag(keys["VAPID_PUBLIC_KEY"], other["VAPID_PRIVATE_KEY"])
s, d = call("GET", "/api/push/key", "key=dk")
check("key endpoint withholds the key and explains a mismatch", d["publicKey"] is None and "aren't a pair" in d["problem"])
check("health reports the mismatch code", call("GET", "/api/push/health")[1]["status"] == "mismatch")
w = {r["agent"]: r for r in h.wiring()}
check("Wiring shows the specific problem", w["push"]["state"] == "bad" and "aren't a pair" in w["push"]["note"])
s, d = call("POST", "/api/push/test", headers=K, body={})
check("test button explains the problem", d["sent"] == 0 and "aren't a pair" in d["error"])
diag("", "")
check("no keys: Wiring says not set up", {r["agent"]: r for r in h.wiring()}["push"]["state"] == "off")
