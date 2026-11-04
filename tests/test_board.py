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
check("reminders are a tall list", ws["reminders"]["size"] == 3 and any("call the bank" in r[1] for r in ws["reminders"]["rows"]))
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
check("the type bar searches every widget, seen or not", "data.widgets.concat(data.apps).filter(w => words.every" in js)
check("commands and mentions aren't searches", '!q.startsWith("/") && !q.startsWith("@")' in js)
check("typing minimizes Theta to show the results", 'ST().dock("search")' in js)
check("the Widgets button and a swipe up minimize Theta", 'openBtn.onclick = () => { if (ST()) ST().dock("board")' in js and "dy > 80" in js)
check("sizes: 1 small, 2 wide, 3 tall, 4 big", ".w.s2{grid-column:span 2}.w.s3{grid-row:span 2}.w.s4{grid-column:span 2;grid-row:span 2}" in h.BOARD_CSS)
check("widgets wear the frame (they're cards) and arrive its way", '"w card s"' in js and "var(--in,pagein)" in h.BOARD_CSS)
check("no tab bar on the only page", "body.headchat .tabbar{display:none}" in h.BOARD_CSS)
check("the stage can be minimized by the board, and panels closing don't undo it", "window.thetaStage = {dock, undock" in h._STAGE_JS
      and 'dockBy === "panels") undock()' in h._STAGE_JS)
check("terminal: the card itself moves there, so its buttons work", "tbody.replaceChildren(r)" in js and ".quizcard,.doccard,.cfgcard,.codeblock,table,.msg-acts" in js)
check("terminal: an old card doesn't pop up on open, and a closed one stays closed", "30 * 60e3" in js and '"theta:termClosed"' in js)
check("chat rows carry their id", "row.dataset.id = m.id" in h._CHAT_JS)

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
check("every widget is a task to clear or the world", all(w["cat"] in ("task", "world") for w in d["widgets"])
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
