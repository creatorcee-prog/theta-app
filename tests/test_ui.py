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
h.CHAT_MODE = "crew"  # these tests cover each agent answering (CHAT_MODE=crew); test_desk.py covers the front desk
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}

def call(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
from wsgiref.util import setup_testing_defaults
import urllib.error, xml.etree.ElementTree as ET
def call(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s, h=dict(hd))))
    return int(got["s"][:3]), (json.loads(out) if out[:1] in (b"{", b"[") else out), got["h"]
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
K = {"x-dashboard-key": "dk"}
print("mode:", mode)
LLMCALLS = []
LLM = {"reply": None}
real_llm = h.llm_chat
def fake_llm(tier, messages, max_tokens=800):
    LLMCALLS.append({"tier": tier, "messages": messages})
    if LLM["reply"] is not None:
        return LLM["reply"]
    return real_llm(tier, messages, max_tokens)
h.llm_chat = fake_llm

# --- brand, avatars, icon, manifest
s, svg, hd = call("GET", "/avatar/theta.svg")
check("avatar served as SVG, cacheable, no key needed", s == 200 and hd["Content-Type"] == "image/svg+xml" and svg.startswith(b"<svg") and "max-age" in hd["Cache-Control"])
check("unknown avatar falls back to the hub's", call("GET", "/avatar/nobody.svg")[1] == call("GET", "/avatar/hub.svg")[1])
check("every agent has its own avatar", len({call("GET", f"/avatar/{a}.svg")[1] for a in h.AGENTS}) == len(h.AGENTS))
s, png, _ = call("GET", "/icon-512.png")
check("app icon is a 512px PNG", png[:8] == b"\x89PNG\r\n\x1a\n" and int.from_bytes(png[16:20], "big") == 512)
s, man, _ = call("GET", "/manifest.webmanifest")
check("manifest says Theta", man["name"] == "Theta" and man["short_name"] == "Theta" and man["display"] == "standalone")

# --- themes, modes, layouts
s, css, hd = call("GET", "/ui.css")
css = css.decode()
check("ui.css has all 12 themes, each with light, dark and follow-device rules",
      len(h.THEMES) == 12 and all(f':root[data-theme="{t}"]{{' in css and f':root[data-theme="{t}"][data-mode="dark"]{{' in css
                                  and f':root[data-theme="{t}"]:not([data-mode="light"])' in css for t in h.THEMES))
check("assets cached for good (versioned URLs)", "immutable" in hd["Cache-Control"] and "immutable" in call("GET", "/ui.js")[2]["Cache-Control"])
s, js, _ = call("GET", "/ui.js")
check("ui.js knows each theme's flags", b'"aurora": {"glass": true' in js and b'"terminal": {"glass": false, "mono": true' in js and b"__THEMES__" not in js)
check("prefs: defaults", h.ui_prefs({}) == ("theta", "auto", "grid"))
check("prefs: from cookie", h.ui_prefs({"cookie": "theta_ui=nebula.dark.magazine"}) == ("nebula", "dark", "magazine"))
check("prefs: junk falls back piece by piece", h.ui_prefs({"cookie": "theta_ui=nope.dark.zzz"}) == ("theta", "dark", "grid")
      and h.ui_prefs({"cookie": "theta_ui=<script>"}) == ("theta", "auto", "grid"))
s, page, _ = call("GET", "/", headers={**K, "cookie": "theta_ui=aurora.light.compact"})
page = page.decode()
check("page renders the saved theme, mode, layout and glass flag", '<html lang="en" data-theme="aurora" data-mode="light" data-layout="compact" data-glass>' in page)
check("forced mode: one theme-color meta", page.count('name="theme-color"') == 1)
s, page, _ = call("GET", "/", headers=K)
check("auto mode: light and dark theme-color metas", page.decode().count('name="theme-color"') == 2)
for t in h.THEMES:
    for pth in ("/", "/chat", "/settings", "/money", "/calendar", "/agent/glass"):
        s, b, _ = call("GET", pth, headers={**K, "cookie": f"theta_ui={t}.dark.magazine"})
        if s != 200 or f'data-theme="{t}"'.encode() not in b:
            check(f"{pth} renders in {t}", False)
