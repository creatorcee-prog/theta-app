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
import urllib.error
BODY = ("The council voted 7-2 on Tuesday to approve the new transit plan after a three-hour hearing. "
        "Mayor Dana Ruiz called it “a once-in-a-generation investment in how people get to work.” "
        "Opponents said the cost estimates were too optimistic and warned of delays. "
        "The plan adds four bus lines and extends light rail to the airport by 2031.") * 2
PAGES = {
  "https://news.test/ld": f"""<html><head><meta property="og:site_name" content="Test Times">
   <script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@graph": [
      {"@type": "WebSite", "name": "Test Times"},
      {"@type": ["NewsArticle"], "headline": "Council approves transit plan",
       "author": [{"@type": "Person", "name": "Jane Doe"}, {"@type": "Person", "name": "Sam Roe"}],
       "publisher": {"name": "Test Times"}, "articleBody": BODY}]})}</script></head><body></body></html>""",
  "https://news.test/meta": """<html><head><meta property="article:author" content="https://news.test/profile/ana-lee,https://news.test/profile/bo-kim">
   <script>var x = "<p>not this</p>";</script></head><body><article>""" + "".join(f"<p>{s}.</p>" for s in BODY.split(". ") if s) + """
   <p>Subscribe to our newsletter for more.</p></article></body></html>""",
  "https://news.test/paywall": "<html><body><p>Subscribe to continue reading.</p></body></html>",
}
class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass
real_urlopen = h.urllib.request.urlopen
FETCHED = []
def fake_urlopen(req, timeout=None):
    url = getattr(req, "full_url", req)
    if url.startswith("https://news.test/"):
        FETCHED.append((url, req.headers.get("User-agent")))
        if url.endswith("/blocked"):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        return Resp(PAGES[url].encode())
    return real_urlopen(req, timeout=timeout)
h.urllib.request.urlopen = fake_urlopen
a = h.read_article("https://news.test/ld")
check("structured data: headline, every author, publisher, body", a["authors"] == ["Jane Doe", "Sam Roe"] and a["publisher"] == "Test Times"
      and a["text"].startswith("The council voted") and not a["blocked"])
check("reads as itself (an honest user agent)", "Theta-dashboard" in FETCHED[-1][1])
a = h.read_article("https://news.test/meta")
check("profile-link bylines become names; paragraphs, no scripts, no newsletter pitch", a["authors"] == ["Ana Lee", "Bo Kim"]
      and "council voted" in a["text"] and "not this" not in a["text"] and "newsletter" not in a["text"])
a = h.read_article("https://news.test/blocked")
check("a site that refuses readers is respected and named", a["blocked"] == "the site doesn't allow automated reading (403)" and not a["text"])
a = h.read_article("https://news.test/paywall")
check("paywall: no text, says so", "paywall" in a["blocked"])
check("credits: all authors, or says there's no byline", h.credit_line({"authors": ["A", "B", "C"]}, "X") == "By A, B and C, X"
      and h.credit_line({"authors": []}, "X") == "X (no byline given)")
src = "Mayor Dana Ruiz called it “a once-in-a-generation investment in how people get to work.”"
t, dropped = h.keep_true_quotes('The mayor called it "a once-in-a-generation investment in how people get to work." '
                                'She also said "this will fix every traffic problem forever." It passed 7-2.', src + " It passed 7-2.")
check("quotes: real ones kept (curly vs straight), invented ones' sentences dropped", dropped == 1 and "once-in-a-generation" in t
      and "fix every traffic problem" not in t and "passed 7-2" in t)
LLM = {"n": 0}
real_llm = h.llm_chat
def fake_llm(tier, messages, max_tokens=800):
    prompt = messages[-1]["content"]
    if "SUMMARY:" in prompt:
        LLM["n"] += 1
        return ('SUMMARY: The council approved the plan 7-2. Mayor Ruiz called it "a once-in-a-generation investment in how people get to work." '
                'Critics said "this is the worst plan in city history." It adds four bus lines.\n'
                "BIAS: Leads with the mayor's view; critics get one line.")
    LLM.setdefault("prompts", []).append(prompt)
    return "My take, plainly partisan: it's a lot of money."
h.llm_chat = fake_llm
b = h.story_brief("Council approves transit plan", "https://news.test/ld", "Test Times")
check("brief: summary with the real quote, invented quote dropped, framing, byline", 'once-in-a-generation' in b["summary"]
      and "worst plan" not in b["summary"] and b["dropped_quotes"] == 1 and b["bias"].startswith("Leads with")
      and b["credit"] == "By Jane Doe and Sam Roe, Test Times" and b["read"])
h.story_brief("Council approves transit plan", "https://news.test/ld", "Test Times")
check("a story is briefed once", LLM["n"] == 1)
b2 = h.story_brief("Blocked story", "https://news.test/blocked", "Hill", fallback="The outlet's short summary of what happened in the vote today.")
check("blocked article: briefed from the feed summary, and says so", "From the outlet's summary" in b2["note"] and not b2["read"])
b3 = h.story_brief("Nothing", "https://news.test/paywall", "CBS")
check("nothing to read: no model call, an honest note", b3["summary"] == "" and "Couldn't read it" in b3["note"] and LLM["n"] == 2)
check("brief text: summary, framing, credit", h.brief_text(b).count("\n") == 2 and "Framing: Leads with" in h.brief_text(b) and h.brief_text(b).endswith("Test Times"))
# the round
story = {"title": "Council approves transit plan", "url": "https://news.test/ld", "source": "Test Times", "image": None, "summary": ""}
h.news_items = lambda now=None: ([], [story])
h.side_coverage = lambda agent, title, limit=3: []
h.store().set_meta("round:news:seen", "[]")
r = h.run_round(force=True, only=["red", "blue", "gray"])
check("round: all three posted", all(r["ran"][a]["ok"] for a in ("red", "blue", "gray")))
posts = {m["from"]: m["text"] for m in h.allchat_view(channel="news") if m["from"] in ("red", "blue", "gray")}
check("Gray's post leads with the brief and the byline", posts["gray"].startswith("Brief: The council approved") and "By Jane Doe and Sam Roe, Test Times" in posts["gray"])
check("Red and Blue argue from it without repeating it", not posts["red"].startswith("Brief") and [("neutral brief of the article" in p) for p in LLM["prompts"] if "top story" in p] == [True] * 3)
wins = h.finish_windows(h.news_windows())
check("the story's sheet shows the brief", wins[0]["text"].startswith("The council approved") and "Test Times" in wins[0]["text"])
cards = h._meta_json("cards", {})
check("each newsie's window carries the brief under their take", "By Jane Doe and Sam Roe" in cards["red"]["text"])
h.urllib.request.urlopen = real_urlopen
print("done")
