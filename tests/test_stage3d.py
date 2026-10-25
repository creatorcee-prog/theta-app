"""Stage 3d: rich-message renderer in Theta's own design language.

- Blockquotes, code blocks with a real Copy button, polished tables
  (alignment honored, scope="col", rounded container, restrained
  dividers), editable document cards, configuration cards that
  submit through /api/allchat, flow diagrams, and bar charts.
- Everything reuses Theta tokens (cards --r, controls --r-sm,
  .glass values, .btn/.field, state classes). No new backend
  endpoint, no model-routing change, no ChatGPT-clone styling.
- Model output stays inert: richText builds DOM nodes, never
  innerHTML for message text; malformed blocks degrade to text.

Verified at the CSS + chat JS source level (same approach as the
Stage 3b/3c tests); the browser test renders a seeded rich message
live and screenshots it.
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
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="lenz:lk", GEMINI_API_KEY="gk", GROQ_API_KEY="qk",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="tok")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h

css = h._UI_CSS
js = h._CHAT_JS
rt = js[js.index("function richText"):]
rt = rt[:rt.index("function typed")]


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


# --- Tables: rounded container, restrained dividers, alignment, scope ---
check("table container has the rounded card treatment",
      ".md .md-scroll{overflow-x:auto;margin:6px 0;white-space:normal;border:1px solid var(--border);border-radius:var(--r-sm);background:var(--surface)}" in css)
check("table dividers are horizontal only with comfortable cells",
      ".md .md-table th,.md .md-table td{border-bottom:1px solid var(--border);padding:9px 12px;text-align:left;vertical-align:top;overflow-wrap:break-word;word-break:normal;white-space:normal;min-width:5.5em}" in css)
check("old full-grid table rule is gone",
      ".md .md-table th,.md .md-table td{border:1px solid var(--border);padding:7px 10px" not in css)
check("table alignment comes from the separator row",
      'cells(lines[i + 1]).map(c => /^:-+:$/.test(c) ? "center" : /^-+:$/.test(c) ? "right" : "left")' in rt)
check("table headers carry scope=col",
      'th.setAttribute("scope", "col")' in rt)
check("table cells keep the 5.5em floor (no shredding)",
      "min-width:5.5em" in css)

# --- Code + quotes ---
check("code blocks keep the 340px cap (3b regression)",
      "max-height:340px;overflow-y:auto" in css and ".md pre{" in css)
check("code blocks get a glass box, Code label, and icon copy button",
      '.md .codeblock{border:1px solid var(--border);border-radius:16px;background:var(--surface);color:var(--text);overflow:hidden;margin:6px 0}' in css
      and '.md .codeblock .chead{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-bottom:1px solid var(--border)}' in css
      and 'head.append(el("span", "clabel", "Code"), copyBtn(() => body.join("\\n"), true))' in rt
      and "navigator.clipboard.writeText" in rt)
check("card buttons and code boxes are glass, not accent or dark",
      '.msg-acts .btn{background:var(--surface);color:var(--text);border:1px solid var(--border)}' in css
      and '.md .codeblock{background:color-mix(in srgb,var(--surface) 72%,transparent);-webkit-backdrop-filter:blur(var(--glass-blur)) saturate(160%);backdrop-filter:blur(var(--glass-blur)) saturate(160%)}' in css
      and ':root[data-glassstyle="liquid"] .msg-acts .btn{background:linear-gradient(135deg,color-mix(in srgb,white 16%,transparent),color-mix(in srgb,white 2%,transparent) 45%,color-mix(in srgb,var(--accent) 10%,transparent)),color-mix(in srgb,var(--surface) 58%,transparent);-webkit-backdrop-filter:blur(32px) saturate(190%);backdrop-filter:blur(32px) saturate(190%);box-shadow:inset 0 1px 0 rgba(255,255,255,.45),inset 0 -1px 0 rgba(255,255,255,.12);border:0}' in css
      and ':root[data-glassstyle="liquid"] .md.codeblock pre{background:transparent;color:var(--text);-webkit-backdrop-filter:none;backdrop-filter:none;box-shadow:none;-webkit-mask-box-image:none;mask-border:none}' in css)
check("blockquotes render with the accent bar",
      ".md .md-quote{border-left:3px solid var(--accent);padding:2px 0 2px 12px;color:var(--muted);margin:6px 0}" in css
      and 'el("blockquote", "md-quote")' in rt)
check("headings keep the approved flat-bold treatment",
      ".md .md-h{font-weight:700;margin-top:4px}" in css)

# --- Cards: Theta tokens, real actions, supported API only ---
check("doc/config cards reuse card tokens (radius, padding, shadow)",
      ".md .doccard,.md .cfgcard{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:var(--pad);box-shadow:var(--shadow);margin:8px 0}" in css)
check("fence dispatch covers doc, config, flow, bars",
      'if (info === "doc")' in rt and 'if (info === "config")' in rt
      and 'if (info === "flow")' in rt and 'if (info === "bars")' in rt)
check("doc card has copy + edit with send-as-message save",
      'el("div", "doccard")' in rt and '"Send edited text"' in rt
      and "sendCard(() => ta.value, card)" in rt)
check("config card parses strict select/check lines",
      'el("div", "cfgcard")' in rt and "/^select\\s+([^:]+):\\s*(.+)$/i" in rt
      and "/^check\\s+([^:]+):\\s*(on|off)\\s*$/i" in rt)
check("card submission uses /api/allchat, never a /api/chat/press fetch",
      '"/api/allchat"' in rt and 'fetch("/api/chat/press"' not in rt)
check("card buttons get 44px touch height on coarse pointers",
      "@media (pointer:coarse){.md .doccard .btn,.md .cfgcard .btn,.md .codeblock .cbtn{min-height:44px;min-width:44px}}" in css)

# --- Diagrams + charts (DOM only, no new library) ---
check("flow builder renders boxes + arrows",
      'el("div", "fnode", n)' in rt and '.md .fnode{background:var(--surface2);border:1px solid var(--border);border-radius:var(--r-sm);padding:10px 14px;font-weight:650;text-align:center}' in css)
check("bars builder renders max-normalized labeled bars",
      'el("div", "bar-fill")' in rt and ".md .bar-track{flex:1;background:var(--surface2);border-radius:999px;height:14px;overflow:hidden}" in css)

# --- Safety + preserved behavior ---
check("richText never uses innerHTML for message text",
      "innerHTML" not in rt)
check("composer attachment submission intact",
      "savedAtts.map" in js)
check("checklist persistence + message action buttons intact",
      '"/api/chat/check"' in js and '"msg-acts"' in js)
check("glass foundation untouched",
      ".glass{background:var(--surface)}" in css)

check("message selection does not repaint the thread background",
      "#msgs ::selection{background:transparent}" in css)
check("own bubbles keep shape and fill but carry no border",
      ".msg.mine .mbody{width:fit-content;max-width:min(76ch,85%);margin-left:auto;background:var(--surface);border-radius:20px;padding:10px 14px;overflow-wrap:anywhere}" in css
      and "border:1px solid var(--border);border-radius:20px;padding:10px 14px" not in css)
check("own messages hide their You/timestamp meta, agent meta intact",
      ".msg.mine .meta{display:none}" in css
      and ".meta{display:flex;align-items:baseline;gap:8px;min-width:0}" in css)
print("stage3d: all checks passed")