check("every page renders in every theme", True)
check("pages need the key", all(call("GET", p)[0] == 401 for p in ("/", "/chat", "/settings", "/money", "/calendar", "/agent/theta")))
check("unknown agent page is a 404", call("GET", "/agent/nobody", headers=K)[0] == 404)
s, page, _ = call("GET", "/settings", headers=K)
page = page.decode()
check("settings offers every theme, mode and layout",
      all(f'data-pref="theme" data-val="{t}"' in page for t in h.THEMES) and all(f'data-val="{m}"' in page for m in h.MODES)
      and all(f'data-pref="layout" data-val="{l}"' in page for l in h.LAYOUTS))

# --- feed pictures
rss = b"""<rss xmlns:media="http://search.yahoo.com/mrss/" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>Outlet</title>
<item><title>A</title><link>https://x/a</link><media:content url="https://img/small.jpg" width="200" medium="image"/><media:content url="https://img/big.jpg" width="1200" medium="image"/></item>
<item><title>B</title><link>https://x/b</link><media:thumbnail url="https://img/thumb.jpg"/></item>
<item><title>C</title><link>https://x/c</link><enclosure url="https://img/enc.jpg" type="image/jpeg"/></item>
<item><title>D</title><link>https://x/d</link><enclosure url="https://x/a.mp3" type="audio/mpeg"/><description>&lt;p&gt;&lt;img src="https://img/desc.jpg?a=1&amp;amp;b=2"&gt;&lt;/p&gt;</description></item>
<item><title>E</title><link>https://x/e</link><media:content url="https://x/v.mp4" type="video/mp4"/></item>
<item><title>F</title><link>https://x/f</link><media:thumbnail url="https://ichef.bbci.co.uk/ace/standard/240/a.jpg"/></item>
</channel></rss>"""
items = {i["title"]: i["image"] for i in h._parse_rss(rss)}
check("RSS pictures: widest media:content, thumbnail, image enclosure, <img> in text, never video",
      items == {"A": "https://img/big.jpg", "B": "https://img/thumb.jpg", "C": "https://img/enc.jpg",
                "D": "https://img/desc.jpg?a=1&b=2", "E": None, "F": "https://ichef.bbci.co.uk/ace/standard/976/a.jpg"})
apple = json.dumps({"feed": {"results": [{"name": "Song", "artistName": "Lady Gaga", "url": "https://music/1",
                                          "artworkUrl100": "https://art/100x100bb.jpg"}]}}).encode()
a = h._parse_apple_json(apple)[0]
check("Apple Music: album art at 600px, marked as a song", a["image"] == "https://art/600x600bb.jpg" and a["kind"] == "song" and a["artist"] == "Lady Gaga")

# --- short titles
check("trim: outlet suffix and BREAKING prefix go", h.trim_title("BREAKING: Storm hits coast - Fox News", "Fox News") == "Storm hits coast")
check("trim: word boundary with an ellipsis", h.trim_title("One two three four five six seven eight nine ten eleven twelve", limit=20) == "One two three four…")
check("trim: short titles untouched", h.trim_title("Rain today") == "Rain today")
LLM["reply"] = "1. Gaga drops new single | Lady Gaga\n2) Senate passes budget bill | none\nnoise line\n3. " + "x" * 80 + " | X\n9. out of range | Y"
n = h.condense_titles(["Lady Gaga surprises fans with a brand-new single at midnight", "Senate passes the budget after a long night", "Third", "Lady Gaga surprises fans with a brand-new single at midnight"])
cache = h._meta_json("cards:short", {})
check("condense: one call, parses '1.' and '2)', skips too-long and out-of-range lines", n == 2 and len(LLMCALLS) == 1 and LLMCALLS[-1]["tier"] == "miner")
check("condense: subject kept, 'none' blank", cache[h._title_key("Lady Gaga surprises fans with a brand-new single at midnight")] == ["Gaga drops new single", "Lady Gaga"]
      and cache[h._title_key("Senate passes the budget after a long night")] == ["Senate passes budget bill", ""])
