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
import base64, hashlib
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def cb(v):
    def head(major, n):
        if n < 24: return bytes([major << 5 | n])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * size): return bytes([major << 5 | info]) + n.to_bytes(size, "big")
    if isinstance(v, bool): return bytes([0xf5 if v else 0xf4])
    if isinstance(v, int): return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, bytes): return head(2, len(v)) + v
    if isinstance(v, str): return head(3, len(v.encode())) + v.encode()
    if isinstance(v, list): return head(4, len(v)) + b"".join(cb(x) for x in v)
    if isinstance(v, dict): return head(5, len(v)) + b"".join(cb(k) + cb(x) for k, x in v.items())
H = {"host": "theta.example"}; HK = dict(H, **K); ORIGIN = "https://theta.example"
RPH = hashlib.sha256(b"theta.example").digest()
priv = ec.generate_private_key(ec.SECP256R1()); nums = priv.public_key().public_numbers()
cred = os.urandom(16)
s, page, _ = call("GET", "/", headers=H)
check("signed-out home shows the sign-in page", s == 401 and b"Face ID" in page and b"<html" in page.lower())
s, r, _ = call("GET", "/api/passkey/options", "type=register", headers=H)
check("register options need the key", s == 401)
s, r, _ = call("GET", "/api/passkey/options", "type=register", headers=HK)
check("register options", s == 200 and r["rpId"] == "theta.example" and r["challenge"] and r["userId"])
def reg(challenge, flags=0x45, origin=ORIGIN, alg=-7):
    cose = {1: 2, 3: alg, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")}
    auth = RPH + bytes([flags]) + (0).to_bytes(4, "big") + bytes(16) + len(cred).to_bytes(2, "big") + cred + cb(cose)
    cd = json.dumps({"type": "webauthn.create", "challenge": challenge, "origin": origin}).encode()
    return {"clientDataJSON": b64u(cd), "attestationObject": b64u(cb({"fmt": "none", "attStmt": {}, "authData": auth})),
            "name": "Test iPhone"}
s, r, _ = call("POST", "/api/passkey/register", headers=HK, body=reg("made-up"))
check("unknown challenge refused", s == 400 and "challenge" in r["error"])
ch = call("GET", "/api/passkey/options", "type=register", headers=HK)[1]["challenge"]
s, r, _ = call("POST", "/api/passkey/register", headers=HK, body=reg(ch, origin="https://evil.example"))
check("wrong origin refused", s == 400 and "origin" in r["error"])
ch = call("GET", "/api/passkey/options", "type=register", headers=HK)[1]["challenge"]
s, r, _ = call("POST", "/api/passkey/register", headers=HK, body=reg(ch, flags=0x41))
check("no user verification refused", s == 400 and "verify" in r["error"])
ch = call("GET", "/api/passkey/options", "type=register", headers=HK)[1]["challenge"]
s, r, _ = call("POST", "/api/passkey/register", headers=HK, body=reg(ch))
check("registered", s == 200 and r["name"] == "Test iPhone" and len(h.passkeys()) == 1)
s, r, _ = call("POST", "/api/passkey/register", headers=HK, body=reg(ch))
check("challenge can't be reused", s == 400)
def login(challenge, count=1, key=priv, origin=ORIGIN, cid=cred):
    auth = RPH + bytes([0x05]) + count.to_bytes(4, "big")
    cd = json.dumps({"type": "webauthn.get", "challenge": challenge, "origin": origin}).encode()
    sig = key.sign(auth + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
    return {"id": b64u(cid), "clientDataJSON": b64u(cd), "authenticatorData": b64u(auth), "signature": b64u(sig)}
ch = call("GET", "/api/passkey/options", "type=login", headers=H)[1]["challenge"]
s, r, hd = call("POST", "/api/passkey/login", headers=H, body=login(ch, key=ec.generate_private_key(ec.SECP256R1())), ip="5.5.5.5")
check("wrong key's signature refused", s == 401 and "Set-Cookie" not in hd)
ch = call("GET", "/api/passkey/options", "type=login", headers=H)[1]["challenge"]
s, r, hd = call("POST", "/api/passkey/login", headers=H, body=login(ch, cid=os.urandom(16)), ip="5.5.5.5")
check("unknown device refused", s == 401 and "registered" in r["error"])
ch = call("GET", "/api/passkey/options", "type=login", headers=H)[1]["challenge"]
s, r, hd = call("POST", "/api/passkey/login", headers=H, body=login(ch, count=5), ip="5.5.5.5")
check("signed in: own session cookie, not the key", s == 200 and "hub_sess=" in hd.get("Set-Cookie", "") and "hub_key=dk" not in hd.get("Set-Cookie", "") and "HttpOnly" in hd["Set-Cookie"])
s, page, _ = call("GET", "/", headers=dict(H, cookie="hub_key=dk"))
check("cookie opens the home page", s == 200)
ch = call("GET", "/api/passkey/options", "type=login", headers=H)[1]["challenge"]
s, r, hd = call("POST", "/api/passkey/login", headers=H, body=login(ch, count=3), ip="5.5.5.5")
check("counter going backwards refused", s == 401 and "copied" in r["error"])
ch = call("GET", "/api/passkey/options", "type=register", headers=HK)[1]["challenge"]
s, r, hd = call("POST", "/api/passkey/login", headers=H, body=login(ch, count=9), ip="5.5.5.5")
check("register challenge can't sign in", s == 401)
s, page, _ = call("GET", "/settings", headers=HK)
check("Settings lists the device", b"Test iPhone" in page)
s, r, _ = call("POST", "/api/passkey/remove", headers=H, body={"id": b64u(cred)})
check("remove needs the key", s == 401 and len(h.passkeys()) == 1)
s, r, _ = call("POST", "/api/passkey/remove", headers=HK, body={"id": b64u(cred)})
check("removed", s == 200 and h.passkeys() == [])
print("done")
