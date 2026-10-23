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
LOG = "﻿" + "\r\n".join("""Key
G - Game
AN - Anime
Waiting for New Installs
Video
* Dandadan - Waiting on S3
* Tsukimichi - Moonlit Fantasy - Waiting for S3
Current
Games
* Elden Ring - (G)
Video 
1. Family
   1. Attack on Titan (w/Ba an Nat S4 Ep22)
2. Main
   1. Witch Hat Atelier - Ep 3 - (AN)
3. Other
   1. The Time I Got Reincarnated into a Slime - (AN)
      1. Waiting on S3 Dub
Text
1. Gokurakugai - Chapter 2 - (C)
In Queue
Games
* Black Myth Wukong - (G) $60
Video
S-TIER: Masterpieces (9.0+ IMDB / 8.5+ MAL)
Highest quality shows - worth prioritizing
Quick Watches (Under 15 hours)
* Fight Club (Movie, 2.3hrs) - IMDB 8.8
* Odd Taxi (13 eps, ~5hrs) - MAL 8.7
________________
A-TIER: Excellent
TV Series
* Peaky Blinders (36 eps, ~36hrs) - IMDB 8.8
Rankings
(For Entertainment Pieces Only)
Video
1. Re:Zero Stopped at S3 Ep 4 - (AN)
Overall Rankings
        (Buy something to represent the Top 10 to put on shelves)
1. Attack On Titan - AN 3x
2. Breaking Bad - S
3. Baldur’s Gate 3 - G 8x
Most beloved
Attack on Titan 
Overlord""".split("\n"))
lib = {}
for e in h.parse_media_log(LOG):
    lib.setdefault(e["title"], e)
check("key section and descriptions skipped", "G" not in lib and not any("worth prioritizing" in t for t in lib))
check("waiting with its note", lib["Dandadan"]["status"] == "waiting" and lib["Dandadan"]["note"] == "Waiting on S3"
      and "Tsukimichi - Moonlit Fantasy" in lib)
check("current: groups, progress, who you watch with", lib["Attack on Titan"]["status"] == "current" and lib["Attack on Titan"]["group"] == "Family"
      and lib["Attack on Titan"]["progress"] == "S4 Ep22" and lib["Attack on Titan"]["with"] == "Ba an Nat")
check("nested detail becomes a note", "Waiting on S3 Dub" in lib["The Time I Got Reincarnated into a Slime"]["note"])
check("reading progress and kind", lib["Gokurakugai"]["kind"] == "comic" and lib["Gokurakugai"]["progress"] == "Chapter 2")
check("queue tiers, kinds from the heading, hours, scores, price", lib["Fight Club"]["tier"] == "S" and lib["Fight Club"]["kind"] == "movie"
      and lib["Odd Taxi"]["kind"] == "anime" and lib["Peaky Blinders"]["kind"] == "show" and lib["Peaky Blinders"]["tier"] == "A"
      and lib["Black Myth Wukong"]["price"] == "$60" and lib["Fight Club"]["scores"] == {"IMDB": 8.8})
check("stopped -> paused", lib["Re:Zero"]["status"] == "paused" and "Stopped at S3 Ep 4" in lib["Re:Zero"]["note"])
check("overall rankings and rewatches", lib["Attack On Titan"]["rank"] == 1 and lib["Attack On Titan"]["times"] == 3 and lib["Baldur's Gate 3"]["times"] == 8)
check("most beloved", lib["Overlord"]["beloved"])
s, d = call("POST", "/api/lenz/import", headers=K, body={"text": LOG})
check("import merges duplicates across sections", s == 200 and d["total"] == len({h._norm_title(t) for t in lib}))
aot = next(x for x in h.library() if h._norm_title(x["title"]) == "attackontitan")
check("Attack on Titan: current (liveliest), ranked 1, 3x, beloved, anime", aot["status"] == "current" and aot["rank"] == 1
      and aot["times"] == 3 and aot["beloved"] and aot["kind"] == "anime")
# actions
iid = lambda t: next(x["id"] for x in h.library() if x["title"] == t)
s, d = call("POST", f"/api/lenz/items/{iid('Witch Hat Atelier')}", headers=K, body={"action": "next"})
check("+1 episode", d["item"]["progress"] == "Ep 4")
s, d = call("POST", f"/api/lenz/items/{iid('Gokurakugai')}", headers=K, body={"action": "next"})
check("+1 chapter", d["item"]["progress"] == "Chapter 3")
s, d = call("POST", f"/api/lenz/items/{iid('Fight Club')}", headers=K, body={"action": "watched", "value": 9})
check("watched with a rating -> finished, Lenz posts in #watch-and-listen", d["item"]["status"] == "done" and d["item"]["rating"] == 9
      and d["item"]["done_at"] and "Fight Club: 9/10" in d["line"] and h.allchat_view(channel="screen")[-1]["text"] == d["line"])
