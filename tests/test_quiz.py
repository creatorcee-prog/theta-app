"""Quiz cards: the agent's clarifying question as an interactable card.

When an agent is unsure what the user means, it can ask with a
```quiz fence (question first, - option lines after) instead of
a paragraph of questions. The user picks one radio option and
Submit sends the choice as a chat message through /api/allchat.
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
            elif op == "GET": r = DB.get(k)
            elif op == "SET": DB[k] = a[0]; r = "OK"
            elif op == "DEL": r = DB.pop(k, None) is not None
            elif op == "LLEN": r = len(DB.get(k, []))
            elif op == "LRANGE":
                lo, hi = int(a[0]), int(a[1])
                r = DB.get(k, [])[lo:hi + 1 if hi >= 0 else None]
            elif op == "EXPIRE": r = 1
            else: r = None
            return self._send(200, {"result": r})
        self._send(404, {})


srv = HTTPServer(("127.0.0.1", 0), Fake)
port = srv.server_address[1]
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
uis = h._UI_JS_SRC
rt = js[js.index("function richText"):]
rt = rt[:rt.index("function typed")]


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


# --- The quiz card itself ---
check("quiz fence dispatches to a card", 'if (info === "quiz")' in rt)
check("quiz options render as radios", 'inp.type = "radio"' in rt)
check("quiz submit sends the choice as a chat message",
      'sendCard(() => "Quiz: " + q' in rt)
check("quiz submit waits for a choice", 'sub.disabled = true' in rt)
check("quiz with no options says so instead of dropping the question",
      '"Nothing to choose here."' in rt)
check("quiz keeps non-option lines instead of dropping them",
      'notes.push(raw.trim())' in rt)
check("quiz card reuses the card shell",
      ".md .doccard,.md .cfgcard,.md .quizcard{background:" in css)

# --- Message footer: Copy / Share / More, then meta below the answer ---
check("agent answers get Copy, Share, and More buttons",
      'copyBtn(() => m.text, true, "mbtn", "Copy message")' in js
      and 'sh.setAttribute("aria-label", "Share message")' in js
      and 'more.setAttribute("aria-label", "More actions")' in js)
check("Share uses the system sheet, or copies when there is none",
      "navigator.share" in js)
check("More offers Download as Markdown",
      'a.download = "message.md"' in js)
check("meta is appended after the actions, not above the answer",
      js.index("body.append(foot)") < js.index("body.append(meta);"))
check("agent footers carry no name (via is a name too)",
      'if (!isAgent) meta.append(name);' in js
      and 'if (!isAgent) meta.append(via);' in js)

# --- The prompt teaches the quiz; radio groups are no longer banned ---
p = h.system_prompt("theta")
check("prompt teaches the quiz for unsure agents",
      "```quiz with a question on" in p and "instead of asking a paragraph of questions" in p)
check("prompt no longer bans radio groups",
      "it cannot show line charts or architecture diagrams" in p)
readme = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "README.md")).read()
check("README catalog covers the quiz", "```quiz ` renders a question" in readme)

# --- Links: external ones open in the default browser ---
check("agent page links open externally in the browser",
      'if (/^https?:/.test(d.page)) { pg.target = "_blank"; pg.rel = "noopener"; }' in uis)
check("chat links already open in a new tab",
      'a.href = url; a.target = "_blank"; a.rel = "noopener";' in rt)

# --- Liquid edge light follows gyro / cursor through variables ---
check("liquid edge light is variable-driven, not fixed",
      "var(--shine-x,0)*2px" in css and "var(--shine-y,0)*2px" in css)
check("edge light reads the gyro and the pointer",
      "deviceorientation" in uis and "edgeSet(e.gamma / 45" in uis
      and "edgeSet(e.clientX / innerWidth * 2 - 1" in uis)
check("edge light stays out of plus mode and reduced motion",
      'document.documentElement.dataset.glassstyle === "liquid"' in uis
      and "if (still || !edgeLiquid()) return;" in uis)

# --- Larger text: body, messages, code, titles ---
check("base text is larger", "font:16px/1.5 " in css)
check("message bodies are larger", ".msg .mbody{font-size:17px}" in css)
check("code text is larger", "overflow-y:auto;font-size:14px;" in css)
check("titles are slightly larger",
      "h1{font-size:30px" in css and "h2{font-size:20px" in css
      and ".md .md-h{font-weight:700;font-size:18px" in css)