n0 = len(LLMCALLS)
check("condense: already-condensed titles cost no call", h.condense_titles(["Lady Gaga surprises fans with a brand-new single at midnight", "Senate passes the budget after a long night"]) == 0 and len(LLMCALLS) == n0)
LLM["reply"] = None

# --- Wikipedia pictures
WIKI = {"mode": "found", "asked": []}
real_urlopen = h.urllib.request.urlopen
class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass
def fake_urlopen(req, timeout=None):
    url = req.full_url if hasattr(req, "full_url") else req
    if "wikipedia.org" not in url:
        return real_urlopen(req, timeout=timeout)
    WIKI["asked"].append((url, req.headers.get("User-agent")))
    if WIKI["mode"] == "down":
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
    if WIKI["mode"] == "found":
        return Resp(json.dumps({"query": {"pages": [{"title": "Lady Gaga", "thumbnail": {"source": "https://upload.wikimedia.org/gaga.jpg"}}]}}).encode())
    return Resp(json.dumps({"query": {"pages": [{"title": "Nobody"}]}}).encode())
h.urllib.request.urlopen = fake_urlopen
check("wiki: found", h.wiki_image("Lady Gaga") == (True, "https://upload.wikimedia.org/gaga.jpg"))
check("wiki: identifies itself (Wikimedia asks for a real User-Agent)", "Theta-dashboard" in WIKI["asked"][-1][1])
WIKI["mode"] = "missing"; WIKI["asked"].clear()
check("wiki: no picture -> answered, none (tries title, then search)", h.wiki_image("Nobody") == (True, None) and len(WIKI["asked"]) == 2 and "gsrsearch" in WIKI["asked"][1][0])
WIKI["mode"] = "down"
check("wiki: rate limited -> not answered", h.wiki_image("Anyone") == (False, None))
WIKI["mode"] = "found"
check("find_images: found one", h.find_images(["Lady Gaga"]) == 1)
WIKI["mode"] = "down"
check("find_images: a failed lookup isn't remembered", h.find_images(["Rate Limited Person"]) == 0 and "rate limited person" not in h._meta_json("cards:img", {}))
WIKI["asked"].clear()
check("find_images: a recent answer isn't asked again", h.find_images(["Lady Gaga"]) == 0 and not WIKI["asked"])
w = h.finish_windows([h._win("lenz", "Lady Gaga surprises fans with a brand-new single at midnight")])[0]
check("finish_windows: short title + looked-up picture", w["title"] == "Gaga drops new single" and w["image"] == "https://upload.wikimedia.org/gaga.jpg")
w = h.finish_windows([h._win("red", "Some other long headline here - Fox News", source="Fox News", image="https://own.jpg")])[0]
check("finish_windows: own picture kept, heuristic title when not condensed", w["title"] == "Some other long headline here" and w["image"] == "https://own.jpg")
h.urllib.request.urlopen = real_urlopen

# --- cards and windows
h.save_card("red", "Big vote today in the Senate", "Our take: it's a win.\nhttps://x/1", "https://img/vote.jpg", "https://x/1", "Fox News")
wins = {w["agent"]: w for w in h.agent_windows()}
check("a saved card becomes the agent's window", wins["red"]["raw"] == "Big vote today in the Senate" and wins["red"]["image"] == "https://img/vote.jpg"
      and wins["red"]["sub"] == "Our take: it's a win." and wins["red"]["external"])
