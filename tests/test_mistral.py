import sys, json, threading, os, io, time, ssl, base64, datetime as dtmod, ipaddress
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta, date
from email.utils import format_datetime
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
import http_ece
import tempfile
S = tempfile.mkdtemp()  # the fake push service's throwaway TLS certificate goes here
# --- self-signed TLS for the fake push service
key = ec.generate_private_key(ec.SECP256R1())
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(1).not_valid_before(datetime.now(dtmod.timezone.utc) - timedelta(days=1)).not_valid_after(datetime.now(dtmod.timezone.utc) + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), True).sign(key, hashes.SHA256()))
open(S + "/push_cert.pem", "wb").write(cert.public_bytes(serialization.Encoding.PEM))
open(S + "/push_key.pem", "wb").write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
os.environ["REQUESTS_CA_BUNDLE"] = S + "/push_cert.pem"
# --- the phone: device keys
dev = ec.generate_private_key(ec.SECP256R1())
b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
auth = os.urandom(16)
p256dh = b64(dev.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
PUSHES, PUSH_STATE = [], {"code": 201}
class Push(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if "gone" in self.path:
            self.send_response(410); self.send_header("Content-Length", "0"); self.end_headers(); return
        if PUSH_STATE["code"] == 201:
            plain = http_ece.decrypt(body, private_key=dev, auth_secret=auth, version="aes128gcm")
            PUSHES.append({"auth": self.headers.get("Authorization"), "ttl": self.headers.get("TTL"), "urgency": self.headers.get("Urgency"), "msg": json.loads(plain), "path": self.path})
        self.send_response(PUSH_STATE["code"]); self.send_header("Content-Length", "0"); self.end_headers()
psrv = HTTPServer(("127.0.0.1", 0), Push)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(S + "/push_cert.pem", S + "/push_key.pem")
psrv.socket = ctx.wrap_socket(psrv.socket, server_side=True)
threading.Thread(target=psrv.serve_forever, daemon=True).start()
ENDPOINT = f"https://127.0.0.1:{psrv.server_address[1]}/push/device1"
# --- fake world: news, calendar, models, redis
NOW = time.time(); TODAY = datetime.now(__import__("zoneinfo").ZoneInfo("America/Denver")).date()
def rss(title, items):
    body = "".join(f"<item><title>{t}</title><link>https://n/{abs(hash(t))}</link><pubDate>{format_datetime(datetime.fromtimestamp(NOW - 600, dtmod.timezone.utc))}</pubDate></item>" for t in items)
    return f"<rss><channel><title>{title}</title>{body}</channel></rss>".encode()
TOMORROW = (TODAY + timedelta(days=1)).strftime("%m-%d")
ICS = "\r\n".join(["BEGIN:VCALENDAR", "BEGIN:VEVENT", "UID:a", f"DTSTART;TZID=America/Denver:{TODAY:%Y%m%d}T090000",
                   f"DTEND;TZID=America/Denver:{TODAY:%Y%m%d}T100000", "SUMMARY:Dentist", "END:VEVENT", "END:VCALENDAR"])
FEEDS = {"/a.xml": rss("Outlet A", ["BREAKING: Big Quake Hits Coast", "Senate Passes Bill"]), "/cal.ics": ICS.encode()}
DB, LLM = {}, []
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj, raw=None):
        b = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path in FEEDS: return self._send(200, None, FEEDS[self.path])
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
            elif op == "SADD": DB.setdefault(k, set()).update(a); r = 1
            elif op == "SMEMBERS": r = sorted(DB.get(k, set()))
            return self._send(200, {"result": r})
        LLM.append(body); last = body["messages"][-1]["content"]
        reply = "THETA: we need a decision on the server bill." if "urgent" in last else ("Handled: try restarting it." if "Escalation #" in last else "Morning!")
        self._send(200, {"choices": [{"message": {"content": reply}}]})
srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="remi:rk", GROQ_API_KEY="qk", GEMINI_API_KEY="gk",
                  NEWS_FEEDS=f"{base}/a.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g",
                  REMI_CALENDAR_URLS=f"{base}/cal.ics", BIRTHDAYS=f"Sam:{TOMORROW}", GLASS_BUDGETS="Dining:100")
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
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s, h=hd)))
    return int(got["s"][:3]), (json.loads(out) if out[:1] == b"{" else out), dict(got["h"])
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
K = {"x-dashboard-key": "dk"}
print("mode:", mode)

