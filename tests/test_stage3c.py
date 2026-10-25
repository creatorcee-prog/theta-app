"""Stage 3c: File and Image Attachments.

Extends the existing single-image attach path (see test_vision.py) to
multiple attachments plus PDF/text files, without changing model
routing or adding any service:

- Client: multi picker (images, PDF, text), preview strip with image
  thumbs and file chips (name, type, size), per-item removal,
  client-side type/size/count/combined-size validation.
- Server: the whole batch is validated before anything is saved;
  images keep the existing upload path, files are sniffed by content
  (PDF magic, else UTF-8 text) and served under the same key-required
  /upload/ route. Messages carry attachments [{url, name, kind}]
  plus the legacy image field (= first image) for old messages.
- Models: every image gets the existing vision treatment (Claude
  sees them directly, everyone else gets the cached Gemini
  descriptions, joined). Files are NOT read by any model: agents
  get an honest note with names only.
- Failure behavior: a rejected batch saves nothing; a failed send
  restores the whole attachment list into the composer, so retry
  is just pressing send again.
"""
import sys, json, threading, os, base64
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
DB, GEMINI_CALLS = {}, []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.endswith("/models"):
            return self._send(200, {"data": [{"id": "openai/gpt-oss-20b"}, {"id": "openai/gpt-oss-120b"}]})
        self._send(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"] or 0)))
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
            else: r = None
            return self._send(200, {"result": r})
        if self.path.startswith("/gemini"):
            GEMINI_CALLS.append(body)
            n = len(GEMINI_CALLS)
            return self._send(200, {"choices": [{"message": {"content": f"Description {n}."}}]})
        return self._send(200, {"choices": [{"message": {"content": "Crew reply ok."}}]})


srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="lenz:lk", GEMINI_API_KEY="gk", GROQ_API_KEY="qk",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="tok")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}
from wsgiref.util import setup_testing_defaults


def call(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs,
           "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)), "wsgi.input": __import__("io").BytesIO(raw)}
    setup_testing_defaults(env)
    if headers:
        for k, v in headers.items():
            env["HTTP_" + k.upper().replace("-", "_")] = v
    out = {}
    def start(status, hdrs, exc=None):
        out["status"] = int(status.split()[0]); out["headers"] = dict(hdrs)
    res = b"".join(h.app(env, start))
    try:
        return out["status"], json.loads(res) if res else None, out["headers"]
    except ValueError:
        return out["status"], res, out["headers"]


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


K = {"x-dashboard-key": "dk"}
JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0fake").decode()
PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNGfake").decode()


def b64_text(s):
    return "data:text/plain;base64," + base64.b64encode(s.encode()).decode()


def b64_pdf():
    return "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 fake pdf").decode()


def mine():
    _s, r, _h = call("GET", "/api/allchat", headers=K)
    return [m for m in r["messages"] if m["from"] == "you"][-1]


def post(atts, text="hello", channel="all"):
    body = {"text": text, "channel": channel}
    if atts is not None:
        body["attachments"] = atts
    return call("POST", "/api/allchat", headers=K, body=body)


# --- validation matrix (unit level, no HTTP) ---
try:
    h.validate_attachments([{"name": "x.exe", "type": "file",
                             "data": "data:application/octet-stream;base64," + base64.b64encode(b"\x89\x00\xff\x00").decode()}])
    check("bad type refused", False)
except ValueError as e:
    check("bad type refused", "isn't a type" in str(e))
try:
    h.validate_attachments([{"name": "empty.txt", "type": "file", "data": b64_text("")}])
    check("empty file refused", False)
except ValueError as e:
    check("empty file refused", "is empty" in str(e))
try:
    h.validate_attachments([{"name": "big.txt", "type": "file", "data": b64_text("a" * (3_000_001))}])
    check("oversize single refused", False)
except ValueError as e:
    check("oversize single refused", "too big" in str(e))
try:
    h.validate_attachments([{"name": f"f{i}.txt", "type": "file", "data": b64_text("a" * 2_000_000)} for i in range(2)])
    check("oversize combined refused", False)
except ValueError as e:
    check("oversize combined refused", "together are too big" in str(e))
try:
    h.validate_attachments([{"name": f"f{i}.txt", "type": "file", "data": b64_text("x")} for i in range(5)])
    check("too many refused", False)
except ValueError as e:
    check("too many refused", "at most 4" in str(e))
