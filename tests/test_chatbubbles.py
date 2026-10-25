"""Own-message bubbles (owner request, after PR #60).

- Chat text is a little larger: message bodies render at 16px
  (base text stays 15px).
- The user's own messages sit on the right as bubbles: the avatar
  column is gone for mine messages, the body hugs its content
  (max 76ch / 85%), aligns right, and wears the UI's glass
  surface — solid where blur is unsupported, translucent + blurred
  under @supports, exactly like .glass.
- Agent messages are untouched: avatars, left alignment, and the
  76ch cap all stay as they were.

Verified at the CSS + chat JS source level (same approach as the
Stage 3b extension tests); the browser test adds the visual check.
"""
import sys, json, threading, os, io
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
DB = {}


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
        return self._send(200, {"choices": [{"message": {"content": "Mini bar reply ok."}}]})


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

css = h._UI_CSS
js = h._CHAT_JS


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


check("own messages still carry the mine class in render()",
      '(m.from === "you" ? " mine" : "")' in js)
check("message rows are single-column with no avatar column",
      ".msg{display:grid;grid-template-columns:minmax(0,1fr);padding:8px 16px 6px}" in css
      and "avcol" not in css and "avcol" not in js)
check("mine bodies are right-aligned content-hugging bubbles",
      ".msg.mine .mbody{width:fit-content;max-width:min(76ch,85%);margin-left:auto;background:var(--surface);border-radius:20px;padding:10px 14px;overflow-wrap:anywhere}" in css)
check("mine bubbles use the glass surface under backdrop-filter",
      ".msg.mine .mbody{background:color-mix(in srgb,var(--surface) 72%,transparent);-webkit-backdrop-filter:blur(var(--glass-blur)) saturate(160%);backdrop-filter:blur(var(--glass-blur)) saturate(160%)}" in css)
check("old accent tint is gone",
      ".msg.mine{background:color-mix(in srgb,var(--accent) 7%,transparent)}" not in css)
check("mine meta is hidden (no You/timestamp on own messages)",
      ".msg.mine .meta{display:none}" in css)
check("chat text is larger (16px message bodies)",
      ".msg .mbody{font-size:16px}" in css)
check("76ch cap intact (3b extension regression)",
      ".mbody{max-width:76ch}" in css)
check("other avatars still render (events, trails, working box)",
      "avatar(" in js and "avcol" not in js)
check("working box hides when the agent stops",
      'if (state === "completed" || state === "failed") { wBox.hidden = true;' in js)
print("chatbubbles: all checks passed")