check("every agent gets a window, in roster order", [w["agent"] for w in h.agent_windows()] == list(h.AGENTS))
h.add_expense(95, "Groceries", "x"); h.GLASS_BUDGETS.update({"Groceries": 100.0})
g = {w["agent"]: w for w in h.agent_windows()}["glass"]
check("Glass's window flags a category near its budget, with a bars picture", g["title"] == "Groceries at 95%" and g["image"].startswith("data:image/svg+xml") and g["href"] == "/money")
h.save_card("lenz", "Old pick", "x", "https://img/old.jpg")
cards = h._meta_json("cards", {}); cards["lenz"]["at"] = time.time() - 9999; h.store().set_meta("cards", json.dumps(cards))
s, page, _ = call("GET", "/", headers={**K, "cookie": "theta_ui=theta.auto.magazine"})
page = page.decode()
crew = page[page.index('aria-label="Agent windows"'):]
check("magazine leads with the newest photo window", crew.index("https://img/vote.jpg") < crew.index("/agent/theta"))
s, page, _ = call("GET", "/", headers={**K, "cookie": "theta_ui=theta.auto.grid"})
crew = page.decode()[page.decode().index('aria-label="Agent windows"'):]
check("grid keeps roster order", crew.index('href="/agent/theta"') < crew.index("https://img/vote.jpg"))
h.save_card("blue", '<script>alert(1)</script>"', "<img src=x onerror=alert(1)>", "javascript:alert(1)\" onload=\"x")
s, page, _ = call("GET", "/", headers=K)
check("window text and picture URLs are escaped", b"<script>alert(1)" not in page and b"<img src=x onerror" not in page and b'" onload="x' not in page)
check("bars picture is URL-encoded SVG", "%3Csvg" in g["image"])

# --- chat channels
h.store().add_chat("glass", "Budget note from a round")
h.store().add_chat("hub", "Round: done", kind="event")
s, d, _ = call("GET", "/api/allchat", "channel=money", headers=K)
check("#money shows Glass's round post (home channel)", any(m["text"] == "Budget note from a round" and m["ch"] == "money" for m in d["messages"]))
s, d, _ = call("GET", "/api/allchat", "channel=command", headers=K)
check("hub events live in #command", any(m["text"] == "Round: done" for m in d["messages"]) and all(m["ch"] == "command" for m in d["messages"]))
s, d, _ = call("GET", "/api/allchat", "channel=bogus", headers=K)
check("unknown channel -> everything", any(m["ch"] == "money" for m in d["messages"]) and any(m["ch"] == "command" for m in d["messages"]))
n = len(LLMCALLS)
s, d, _ = call("POST", "/api/allchat", headers=K, body={"text": "What's coming up?", "channel": "family"})
mine = [m for m in d["messages"] if m["from"] in ("you", "remi")][-2:]
check("#family: Remi answers without Mistral routing, both tagged #family", [m["from"] for m in mine] == ["you", "remi"] and all(m["ch"] == "family" for m in mine)
      and d["routed"] == [] and len(LLMCALLS) == n + 1)
s, d, _ = call("GET", "/api/allchat", "channel=money", headers=K)
check("#family talk stays out of #money", not any(m["text"] == "What's coming up?" for m in d["messages"]))
n = len(LLMCALLS)
s, d, _ = call("POST", "/api/allchat", headers=K, body={"text": "Thoughts?", "channel": "news"})
check("#news: all three answer", sorted(m["from"] for m in d["messages"][-3:]) == ["blue", "gray", "red"] and len(LLMCALLS) == n + 3)
LLM["reply"] = "charter"
s, d, _ = call("POST", "/api/allchat", headers=K, body={"text": "how are we doing", "channel": "money"})
pick_prompt = LLMCALLS[-2]["messages"][-1]["content"] if len(LLMCALLS) >= 2 else ""
check("#money: Mistral picks among Glass and Charter only", "- glass:" in pick_prompt and "- charter:" in pick_prompt and "- remi:" not in pick_prompt
      and d["routed"] == ["Charter"])
LLM["reply"] = "nonsense words"
s, d, _ = call("POST", "/api/allchat", headers=K, body={"text": "hi", "channel": "money"})
check("#money: a useless pick falls back to the first member", d["routed"] == ["Glass"])
LLM["reply"] = None
s, d, _ = call("POST", "/api/allchat", headers=K, body={"text": "@lenz anything good?", "channel": "money"})
check("an @mention still wins in any channel", d["messages"][-1]["from"] == "lenz" and d["messages"][-1]["ch"] == "money")
s, page, _ = call("GET", "/chat", "ch=money&to=glass", headers=K)
page = page.decode()
check("chat page: channel list, members, composer for the channel", "Message #money" in page and page.count('href="/chat?ch=') >= 2 * len(h.CHANNELS) and 'id="members"' in page)
h.store().add_chat("lenz", "</script><script>alert(1)</script>", channel="money")
s, page, _ = call("GET", "/chat", "ch=money", headers=K)
check("chat's embedded messages can't close the script tag", b"</script><script>alert(1)" not in page)
check("no per-agent chat picker any more", b'id="chat-agent"' not in page)

