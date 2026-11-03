"""Glasses mode (2026-11-03): the Head page takes taps from Bluetooth glasses
through the Media Session API, and a recorded clip is heard by Groq's
Whisper at /api/voice/hear. A fake Groq stands in; no live network."""
import sys, json, os, base64, threading
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
SEEN = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        SEEN.append((self.path, self.headers.get("Content-Type"), self.headers.get("Authorization"), body))
        code, out = (429, {"error": {"message": "rate limited"}}) if b"BUSY" in body else (200, {"text": "  remind me at six  to call mom "})
        b = json.dumps(out).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ.update(DASHBOARD_KEY="dk", GROQ_API_KEY="gk", NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.PROVIDERS["groq"] = (f"http://127.0.0.1:{srv.server_address[1]}/openai/v1/chat/completions",) + tuple(h.PROVIDERS["groq"][1:])


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


def call(body, key="dk"):
    s, ct, out = h.handle("POST", "/api/voice/hear", {}, {"x-dashboard-key": key} if key else {}, json.dumps(body).encode())[:3]
    return s, json.loads(out)


clip = b"\x00\x00\x00\x18ftypM4A " + b"x" * 3000
check("needs sign-in", call({"audio": base64.b64encode(clip).decode()}, key=None)[0] == 401)
s, d = call({"audio": base64.b64encode(clip).decode(), "mime": "audio/mp4"})
check("heard, tidied", s == 200 and d["text"] == "remind me at six to call mom")
path, ctype, auth, body = SEEN[-1]
check("sent to Groq's transcriptions with the key", path == "/openai/v1/audio/transcriptions" and auth == "Bearer gk")
check("as a multipart clip with the Whisper model", ctype.startswith("multipart/form-data; boundary=")
      and b'filename="clip.m4a"' in body and h.HEAR_MODEL.encode() in body and clip in body)
check("bad audio is a 400", call({"audio": "not base64!!"})[0] == 400)
check("no audio is a 400", call({"audio": ""})[0] == 400)
check("too long is refused", call({"audio": base64.b64encode(b"x" * (h.HEAR_MAX_BYTES + 1)).decode()})[0] == 400)
s, d = call({"audio": base64.b64encode(b"BUSY" + b"x" * 3000).decode(), "mime": "audio/webm"})
check("Groq out of free uses says so", s == 429 and "out of free uses" in d["error"])
check("webm named as webm", b'filename="clip.webm"' in SEEN[-1][3])

page = h.head_page({"host": "theta.example", "x-dashboard-key": "dk"})
html_ = page[2].decode() if isinstance(page, tuple) else str(page)
check("Glasses mode switch on the Head page", 'id="head-glasses"' in html_)
check("taps come through the Media Session API", "navigator.mediaSession" in html_ and "setActionHandler" in html_)
check("a tap while Theta talks stops it", 'if (state === "speaking") { hush();' in html_)
check("backup ear posts to /api/voice/hear", "/api/voice/hear" in html_ and "MediaRecorder" in html_)
print("done")
