"""2026-11-04: the Theta page is the only page. Widgets 1-4 spaces big when Theta is minimized, important
first and new-only (the rest searchable from the type bar), Theta's cards in a terminal above everything,
and every other page opening inside the Theta page. No live network."""
import sys, os, json, re
sys.dont_write_bytecode = True
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
os.environ.update(DASHBOARD_KEY="dk", HEAD_MODE="single", GLASS_BUDGETS="Groceries:400,Dining:150",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


K = {"x-dashboard-key": "dk", "host": "x"}
h.glass_log_reply((182.4, "groceries", "costco")); h.glass_log_reply((196.0, "dining", "sushi"))
h.add_reminder("tomorrow at 9am call the bank")
h.focus_start("20 taxes")
s, kind, out = h.handle("GET", "/api/board", {}, K, b"")[:3]
d = json.loads(out)
ws = {w["id"]: w for w in d["widgets"]}
check("the board answers, signed in only", s == 200 and d["ok"] and h.handle("GET", "/api/board", {}, {}, b"")[0] == 401)
check("widgets are 1 to 4 spaces", all(w["size"] in (1, 2, 3, 4) for w in d["widgets"]))
check("over budget is important, and says by how much", ws["money"]["important"] and "Dining" in ws["money"]["big"])
check("a focus session is important while it runs", ws["focus"]["important"] and "taxes" in ws["focus"]["sub"])
check("reminders are a wide list (the words and their Done button both fit)", ws["reminders"]["size"] == 2 and any("call the bank" in r[1] for r in ws["reminders"]["rows"]))
imp = [w["important"] for w in d["widgets"]]
check("important ones come first", imp == sorted(imp, reverse=True))
check("each widget has a signature that changes only with what it says", all(re.fullmatch(r"[0-9a-f]{12}", w["sig"]) for w in d["widgets"]))
h.glass_log_reply((5.0, "groceries", "gum"))
d2 = json.loads(h.handle("GET", "/api/board", {}, K, b"")[2])
check("...the money widget's signature moved when spending did", {w["id"]: w for w in d2["widgets"]}["money"]["sig"] != ws["money"]["sig"])
check("every widget is searchable", all(w["search"] and w["title"].lower() in w["search"] for w in d["widgets"]))
check("the full pages are always findable as apps", {a["title"] for a in d["apps"]} >= {"Settings", "Diagnostics", "Money", "Calendar", "Mail"})
_nw = h.news_windows
h.news_windows = lambda: 1 / 0
check("a failing part never blanks the board", h.board()["widgets"] != [])
h.news_windows = _nw

# ---- the Theta page
page = h.head_page(K)
for i in ("board", "bgrid", "board-open", "term", "term-body", "wsheet", "wsheet-frame"):
    check(f"the Theta page has #{i}", f'id="{i}"' in page)
js = h.BOARD_JS
check("shown: important, or new since you looked", "w.important || seen[w.id] !== w.sig" in js and '"theta:seen"' in js)
check("seen only after a look (2.5 s on the board), and never while searching", "seenTimer = setTimeout" in js and "if (!q &&" in js)
check("the type bar searches every widget and page, seen or not", "list = data.widgets.filter(hit)" in js and "data.apps.filter(hit)" in js)
check("commands and mentions aren't searches", '!q.startsWith("/") && !q.startsWith("@")' in js)
check("typing minimizes Theta to show the results", 'ST().dock("search")' in js)
check("the Widgets button and a swipe up minimize Theta", 'openBtn.onclick = () => { if (ST()) ST().dock("board")' in js and "dy > 80" in js)
check("sizes: 1 small, 2 wide, 3 tall, 4 big", ".w.s2{grid-column:span 2}.w.s3{grid-row:span 2}.w.s4{grid-column:span 2;grid-row:span 2}" in h.BOARD_CSS)
check("widgets wear the frame (they're cards) and arrive its way", '"w card s"' in js and "var(--in,pagein)" in h.BOARD_CSS)
check("no tab bar on the only page", "body.headchat .tabbar{display:none}" in h.BOARD_CSS)
check("the stage can be minimized by the board, and panels closing don't undo it", "window.thetaStage = {dock, undock" in h._STAGE_JS
      and 'dockBy === "panels") undock()' in h._STAGE_JS)
check("terminal: a copy, so the message stays in the chat; taps and typing go to the real card", "mirror(r)" in js
      and "o.click()" in js and 'o.dispatchEvent(new Event("input"' in js and "tbody.replaceChildren(r)" not in js)
check("terminal: an old card doesn't pop up on open, and a closed one stays closed", "30 * 60e3" in js and '"theta:termClosed"' in js)
check("chat rows carry their id", "row.dataset.id = m.id" in h._CHAT_JS)
check("terminal: only real cards, not the copy/share footer every reply has", '.msg-acts:not(.macts)' in js and '"msg-acts macts"' in h._CHAT_JS)
check("terminal: never copies a reply while it's still typing", 'r.querySelector(".caret")' in js)
check("open chat covers the board instead of sitting on it", "body.showchat #board,body.showchat .board-open{visibility:hidden}" in h.BOARD_CSS)
check("Theta never promises to do something after its reply", "nothing happens after it" in h._HEAD_ALONE and "background tool" in h._HEAD_ALONE
      and "nothing happens after it" in h.head_system() and "nothing happens after it" in h.head_system(native=True))

# ---- one page
home = h.handle("GET", "/money", {}, K, b"")[2].decode()
check("other pages send you to the Theta page, opened there", "window.THETA_ONEPAGE=true" in home and '"/head?open="+encodeURIComponent' in home)
check("...except inside its sheet, or when asked for the full page", "window.top!==window" in home and "full=1" in home)
check("inside the sheet the page drops the app's bars", "html.embedded .tabbar,html.embedded .minibar,html.embedded .theta-mini" in h._UI_CSS)
sec = dict(h.SECURITY_HEADERS)
check("only the hub frames the hub (other sites still can't)", sec["X-Frame-Options"] == "SAMEORIGIN" and "frame-ancestors 'self'" in sec["Content-Security-Policy"])
check("the sheet only opens the app's own paths", "/^\\/[A-Za-z0-9\\/#?=&._-]*$/.test(want)" in js and '!want.startsWith("//")' in js)
check("a look changed in the sheet shows on the Theta page", "look() !== lookAt" in js)
print("done")

# ---- the board's goal, learning your order, news interests (2026-11-04, later)
d = h.board()
check("every widget is a task to clear, the world, or for later", all(w["cat"] in ("task", "world", "later") for w in d["widgets"])
      and all(w["cat"] == "world" for w in d["widgets"] if w["id"] in h.BOARD_WORLD))
check("Theta knows the goal: in its prompt, its glance, and a board lookup", h.BOARD_PURPOSE in h.head_system(native=True)
      and h.BOARD_PURPOSE in h.head_system() and "Board:" in h.head_glance() and "board" in h.head_tools() and "board" in h.HEAD_LOOKUPS)
check("the board lookup lists what's left to clear", "Widgets to clear:" in h._tool_board("now", "theta"))
check("the glance never fetches the news (tasks only)", "world=False" in open(h._PARTS_DIR + "/board.py").read())
h.store().set_meta("board:reward", "{}")
before = {w["id"]: w["score"] for w in h.board()["widgets"]}
r = json.loads(h.handle("POST", "/api/board/click", {}, K, json.dumps({"id": "daily", "order": 1}).encode())[2])
r2 = json.loads(h.handle("POST", "/api/board/click", {}, K, json.dumps({"id": "reminders", "order": 3}).encode())[2])
check("a first tap earns more than a third", r["reward"] == 1 and abs(r2["reward"] - 1 / 3) < .01)
after = {w["id"]: w["score"] for w in h.board()["widgets"]}
check("...and lifts the widget on the board", after["daily"] > before["daily"] and after["daily"] - before["daily"] > after["reminders"] - before["reminders"])
check("news earns no order reward", h.board_click("news", 1) == {} and h.board_click("breaking", 1) == {})
check("rewards fade by half in two weeks", abs(h._decay(1, 0, h.REWARD_HALF_LIFE) - .5) < 1e-9)
h.board_click("", 1, "Mars rover finds water ice near the equator", kind="news")
t = h.board_topics()
check("opening a story makes its topics more interesting (common words aren't topics)", t.get("mars", 0) > 0 and t.get("rover", 0) > 0 and "the" not in t and "near" not in t)
_nw = h.news_windows
h.news_windows = lambda: [{"raw": "Stocks slip on rates", "href": "https://a", "source": "A"},
                          {"raw": "City council meets", "href": "https://b", "source": "B"},
                          {"raw": "Mars rover drills deeper", "href": "https://c", "source": "C"}]
news = {w["id"]: w for w in h.board()["widgets"]}["news"]
h.news_windows = _nw
check("news order is the outlets' except stories on topics you like, which come first and say so",
      news["items"][0]["t"].startswith("Mars") and news["items"][0]["s"].startswith("For you") and news["items"][1]["t"].startswith("Stocks"))
js = h.BOARD_JS
check("the page sends taps in order, and counts a new look from 1", "tap({id: w.id, order: ++taps})" in js and "taps = 0; // a new look" in js)
check("the header counts what's left to clear", "to clear" in js and "just the world now" in js)
css = h._UI_CSS
check("Hologram: faint scan lines over its cards, still with reduced motion", "repeating-linear-gradient(0deg,color-mix(in srgb,var(--text) 5%,transparent) 0 1px,transparent 1px 3px)" in css
      and ':root[data-glassstyle="holo"] .card::before{animation:none}' in css)
check("Hologram: the gyro tilts it 85% less (4deg -> 0.6deg, 3deg -> 0.45deg)", "* 0.6deg" in css and "* -0.45deg" in css and "* 4deg" not in css)
print("goal done")

# ---- the ticker, Theta hidden under the board, new schemes and frame, pictures as Theta (2026-11-04, later)
page = h.head_page(K)
js, css = h.BOARD_JS, h.BOARD_CSS
check("a ticker across the top while Theta is minimized", 'id="ticker"' in page and "body.docked .ticker:not([hidden]){display:flex}" in css
      and "@keyframes tkcrawl" in css)
check("the ticker: Theta's last reply first, then weather, what's next, breaking, headlines, releases", all(k in js for k in
      ('k: "Theta", t: lastReply', 'k: "Weather"', "W.calendar.eyebrow", 'k: "Breaking"', "W.news && W.news.items", "W.releases")))
check("it loops without a gap and pauses on a tap", "track.replaceChildren(...make(), ...make())" in js and 'classList.toggle("held")' in js)
check("reduced motion: the ticker holds still", "@media (prefers-reduced-motion:reduce){.tk-track{animation:none}" in css)
check("minimized: Tap to talk, the caption and Talk are hidden outright (not just faded)",
      "body.docked #head-state,body.docked #head-said{visibility:hidden}" in css and "body.docked .hud .talk" in css)
new = ["gilded", "lattice", "bloom", "neonrift", "verdant", "lunar", "bloodsign", "nightfiligree", "dusk"]
check("nine schemes from game menus", all(n in h.THEMES for n in new) and len(h.THEMES) == 28)
check("the Filigree frame: double lines, engraved capitals, unveils, chimes", "ornate" in h.FRAMES and h.FRAME_FONTS["ornate"][1] == "cinzel"
      and ':root[data-glassstyle="ornate"] .card' in h._UI_CSS and "@keyframes in-unveil" in h._UI_CSS and "ornate(c, o, t)" in h._UI_JS)
check("Cinzel is shipped", os.path.isfile(os.path.join(h._PARTS_DIR, "fonts", "cinzel-700.woff2")))
hj = h._HEAD_JS
check("your pictures as Theta: up to four, one per state", '<option value="image">Your pictures</option>' in page and 'id="av-img"' in page
      and "const STATE_IX = {idle: 0, listening: 1, thinking: 2, speaking: 3}" in hj)
check("a GIF keeps moving (it's the canvas's own background) and goes to the corner with Theta", "cv.style.backgroundImage = `url(" in hj)
check("pictures are shrunk, GIFs kept up to 2.5 MB, and too big says so", "600 / Math.max" in hj and "2.5e6" in hj and "too big to keep on this device" in hj)
check("the ring breathes with the voice in the mood's color", "function drawPicture(t, lv)" in hj and "col(0, 8, 0.35 + 0.6 * lv)" in hj)
print("ticker done")
# ---- backgrounds: your picture, and Spotlight (2026-11-04, later)
import datetime as _d
_t = _d.datetime.now(h.hub_tz()).date()
h.store().set_meta("releases", json.dumps({"at": 0, "day": _t.isoformat(), "by": {
    "tmdb": [{"title": "Avengers: Doomsday", "kind": "movie", "date": (_t + _d.timedelta(days=44)).isoformat(),
              "image": "https://image.tmdb.org/t/p/w342/x.jpg", "pop": 900, "url": "https://www.themoviedb.org/movie/1"},
             {"title": "Quiet Garden Show", "kind": "tv", "date": (_t + _d.timedelta(days=60)).isoformat(),
              "image": "https://image.tmdb.org/t/p/w342/y.jpg", "pop": 50, "url": "https://www.themoviedb.org/tv/2"}],
    "games": [{"title": "Grand Theft Auto VI", "kind": "game", "date": (_t + _d.timedelta(days=15)).isoformat(),
               "image": "https://media.rawg.io/g.jpg", "pop": 5000, "url": "https://rawg.io/games/gta-vi"},
              {"title": "No Picture Game", "kind": "game", "date": _t.isoformat(), "image": "", "pop": 1, "url": "https://rawg.io/games/x"}]}}))
h.store().set_meta("board:topics", json.dumps({"avengers": {"v": 3, "at": __import__("time").time()}}))
sp = h.spotlight()
titles = [x["title"] for x in sp]
check("Spotlight: what's coming, with a picture and where it was found", sp and all(x["image"].startswith("https://") and x["url"].startswith("https://") and x["site"] for x in sp)
      and "No Picture Game" not in titles)
check("Spotlight: topics you read about come first, and say why", titles[0] == "Avengers: Doomsday" and "avengers" in sp[0]["why"])
check("Spotlight: big posters, not thumbnails", "/t/p/w780/" in sp[0]["image"])
check("Spotlight: answers signed in only", h.handle("GET", "/api/spotlight", {}, {}, b"")[0] == 401
      and json.loads(h.handle("GET", "/api/spotlight", {}, K, b"")[2])["items"])
ui = h._UI_JS
check("the page rotates it, crossfading, with a caption that links to the source", "function startSpot()" in ui and 'a.setAttribute("aria-label", "Found on " + it.site)' in ui
      and 'target="_blank" rel="noopener"' in ui and "15000" in ui)
check("your picture as the background, kept on this device", 'localStorage.getItem("theta:bgimg")' in ui
      and h.ui_prefs({"cookie": "theta_ui=theta.dark.grid.plus.image"})[4] == "image" and h.ui_prefs({"cookie": "theta_ui=theta.dark.grid.plus.spotlight"})[4] == "spotlight")
sett = h.handle("GET", "/settings", {}, K, b"")[2].decode()
check("Settings: Spotlight, Your picture, and a picker", 'data-val="spotlight"' in sett and 'data-val="image"' in sett and 'id="bg-pick"' in sett)
print("backgrounds done")

# ---- live clearing, new dots, and the ADD pass (2026-11-04, later)
h.add_reminder("in 1 minute stretch your legs")
d = {w["id"]: w for w in h.board()["widgets"]}
r = d["reminders"]
due = [a for a in r["acts"] if a]
check("a due reminder clears in one tap (Done, even before its time)", r["cat"] == "task" and due and due[0]["post"].endswith("/done?early=1"))
rid = int(due[0]["post"].split("/")[3])
check("...and the API removes a one-off done early", json.loads(h.handle("POST", f"/api/reminders/{rid}/done", {"early": ["1"]}, K, b"{}")[2])["ok"]
      and not any(x["id"] == rid for x in h.reminders()))
d = {w["id"]: w for w in h.board()["widgets"]}
check("with nothing due, reminders are for later, not something to clear", d.get("reminders", {}).get("cat") in ("later", None))
dl = d.get("daily")
check("the daily check clears one item per tap, and leaves when all are done", dl and all(a and a["post"] == "/api/daily/toggle" for a in dl["acts"]))
for a in dl["acts"]:
    h.handle("POST", "/api/daily/toggle", {}, K, json.dumps(a["body"]).encode())
check("...gone once every item is ticked", "daily" not in {w["id"] for w in h.board()["widgets"]})
check("the calendar, a running focus and plain spending are for later, not to clear", all(w["cat"] != "task" for w in h.board()["widgets"]
      if w["id"] in ("calendar", "focus") or (w["id"] == "money" and not w["important"])))
check("the crew's old windows are off the board (they repeated other widgets)", not any(w["id"].startswith("crew-") for w in h.board()["widgets"]))
js, css = h.BOARD_JS, h.BOARD_CSS
check("live: every 20 s while the board is up, and right after Theta answers or a tap", "}, 20000);" in js and "setTimeout(load, 1200)" in js and "setTimeout(load, 350)" in js)
check("live: something new appears at once; what got dealt with leaves at once, sliding out", "shown.add(w.id)" in js and 'classList.add("leaving")' in js and "@keyframes wleave" in css)
check("live: what stays keeps its element (no flicker)", "o.dataset.sig === w.sig" in js and ".w.kept{animation:none}" in css)
check("new widgets wear a dot of their own color (red stays for important)", ".w.isnew::after" in css and "var(--accent2)" in css and '" isnew"' in js)
check("cleared: counted for today, with a toast", '"theta:cleared"' in js and "Cleared: " in js and ".btoast" in css)
check("ADD: one thing marked Start here; at most four to clear at once, the rest behind +N more", '"Start here"' in js and "TASKS_MAX = 4" in js and "more to clear" in js)
check("ADD: the full pages are small chips, not big tiles", "function chips(apps)" in js and ".approw" in css)
check("ADD: the ticker holds still while you type", '$("ticker").classList.add("held")' in js)
check("ADD: tap targets are big enough on a phone", "@media (pointer:coarse){.w .rdone{width:40px;height:40px}.bchip{min-height:38px}}" in css)
print("live done")

# ---- the calendar: today only, with the day as a scored ring (2026-11-04, later)
import datetime as _dd
_n = _dd.datetime.now(h.hub_tz()).replace(hour=12, minute=0, second=0, microsecond=0)
_ev = lambda t, a, b: {"title": t, "location": "", "start": _n + _dd.timedelta(minutes=a), "end": _n + _dd.timedelta(minutes=b), "all_day": False, "birthday": False}
h.REMI_CALENDAR_URLS = ["https://cal.example/x.ics"]
h.calendar_events = lambda a, b: [_ev("Standup", -120, -60), _ev("Gym", -30, 30), _ev("Dentist", 60, 120),
                                  _ev("Tomorrow thing", 24 * 60 + 30, 24 * 60 + 60)]
cal = {w["id"]: w for w in h.board(_n)["widgets"]}["calendar"]
check("the calendar shows today only", "Tomorrow" not in json.dumps(cal) and cal["title"] == "Today")
rg = cal["ring"]
check("the day as a ring: each of today's events an arc, a hand at now", len(rg["arcs"]) == 3 and rg["now"] == 720 and rg["arcs"][0]["s"] == 600)
check("the ring scores the day: how much of today's scheduled time is behind you, and what's left", rg["score"] == 50 and rg["left"] == 2 and rg["total"] == 3)
check("the page draws it (done arcs dim, a now hand, the score in the middle)", "function dayRing(r)" in h.BOARD_JS and '"dr-done"' in h.BOARD_JS
      and '"dr-now"' in h.BOARD_JS and ".dayring .dr-score" in h.BOARD_CSS)
print("calendar done")

# ---- Spotlight's credit is a small line at the top, out of the replies' way (2026-11-04, later)
css = h._UI_CSS
check("Spotlight's credit: one small line at the top, hidden under panels, the board and the sheet",
      ".spot-cap{position:fixed;left:max(12px,env(safe-area-inset-left,0px));top:calc(env(safe-area-inset-top,0px) + 10px)" in css
      and "body.docked .spot-cap,body.has-panels .spot-cap,body.sheet-open .spot-cap{display:none}" in css)
check("panels on screen mark the page, so the credit steps aside", 'document.body.classList.toggle("has-panels", n > 0)' in h._DECK_JS)
print("credit done")