try:
    h.validate_attachments([{"name": "bad.txt", "type": "file", "data": "data:text/plain;base64,!!!"}])
    check("bad base64 refused", False)
except ValueError as e:
    check("bad base64 refused", "didn't come through whole" in str(e))
check("pdf sniffed by magic, not mime",
      h.save_file("doc.pdf", "data:application/octet-stream;base64," + base64.b64encode(b"%PDF-1.4 x").decode())[0].endswith(".pdf"))
check("md keeps its extension",
      h.save_file("n.md", b64_text("# hi"))[0].endswith(".md"))
check("filename sanitized (no paths)",
      h._clean_filename("../../etc/passwd") == "passwd"
      and h._clean_filename("a/b\\c.txt") == "c.txt")

# --- HTTP: mixed batch saves, associates, serves ---
s, r, _ = post([{"name": "a.jpg", "type": "image", "data": JPEG},
                {"name": "b.png", "type": "image", "data": PNG},
                {"name": "doc.pdf", "type": "file", "data": b64_pdf()},
                {"name": "notes.txt", "type": "file", "data": b64_text("hello file")}],
               text="mixed batch", channel="money")
m = mine()
check("mixed batch accepted", s == 200 and len(m.get("attachments", [])) == 4)
check("legacy image = first image", m.get("image", "").startswith("/upload/") and m["image"].endswith(".jpeg"))
check("message stays on its channel", m.get("ch") == "money")
pdf_url = [a["url"] for a in m["attachments"] if a["name"] == "doc.pdf"][0]
s, data, hd = call("GET", pdf_url, headers=K)
check("pdf served with its type", s == 200 and hd.get("Content-Type") == "application/pdf" and data == b"%PDF-1.4 fake pdf")
txt_url = [a["url"] for a in m["attachments"] if a["name"] == "notes.txt"][0]
s, data, hd = call("GET", txt_url, headers=K)
check("text served with its type", s == 200 and hd.get("Content-Type") == "text/plain" and data == b"hello file")
s, _r, _h = call("GET", pdf_url)
check("upload still needs the key", s == 401)
s, _r, _h = call("GET", "/upload/0123456789ab.pdf", headers=K)
check("bad upload path is 404", s == 404)

# --- atomicity: a rejected batch saves nothing ---
before = len(call("GET", "/api/allchat", headers=K)[1]["messages"])
before_up = len(h._meta_json("uploads", []))
s, r, _ = post([{"name": "ok.txt", "type": "file", "data": b64_text("ok")},
                {"name": "bad.exe", "type": "file",
                 "data": "data:application/octet-stream;base64," + base64.b64encode(b"\x89\x00\xff").decode()}],
               text="should not save")
after = len(call("GET", "/api/allchat", headers=K)[1]["messages"])
check("rejected batch saves nothing", s == 400 and "bad.exe" in r["error"] and after == before
      and len(h._meta_json("uploads", [])) == before_up)

# --- legacy single-image field still works ---
s, r, _ = call("POST", "/api/allchat", headers=K, body={"text": "legacy", "image": JPEG, "channel": "all"})
m = mine()
check("legacy image field still works", s == 200 and m.get("image", "").startswith("/upload/"))

# --- vision: every image described, files only named ---
GEMINI_CALLS.clear()
s, r, _ = post([{"name": "a.jpg", "type": "image", "data": JPEG},
                {"name": "b.png", "type": "image", "data": PNG},
                {"name": "doc.pdf", "type": "file", "data": b64_pdf()}], text="look at these")
m = mine()
notes = h.seen_notes(m)
check("each image gets a vision description", notes.count("Description") == 2 and "---" in notes)
check("files are named, not summarized", "doc.pdf" in notes and "cannot open or read" in notes)

# --- shipped chat JS + markup carry the new UI ---
s, chat_js, _h = call("GET", "/chat.js")
chat_js = chat_js.decode() if isinstance(chat_js, bytes) else chat_js
check("chat.js has multi attach UI", "takeFiles" in chat_js and "renderAtts" in chat_js
      and "setAtts(savedAtts)" in chat_js and "fchip" in chat_js and "fmtSize" in chat_js)
s, chat_html, _h = call("GET", "/chat", headers=K)
chat_html = chat_html.decode() if isinstance(chat_html, bytes) else chat_html
check("composer markup: multi picker + strip",
      'id="chat-file" accept="image/*,.pdf,.txt,.md" multiple' in chat_html
      and 'id="chat-attach"' in chat_html)
print("done")