s, d = call("POST", f"/api/lenz/items/{iid('Odd Taxi')}", headers=K, body={"action": "watched", "value": None})
check("watched without a rating -> Lenz asks for one", d["item"]["rating"] is None and "out of 10" in d["line"])
s, d = call("POST", f"/api/lenz/items/{iid('Odd Taxi')}", headers=K, body={"action": "rate", "value": 8})
check("rate later", d["item"]["rating"] == 8)
check("bad rating refused", call("POST", f"/api/lenz/items/{iid('Odd Taxi')}", headers=K, body={"action": "rate", "value": 11})[0] == 400)
s, d = call("POST", f"/api/lenz/items/{iid('Peaky Blinders')}", headers=K, body={"action": "start"})
check("start", d["item"]["status"] == "current")
s, d = call("POST", "/api/lenz/items", headers=K, body={"title": "Pluto", "kind": "anime", "status": "queue"})
check("add", s == 200 and d["item"]["title"] == "Pluto" and d["item"]["kind"] == "anime")
s, d = call("POST", f"/api/lenz/items/{d['item']['id']}", headers=K, body={"action": "delete"})
check("delete", s == 200 and not any(x["title"] == "Pluto" for x in h.library()))
check("unknown item/action", call("POST", "/api/lenz/items/9999", headers=K, body={"action": "start"})[0] == 404
      and call("POST", "/api/lenz/items/1", headers=K, body={"action": "zap"})[0] == 400)
check("lenz API needs the key", call("POST", "/api/lenz/import", body={"text": LOG})[0] == 401 and call("GET", "/api/lenz")[0] == 401)
call("POST", "/api/lenz/import", headers=K, body={"text": LOG})
check("re-import keeps your ratings and finishes", next(x for x in h.library() if x["title"] == "Fight Club")["rating"] == 9
      and next(x for x in h.library() if x["title"] == "Fight Club")["status"] == "done")
check("empty import explains", call("POST", "/api/lenz/import", headers=K, body={"text": "hello"})[0] == 400)
# chat
n = len(CALLS)
s, d = call("POST", "/api/allchat", headers=K, body={"text": "@lenz I finished Witch Hat Atelier, 10/10", "channel": "screen"})
check("'I finished X, 10/10' logs it with no model call", "Witch Hat Atelier: 10/10" in d["messages"][-1]["text"] and len(CALLS) == n
      and next(x for x in h.library() if x["title"] == "Witch Hat Atelier")["rating"] == 10)
s, d = call("POST", "/api/allchat", headers=K, body={"text": "@lenz just watched Perfect Blue", "channel": "screen"})
check("unknown title is added as finished, asks for a rating", "out of 10" in d["messages"][-1]["text"] and any(x["title"] == "Perfect Blue" and x["status"] == "done" for x in h.library()))
check("Lenz's prompt knows your library", "Attack on Titan" in h.system_prompt("lenz") and "Witch Hat Atelier 10/10" in h.system_prompt("lenz"))
# taste and the weekly report
prof = h.taste_profile()
check("taste: per-kind counts and averages", prof["kinds"]["anime"]["avg"] == 9.0 and prof["kinds"]["movie"]["avg"] == 9.0)
from datetime import date
rep1 = h.lenz_week_report(date(2026, 10, 25))
check("weekly report lists this week's finishes with ratings", "Fight Club (9/10)" in rep1 and "Perfect Blue (unrated)" in rep1 and "still unrated" in rep1)
# followed news
real_outlets = h.outlet_items
h.outlet_items = lambda urls: [{"title": "Dandadan Season 3 announced for 2027", "url": "https://n/1", "source": "MAL"},
                               {"title": "Elden Ring Nightreign gets a patch", "url": "https://n/2", "source": "IGN"},
                               {"title": "Unrelated show news", "url": "https://n/3", "source": "IGN"},
                               {"title": "Big news for Overlord fans", "url": "https://n/4", "source": "MAL"}]
fn = {n["url"]: n for n in h.followed_news()}
check("news about what you follow, not the rest", set(fn) == {"https://n/1", "https://n/2", "https://n/4"} and fn["https://n/1"]["waiting"]
      and fn["https://n/1"]["about"] == "Dandadan")