# --- a round short on time skips the window refresh (Vercel's 60 s limit)
n = len(LLMCALLS)
h.save_card("gray", "A brand new headline nobody has condensed yet", "x")
check("refresh: no time left -> no model call, no lookups", h.refresh_windows(deadline=time.time() + 5) == "" and len(LLMCALLS) == n)
LLM["reply"] = "1. New headline | none"
note = h.refresh_windows(deadline=time.time() + 60)
check("refresh: with time -> condenses: " + note, "new window title" in note and len(LLMCALLS) == n + 1)
LLM["reply"] = None

# --- sheets, coverage, logos, unread
check("feed summaries: HTML stripped, cut at a word", h._plain("<p>Hello &amp; <b>welcome</b></p>") == "Hello & welcome"
      and h._plain("word " * 200, limit=20).endswith("…") and len(h._plain("word " * 200, limit=20)) <= 21)
items = h._parse_rss(b"<rss><channel><title>O</title><item><title>T</title><link>https://www.site.com/a</link><description>&lt;p&gt;Short summary.&lt;/p&gt;</description></item></channel></rss>")
check("RSS items keep their summary", items[0]["summary"] == "Short summary.")
cov = {"red": ["Fox News", "Daily Wire"], "gray": ["The Hill"], "blue": []}
html_cov = h.coverage_html(cov)
check("coverage bar: counts, colors, names in the tooltip", "Red 2 · Gray 1 · Blue 0" in html_cov and h.AGENT_LOOKS["red"][0] in html_cov
      and "Daily Wire" in html_cov and h.AGENT_LOOKS["blue"][0] not in html_cov)
check("no coverage, no bar", h.coverage_html({"red": [], "gray": [], "blue": []}) == "" and h.coverage_html(None) == "")
w = h._win("", "Story title", image=None, href="https://www.site.com/a", external=True, source="Site", text="Sum")
check("external windows know their site, for the logo", w["site"] == "www.site.com" and w["links"] == [["Site", "https://www.site.com/a"]])
hw = h.win_html(w)
check("window shows the site's logo", 'class="logo" src="https://icons.duckduckgo.com/ip3/www.site.com.ico"' in hw)
import html as _html, re as _re
sheet = json.loads(_html.unescape(_re.search(r'data-sheet="([^"]*)"', hw).group(1)))
check("window carries its sheet: full title, text, links", sheet["title"] == "Story title" and sheet["text"] == "Sum" and sheet["links"] == [["Site", "https://www.site.com/a"]])
w2 = h.win_html(h._win("glass", "", "s", text='</a><script>x</script>"', title="t"))
check("sheet data is escaped inside the attribute", "<script>x" not in w2 and '"</a>' not in w2)
h.store().add_chat("remi", "a family note")
h.store().add_chat("you", "mine")
latest = h.latest_by_channel()
last_remi = [m for m in h.store().list_chat(500) if m["from"] == "remi"][-1]["id"]
check("latest per channel: agents' posts only, not yours or events", latest["family"] == last_remi and all(v != h.store().list_chat(1)[-1]["id"] for v in latest.values()))
s_, page, _ = call("GET", "/settings", headers=K)
check("every page carries the newest-per-channel map", b"window.THETA_LATEST = {" in page and b'data-haptics' not in page)
s_, d, _ = call("GET", "/api/allchat", "channel=family", headers=K)
check("chat API returns it too", d["latest"]["family"] == last_remi)

# --- bot-pushed items still show
call("POST", "/api/report", headers={"x-bot-key": "lk"}, body={"bot_id": "lenz", "event_type": "entertainment", "payload": {"title": "Lenz pushed pick", "url": "https://x/p"}})
s, page, _ = call("GET", "/", headers=K)
check("items bots push show on Home", b"Lenz pushed pick" in page)
print("done")