# PWA files
s, body, hd = call("GET", "/manifest.webmanifest", headers={"cookie": "hub_key=dk"})
m = body
check("manifest: standalone, icons, signed-in start_url", s == 200 and hd["Content-Type"] == "application/manifest+json" and m["display"] == "standalone" and m["start_url"] == "/?key=dk")
check("manifest without login doesn't leak the key", call("GET", "/manifest.webmanifest")[1]["start_url"] == "/")
s, png, hd = call("GET", "/icon-192.png")
check("icons are real PNGs of the right size", png[:8] == b"\x89PNG\r\n\x1a\n" and int.from_bytes(png[16:20], "big") == 192 and int.from_bytes(call("GET", "/apple-touch-icon.png")[1][16:20], "big") == 180)
check("service worker served", b"showNotification" in call("GET", "/sw.js")[1])
s, page, _ = call("GET", "/", "key=dk", headers={"host": "hub.example.app"}); page = page.decode()
check("home: viewport, manifest, icon", 'name="viewport"' in page and 'rel="manifest"' in page and "apple-touch-icon" in page)
check("home: push controls (moved from Settings, Stage 2)", 'id="push-on"' in call("GET", "/", "key=dk", headers={"host": "hub.example.app"})[1].decode())
check("dashboard records its origin for the push subject", h.store().get_meta("hub:origin") == "https://hub.example.app")

# keys + subscription
check("no keys yet: key endpoint says so; notify is a no-op", call("GET", "/api/push/key", "key=dk")[1]["publicKey"] is None and h.notify("x", "y") == 0)
s, keys, _ = call("GET", "/api/push/new-keys", "key=dk")
check("new-keys makes a valid pair", s == 200 and len(base64.urlsafe_b64decode(keys["VAPID_PUBLIC_KEY"] + "==")) == 65 and len(base64.urlsafe_b64decode(keys["VAPID_PRIVATE_KEY"] + "=")) == 32)
check("new-keys needs the key", call("GET", "/api/push/new-keys")[0] == 401)
h.VAPID_PUBLIC_KEY, h.VAPID_PRIVATE_KEY = keys["VAPID_PUBLIC_KEY"], keys["VAPID_PRIVATE_KEY"]
check("subscribe rejects junk", call("POST", "/api/push/subscribe", headers=K, body={"subscription": {"endpoint": "http://x"}})[0] == 400)
sub = {"endpoint": ENDPOINT, "keys": {"p256dh": p256dh, "auth": b64(auth)}, "expirationTime": None}
s, d, _ = call("POST", "/api/push/subscribe", headers=K, body={"subscription": sub})
s2, d2, _ = call("POST", "/api/push/subscribe", headers=K, body={"subscription": sub})
check("subscribe stores the device once", d["ok"] and d2["devices"] == 1)
s, d, _ = call("POST", "/api/push/test", headers=K, body={})
p = PUSHES[-1]
check("test push decrypts on the phone with the right text", d["sent"] == 1 and p["msg"] == {"title": "Mistral", "body": "Test: phone notifications from Theta work.", "url": "/"})
check("VAPID-signed for this key, with a TTL", p["auth"].startswith("vapid t=") and f"k={keys['VAPID_PUBLIC_KEY']}" in p["auth"] and p["ttl"] == "3600")
jwt = p["auth"].split("t=")[1].split(",")[0]
claims = json.loads(base64.urlsafe_b64decode(jwt.split(".")[1] + "=="))
check("JWT subject is the hub origin; audience is the push service", claims["sub"] == "https://hub.example.app" and claims["aud"].startswith("https://127.0.0.1:"))
check("test result names the device and Apple/Google accepted it", d["results"] and d["results"][0]["ok"] and d["results"][0]["code"] == 201)
check("pushes are sent with high urgency (Low Power Mode)", p["urgency"] == "high")
dead = {"endpoint": ENDPOINT.replace("device1", "gone1"), "keys": sub["keys"]}
call("POST", "/api/push/subscribe", headers={**K, "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) Mobile/15E148"}, body={"subscription": dead})
s, d, _ = call("POST", "/api/push/test", headers=K, body={})
bad = [x for x in d["results"] if not x["ok"]]
check("a removed/re-added app's dead sign-up is reported and dropped", d["sent"] == 1 and len(bad) == 1 and "iPhone" in bad[0]["device"]
      and "no longer exists" in bad[0]["why"] and len(h.push_subs()) == 1)
