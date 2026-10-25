"""Presentation Intelligence Policy, second slice (merged main).

The policy's prompt side: system_prompt() carries a compact
presentation section (decision rules + hard limits), and the
README catalogs exactly the formats the chat renders. Stage 3d
merged, so the prompt now names its fences (doc/config/flow/
bars), blockquotes, and code copy buttons; only line charts,
radio groups, and architecture diagrams remain unrendered.
"""
import sys, json, threading, os
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
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="lenz:lk", GEMINI_API_KEY="<redacted>", GROQ_API_KEY="<redacted>",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="tk")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h

js = h._CHAT_JS
readme = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "README.md")).read()


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


# --- The prompt carries the presentation section, for every agent ---
for agent in ("theta", "mistral", "glass"):
    p = h.system_prompt(agent)
    check(f"system_prompt({agent}) picks the best format, not prose by default",
          "Present each answer in the format that helps most" in p)
    check(f"system_prompt({agent}) chooses autonomously but keeps it simple",
          "pick the format yourself when it is clearly better than plain prose" in p
          and "keep it simple when it is not" in p)

p = h.system_prompt("theta")
check("prompt names the decision rules: tables, lists, checklists, code, headings",
      "a table for things compared across columns" in p
      and "numbered lists for several items" in p
      and "- [ ] for to-dos" in p
      and "a fenced code block for code" in p
      and "headings for long answers" in p)
check("prompt forbids invented data",
      "Never invent data to fill a table or list" in p)
check("prompt forbids describing controls the chat cannot show",
      "it cannot show line charts" in p
      and "radio groups, or architecture diagrams" in p
      and "buttons in chat exist only when the server issues them" in p)
check("prompt reaches desk agents through desk_system",
      "Present each answer in the format that helps most" in h.desk_system("mistral"))

# --- The prompt names the merged fences, nothing unrendered ---
check("prompt names the merged fences",
      "```config" in p and "```doc" in p
      and "```flow" in p and "```bars" in p)
check("prompt names blockquotes and code copy",
      "blockquotes (> )" in p and "code blocks with a Copy button" in p)

# --- Every format the prompt names is actually rendered ---
check("renderer renders tables, checklists, headings, code fences",
      "md-table" in js and "/api/chat/check" in js
      and "md-h" in js and '/^\\s*```/.test(line)' in js)

# --- The README catalogs exactly the approved formats ---
check("README catalogs the approved presentation formats",
      "## How agents present answers" in readme
      and "never invent" in readme
      and "Not yet approved" in readme
      and "```config" in readme
      and "line charts" in readme)

print("presentation: all checks passed")
