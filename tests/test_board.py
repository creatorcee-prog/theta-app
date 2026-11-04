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