check("Settings shows the device with notifications on", b"Notifications on" in call("GET", "/settings", "key=dk")[1])
call("POST", "/api/push/subscribe", headers=K, body={"subscription": dead})
rid = [x["id"] for x in h.devices_report()["push"] if "gone1" in ""] or [__import__("hashlib").sha1(dead["endpoint"].encode()).hexdigest()[:10]]
s, d, _ = call("POST", "/api/push/remove", headers=K, body={"id": rid[0]})
check("a stale notification device can be removed", s == 200 and len(h.push_subs()) == 1)
check("removing needs the key", call("POST", "/api/push/remove", body={"id": rid[0]})[0] == 401)
w = {r["agent"]: r for r in h.wiring()}
check("wiring: notifications OK with 1 device", w["push"]["state"] == "ok" and "1 device" in w["push"]["note"])

# round: digest, breaking, birthdays, triage
PUSHES.clear()
call("POST", "/api/escalate", headers={"x-bot-key": "rk"}, body={"bot_id": "remi", "issue": "Calendar sync keeps failing"})
call("POST", "/api/escalate", headers={"x-bot-key": "rk"}, body={"bot_id": "remi", "issue": "urgent: server bill doubled"})
h.add_expense(130, "Dining", "dinner")
h.DIGEST_TIME = "00:00"
r = h.run_round(force=True)
did = r["ran"]["mistral"]["did"]
check("Mistral's round: digest, breaking, triage, wiring", "posted the morning digest" in did and "flagged breaking news" in did and "handled #" in did and "forwarded #" in did)
msgs = [m for m in h.allchat_view() if m["from"] == "mistral"]
digest = [m["text"] for m in msgs if "Here's today" in m["text"]][0]
check("digest from real data", digest.startswith("Morning!\nHere's today") and "Calendar: 9 AM–10 AM: Dentist" in digest and "Birthday: Sam's birthday tomorrow." in digest and "- BREAKING: Big Quake Hits Coast (Outlet A)" in digest and "Budget: over in Dining ($130 of $100)" in digest)
bodies = [x["msg"]["body"] for x in PUSHES]
check("digest one-liner pushed", any(b.startswith("1 event · Sam's birthday · ") and "Dining over budget" in b for b in bodies))
check("breaking pushed with its link", any(x["msg"]["body"] == "Breaking (Outlet A): BREAKING: Big Quake Hits Coast" and x["msg"]["url"].startswith("https://n/") for x in PUSHES))
check("Remi's birthday and Glass's alert pushed via Mistral", "Remi: Sam's birthday is tomorrow." in bodies and "Glass: Dining is over budget: $130.00 of $100." in bodies)
check("triage: handled one in chat, forwarded the urgent one to Theta", any(m["text"].startswith("On #") and "Handled: try restarting it." in m["text"] for m in msgs) and any("needs Theta, so I passed it up as #" in m["text"] for m in msgs) and any(b.startswith("Escalated to Theta: urgent") for b in bodies))
master = [e for e in h.store().list_escalations(50, open_only=True) if e["to_role"] == "master"]
check("forwarded escalation exists for Theta", len(master) == 1 and master[0]["from_bot"] == "mistral")
n = len(PUSHES); r = h.run_round(force=True)
check("next round: no repeat digest, breaking or triage", r["ran"]["mistral"]["did"] == "nothing new" and not [x for x in PUSHES[n:] if x["msg"]["body"].startswith(("Breaking", "Escalated", "1 event"))])

# dead device dropped
PUSH_STATE["code"] = 410
check("410 Gone: device dropped", h.notify("Mistral", "x") == 0 and h.push_subs() == [])
check("wiring: no device yet", {r["agent"]: r for r in h.wiring()}["push"]["state"] == "off")