# MyAnimeList sync and posters, with fake services
class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass
real_urlopen = h.urllib.request.urlopen
ASKED = []
def fake_urlopen(req, timeout=None):
    url = getattr(req, "full_url", req)
    ASKED.append(url)
    if "api.myanimelist.net" in url:
        assert req.headers.get("X-mal-client-id") == "mid"
        if "/animelist?" in url:
            return Resp(json.dumps({"data": [
                {"node": {"id": 1, "title": "Witch Hat Atelier", "main_picture": {"large": "https://mal/wha.jpg"}, "genres": [{"name": "Fantasy"}], "mean": 8.9},
                 "list_status": {"status": "completed", "score": 10, "num_episodes_watched": 12}},
                {"node": {"id": 2, "title": "Mob Psycho 100", "genres": [{"name": "Action"}]},
                 "list_status": {"status": "plan_to_watch", "score": 0}}]}).encode())
        return Resp(json.dumps({"data": [{"node": {"id": 7, "title": "Witch Hat Atelier", "media_type": "manga"},
                                           "list_status": {"status": "reading", "num_chapters_read": 80}}]}).encode())
    if "api.jikan.moe" in url:
        return Resp(json.dumps({"data": [{"mal_id": 9, "images": {"jpg": {"large_image_url": "https://jikan/x.jpg"}},
                                         "genres": [{"name": "Drama"}], "themes": [], "score": 8.1}]}).encode())
    if "wikipedia.org" in url:
        return Resp(json.dumps({"query": {"pages": [{"thumbnail": {"source": "https://wiki/game.jpg"}}]}}).encode())
    return real_urlopen(req, timeout=timeout)
h.urllib.request.urlopen = fake_urlopen
h.MAL_CLIENT_ID, h.MAL_USERNAME = "mid", "someone"
r = h.sync_mal()
wha = next(x for x in h.library() if x["title"] == "Witch Hat Atelier")
check("MAL: status and progress win, picture and genres added", wha["status"] == "done" and wha["progress"] == "Ep 12"
      and wha["image"] == "https://mal/wha.jpg" and "Fantasy" in wha["genres"] and r["added"] == 2)
check("MAL: the manga of the same title stays separate", next(x for x in h.library() if x["title"] == "Witch Hat Atelier (manga)")["progress"] == "Ch 80")
check("MAL: new titles join the queue", next(x for x in h.library() if x["title"] == "Mob Psycho 100")["status"] == "queue")
h.time.sleep = lambda s: None
n = h.enrich_library(limit=40)
check("posters: anime from Jikan, games from Wikipedia", n > 0 and next(x for x in h.library() if x["title"] == "Elden Ring")["image"] == "https://wiki/game.jpg"
      and next(x for x in h.library() if x["title"] == "Odd Taxi")["image"] == "https://jikan/x.jpg")
def broken(req, timeout=None):
    raise urllib.error.HTTPError(getattr(req, "full_url", ""), 403, "nope", {}, None)
h.urllib.request.urlopen = broken
try:
    h.sync_mal(); check("MAL refusal raises", False)
except h.LLMError as e:
    check("MAL refusal explains: " + str(e), "403" in str(e) and "public" in str(e))
h.urllib.request.urlopen = fake_urlopen
# round
h.TMDB_API_KEY = ""
h.store().set_meta("round:lenz:sync_day", "")
LLM_REPLY = "Worth a look."
r = h.run_round(force=True, only=["lenz"])
check("Lenz's round: syncs, posts followed news, still pitches: " + r["ran"]["lenz"]["did"], r["ran"]["lenz"]["ok"]
      and "synced MyAnimeList" in r["ran"]["lenz"]["did"] and "news item" in r["ran"]["lenz"]["did"])
check("news lands in #watch-and-listen", any(m["text"].startswith("News on what you follow") for m in h.allchat_view(channel="screen")))
h.outlet_items = real_outlets
h.urllib.request.urlopen = real_urlopen
# pages
s, page = call("GET", "/lenz", headers=K)
check("Lenz's page renders with the library", s == 200 and b"window.LENZ = {" in page and b"Attack on Titan" in page and b'id="lenz-view"' in page)
s, page = call("GET", "/", headers=K)
check("Lenz's window opens his page, not a sheet", b'href="/lenz"' in page and b'href="/lenz" data-sheet' not in page)
print("done")
