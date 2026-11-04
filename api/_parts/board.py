"""The widget board (2026-11-04). Part of api/index.py, loaded INTO its namespace by _load_part() (see
store.py).

The Theta page is the only page now. When Theta is minimized, what was on Home, Money, Calendar and
Diagnostics shows as widgets 1 to 4 spaces big: 1 a small tile (one number), 2 a wide strip, 3 a tall
list, 4 a big square. A widget is shown when it has something you haven't seen yet, or when it's
important right now (breaking news, a failing check, over budget, something overdue); important ones
come first. Everything stays reachable: the type bar searches every widget, seen or not, and tapping
one opens its full page in a sheet on the Theta page. Each widget's `sig` changes only when what it
says changes, so the page can tell new from seen. No model calls; one pass over data the hub keeps."""

BOARD_APPS = [  # always findable, never "new": the full pages, opened in a sheet
    ("settings", "Settings", "/settings", "theme frame font sounds voice notifications widget gmail memory face id"),
    ("diagnostics", "Diagnostics", "/diagnostics", "health checkup security harness speed wiring"),
    ("money", "Money", "/money", "budget spending expenses ledger"),
    ("calendar", "Calendar", "/calendar", "events reminders schedule"),
    ("mail", "Mail", "/mail", "email gmail inbox"),
    ("chat", "Chat history", "#chat", "messages conversation transcript"),
    ("lenz", "Lenz", "/lenz", "shows games movies releases library"),
]


# The board's goal (2026-11-04): clear every widget that isn't the world (news, entertainment, weather).
# A "task" widget leaves when it's dealt with (or seen, unless it's important); what's left is the world.
BOARD_WORLD = {"breaking", "news", "trending", "releases", "weather"}
BOARD_PURPOSE = ("The board (the user's widgets when you're minimized) has one goal: clear every widget that isn't the "
                 "world. News, entertainment, releases and weather are meant to stay; everything else (reminders, "
                 "money, calendar, diagnostics, jobs, the daily check) is something to deal with and clear. When a "
                 "widget is waiting to be cleared, help the user clear it: do it with your tools, or say the one "
                 "step that clears it. A clear board is the user caught up.")

# What you tap first on the board counts most: a widget's reward is 1 for a first tap, 1/2 for a second,
# 1/3 for a third (in one look at the board), fading by half every two weeks. News keeps its own order
# except for stories on topics you've opened before.
REWARD_HALF_LIFE = 14 * 86400
_STOP = set("the a an and or of to in on for with at by from as is are was were be been has have had it its this that "
            "after over into about new says say said will would could more most than but not no yes how why what who "
            "when where which their they them his her he she you your our we us i up out off just after before amid "
            "near finds find gets get makes make take takes back first last year years week day days today while still".split())


def _decay(v, at, now):
    return v * 0.5 ** (max(0, now - at) / REWARD_HALF_LIFE)


def board_rewards(now=None):
    now = now or time.time()
    r = _meta_json("board:reward", {})
    return {k: _decay(v.get("v", 0), v.get("at", now), now) for k, v in r.items()}


def topic_words(title):
    return {w for w in re.findall(r"[a-z][a-z'-]{3,}", (title or "").lower()) if w not in _STOP}


def board_topics(now=None):
    now = now or time.time()
    t = _meta_json("board:topics", {})
    return {k: _decay(v.get("v", 0), v.get("at", now), now) for k, v in t.items()}


def board_click(wid, order=1, title="", kind="widget", now=None):
    """A tap on the board. Widgets: the first tap in a look at the board earns the most. News: the
    story's topics get a little more interesting (news order is otherwise untouched)."""
    now = now or time.time()
    wid = re.sub(r"[^a-z0-9-]", "", str(wid or "").lower())[:40]
    if kind == "news":
        t = _meta_json("board:topics", {})
        for w in topic_words(title):
            old = _decay(t.get(w, {}).get("v", 0), t.get(w, {}).get("at", now), now)
            t[w] = {"v": round(old + 1, 3), "at": now}
        t = dict(sorted(t.items(), key=lambda kv: -kv[1]["v"])[:200])
        store().set_meta("board:topics", json.dumps(t))
        return {"topics": len(t)}
    if not wid or wid in ("news", "breaking"):
        return {}
    try:
        order = max(1, min(int(order), 20))
    except (TypeError, ValueError):
        order = 1
    r = _meta_json("board:reward", {})
    old = _decay(r.get(wid, {}).get("v", 0), r.get(wid, {}).get("at", now), now)
    r[wid] = {"v": round(old + 1 / order, 3), "at": now}
    store().set_meta("board:reward", json.dumps(dict(sorted(r.items(), key=lambda kv: -kv[1]["v"])[:100])))
    return {"reward": r[wid]["v"]}


def _sig(*parts):
    return hashlib.sha1(json.dumps(parts, default=str, sort_keys=True).encode()).hexdigest()[:12]


def _w(wid, size, title, score, *, eyebrow="", big="", sub="", rows=None, items=None, open_="", important=False,
       tone="", search="", sig_parts=None):
    rows = [r for r in (rows or []) if r and r[0]]
    items = [i for i in (items or []) if i and i.get("t")]
    return {"id": wid, "cat": "world" if wid in BOARD_WORLD else "task", "size": size, "title": title, "eyebrow": eyebrow, "big": big, "sub": sub,
            "rows": [[str(a)[:80], str(b)[:80]] for a, b in rows][:6], "items": items[:5], "open": open_,
            "important": bool(important), "tone": tone, "score": score,
            "search": " ".join([title, eyebrow, big, sub, search] + [f"{a} {b}" for a, b in rows]
                               + [i.get("t", "") for i in items]).lower()[:1200],
            "sig": _sig(sig_parts if sig_parts is not None else [big, sub, rows, [i.get("t") for i in items]])}


def board(now=None, world=True):
    """Every widget the board can show, most important first. Each part is guarded: one failing never
    blanks the board."""
    now = now or datetime.now(hub_tz())
    out = []

    def part(fn):
        try:
            got = fn()
            out.extend(g for g in (got if isinstance(got, list) else [got]) if g)
        except Exception as e:
            print(f"board part {getattr(fn, '__name__', fn)} failed: {e!r}")

    t = now.timestamp()

    def w_reminders():
        rs = sorted(reminders(), key=lambda r: r["at"])
        due = [r for r in rs if r.get("pending") or r["at"] <= t + 3600]
        late = [r for r in due if r.get("pending") or r["at"] <= t]
        soon = [r for r in rs if r not in due][:3]
        show = (due + soon)[:5]
        if not show:
            return None
        return _w("reminders", 3, "Reminders", 95 if late else 60, eyebrow="Overdue" if late else "Coming up",
                  rows=[(("now" if r["at"] <= t else _clock(datetime.fromtimestamp(r["at"], hub_tz())))
                         if r["at"] - t < 20 * 3600 else datetime.fromtimestamp(r["at"], hub_tz()).strftime("%a"),
                         r["what"]) for r in show], open_="/calendar#reminders", important=bool(late), tone="warn" if late else "")

    def w_calendar():
        if not calendar_linked():
            return None
        evs = calendar_events(now.date(), now.date() + timedelta(days=1))
        timed = [e for e in evs if not e["all_day"] and isinstance(e["start"], datetime) and e["end"] > now]
        if not evs:
            return None
        nxt = timed[0] if timed else None
        mins = (nxt["start"] - now).total_seconds() / 60 if nxt else None
        return _w("calendar", 2, "Up next" if nxt else "Today", 90 if mins is not None and mins <= 120 else 50,
                  eyebrow=("Happening now" if mins is not None and mins <= 0 else f"In {int(mins)} min" if mins is not None and mins < 120
                           else f"{len(evs)} on the calendar"),
                  big=(nxt or evs[0])["title"][:60], sub=(_clock(nxt["start"]) + (f" · {nxt['location']}" if nxt.get("location") else "")) if nxt else "",
                  rows=[(_clock(e["start"]) if not e["all_day"] else "all day", e["title"]) for e in (timed or evs)[1:3]],
                  open_="/calendar", important=mins is not None and mins <= 60)

    def w_money():
        st = month_status(now.strftime("%Y-%m"))
        spent = sum(v["spent"] for v in st.values())
        budget = sum(v["budget"] or 0 for v in st.values())
        over = [(c, v) for c, v in st.items() if v["budget"] and v["spent"] >= v["budget"]]
        if not spent and not budget:
            return None
        if over:
            c, v = max(over, key=lambda cv: cv[1]["spent"] / cv[1]["budget"])
            return _w("money", 2, "Money", 88, eyebrow="Over budget", big=f"{c} ${v['spent']:,.0f} / ${v['budget']:,.0f}",
                      sub=f"{len(over)} categor{'y' if len(over) == 1 else 'ies'} over · ${spent:,.0f} this month",
                      open_="/money", important=True, tone="bad")
        share = spent / budget if budget else 0
        return _w("money", 1, "Money", 74 if share >= .9 else 35, eyebrow=now.strftime("%B"), big=f"${spent:,.0f}",
                  sub=f"{share:.0%} of ${budget:,.0f}" if budget else "spent so far", open_="/money",
                  important=share >= .9, tone="warn" if share >= .9 else "")

    def w_diag():
        bad = []
        for sv, text in watchdog_findings():
            if sv in ("high", "warn"):
                bad.append((sv, text))
        fails = _meta_json("round:failures", {})
        last_tick = float(store().get_meta("tick:last") or 0)
        rows = [("!" if sv == "high" else "·", text[:80]) for sv, text in bad[:3]]
        rows += [(AGENTS.get(a, {}).get("name", a), f"round failed: {str(e)[:60]}") for a, e in list(fails.items())[:2]]
        if last_tick and time.time() - last_tick > 1800:
            rows.append(("tick", f"last ran {_ago(last_tick)} ago"))
        high = any(sv == "high" for sv, _ in bad) or bool(fails)
        if not rows:
            return _w("diagnostics-ok", 1, "Diagnostics", 5, eyebrow="Health", big="All good", sub="no problems found",
                      open_="/diagnostics", sig_parts=["ok"])
        return _w("diagnostics", 2 if len(rows) < 3 else 3, "Diagnostics", 97 if high else 66,
                  eyebrow=f"{len(rows)} to look at", rows=rows, open_="/diagnostics", important=high, tone="bad" if high else "warn")

    def w_news():
        news = news_windows()
        if not news:
            return None
        out_ = []
        breaking = [n for n in news if n.get("tag")]
        if breaking:
            b = breaking[0]
            out_.append(_w("breaking", 4 if b.get("image") else 2, "Breaking", 99, eyebrow=b.get("source") or "News",
                           big=(b.get("raw") or b.get("title") or "")[:140], sub=(b.get("text") or "")[:160],
                           items=[{"t": (x.get("raw") or x.get("title") or "")[:90], "u": x.get("href"), "s": x.get("source")} for x in breaking[1:3]],
                           open_=b.get("href") or "/#news", important=True, tone="bad", search="news breaking",
                           sig_parts=[b.get("raw") or b.get("title")]))
        likes = board_topics()
        pool = [n for n in news if not n.get("tag")][:12]
        interest = lambda n: sum(likes.get(w, 0) for w in topic_words(n.get("raw") or n.get("title") or ""))
        ranked = sorted(pool, key=lambda n: -interest(n)) if likes else pool  # stable: the outlets' order otherwise
        top = ranked[:4]
        if top:
            out_.append(_w("news", 4, "Top stories", 30, eyebrow=f"{len(news)} from your outlets",
                           items=[{"t": (x.get("raw") or x.get("title") or "")[:100], "u": x.get("href"),
                                   "s": ("For you \u00b7 " if likes and interest(x) >= 1 else "") + (x.get("source") or ""),
                                   "img": x.get("image") if str(x.get("image") or "").startswith("https://") else ""} for x in top],
                           open_="/#news", search="news headlines"))
        return out_

    def w_trending():
        tr = trending_windows()[:4]
        if not tr:
            return None
        return _w("trending", 2, "Watch & listen", 20, eyebrow="Trending",
                  items=[{"t": (x.get("raw") or x.get("title") or "")[:80], "u": x.get("href"), "s": x.get("source") or x.get("site")} for x in tr],
                  open_="/lenz", search="entertainment trending lenz")

    def w_releases():
        today = now.date().isoformat()
        rel = [x for x in releases(now.date()) if x.get("followed")][:3]
        if not rel:
            return None
        out_today = [x for x in rel if x["date"] == today]
        return _w("releases", 1 if len(rel) == 1 else 2, "Releases", 80 if out_today else 25,
                  eyebrow="Out today" if out_today else "Coming up",
                  rows=[(x["date"][5:], x.get("title", "")) for x in rel], open_="/lenz", important=bool(out_today))

    def w_daily():
        items, done = daily_items(), daily_done()
        if not items:
            return None
        left = [i for i in items if i["id"] not in done]
        return _w("daily", 2, "Today's check", 55 if left else 8, eyebrow=f"{len(items) - len(left)} of {len(items)} done",
                  rows=[("☐" if i["id"] not in done else "☑", i["text"]) for i in items[:4]], open_="/#today",
                  sig_parts=[now.date().isoformat(), len(left)])

    def w_focus():
        f = focus_state()
        if not f or f.get("until", 0) <= time.time():
            return None
        left = max(1, round((f["until"] - time.time()) / 60))
        return _w("focus", 1, "Focus", 93, eyebrow="Focusing", big=f"{left} min", sub=f["task"][:40], important=True,
                  open_="", sig_parts=[f["task"], f["until"]])

    def w_weather():
        w = _meta_json("weather:today", {})
        if w.get("day") != now.date().isoformat():
            return None
        return _w("weather", 1, "Weather", 40 if w.get("rain", 0) >= 50 else 15, eyebrow=w.get("name", ""),
                  big=f"{w['hi']}° / {w['lo']}°", sub=f"{w['rain']}% rain", important=w.get("rain", 0) >= 70,
                  sig_parts=[w.get("day"), w.get("hi"), w.get("rain")])

    def w_jobs():
        js = jobs()[-3:]
        live = [j for j in js if j.get("status") in ("queued", "running")]
        if not js:
            return None
        return _w("jobs", 2, "Background jobs", 70 if live else 12, eyebrow=f"{len(live)} running" if live else "Done",
                  rows=[(f"#{j['id']}", f"{j['status']}: {j['task'][:60]}") for j in reversed(js)], open_="#chat")

    def w_dreams():
        ideas = [x for x in dream_taste() if x.get("auto") and x.get("at", 0) > time.time() - 36 * 3600]
        if not ideas:
            return None
        return _w("dreams", 2, "Overnight ideas", 45, eyebrow="Theta had these while you slept",
                  rows=[("💭", x.get("idea", "")[:80]) for x in ideas[-3:]], open_="#chat")

    def w_crew():
        chat = store().list_chat(60)
        wins = finish_windows(agent_windows(chat, _meta_json("cards", {})), _meta_json("cards:short", {}), _meta_json("cards:img", {}))
        return [_w(f"crew-{w['agent']}", 1, AGENTS.get(w["agent"], {}).get("name", w["agent"]), 10,
                   eyebrow="Crew", big=(w.get("title") or w.get("raw") or "")[:50], sub=(w.get("sub") or "")[:60],
                   open_=w.get("href") or "", search="crew agent")
                for w in wins[:4] if w.get("agent")]

    fns = (w_reminders, w_calendar, w_money, w_diag, w_news, w_trending, w_releases, w_daily, w_focus,
           w_weather, w_jobs, w_dreams, w_crew)
    for fn in fns if world else [f for f in fns if f not in (w_news, w_trending, w_releases, w_weather)]:
        part(fn)
    rw = board_rewards()
    for w in out:
        if w["id"] not in ("news", "breaking"):
            w["score"] += min(30, rw.get(w["id"], 0) * 8)
    out.sort(key=lambda w: (not w["important"], -w["score"]))
    apps = [{"id": "app-" + k, "size": 1, "title": label, "app": True, "open": href, "search": f"{label} {words}".lower(),
             "sig": "app", "important": False, "score": 0} for k, label, href, words in BOARD_APPS]
    return {"widgets": out, "apps": apps, "at": now.isoformat(timespec="seconds"),
            "to_clear": sum(1 for w in out if w["cat"] == "task" and w["id"] != "diagnostics-ok")}


def board_to_clear(now=None):
    """The task widgets on the board right now (what Theta is helping clear)."""
    return [w for w in board(now, world=False)["widgets"] if w["cat"] == "task" and w["id"] != "diagnostics-ok"]


def _tool_board(arg, agent):
    left = board_to_clear()
    if not left:
        return "The board is clear: only the world (news, entertainment, weather) is left."
    return "Widgets to clear: " + "; ".join(
        f"{w['title']} ({'important' if w['important'] else 'new'}): " + ", ".join(
            x for x in [w.get('big'), w.get('sub')] + [f"{a} {b}" for a, b in w.get('rows', [])[:3]] if x)[:160] for w in left)


TOOLS["board"] = ("board | now   (what's on the user's widget board waiting to be cleared; the goal is a board with only "
                  "news and entertainment left)", _tool_board, {"theta"})
HEAD_LOOKUPS.add("board")


def board_markup():
    """The board, the card terminal and the full-page sheet, added to the Theta page."""
    return ('<div id="ticker" class="ticker" aria-label="What\u2019s going on" hidden><div class="tk-track" id="tk-track"></div></div>'
            '<button type="button" id="board-open" class="board-open" hidden><span class="bo-grid" aria-hidden="true"></span>'
            '<span id="board-count">Widgets</span></button>'
            '<section id="board" aria-label="Widgets"><div class="bhead"><span id="board-title" aria-live="polite"></span>'
            '<button type="button" id="board-all" class="bchip">Show all</button></div><div class="bgrid" id="bgrid"></div></section>'
            '<section id="term" class="term" hidden aria-label="What Theta made"><div class="term-bar"><span class="term-dots" aria-hidden="true">'
            '<i></i><i></i><i></i></span><b>theta://card</b><button type="button" id="term-x" aria-label="Close">×</button></div>'
            '<div class="term-body" id="term-body"></div></section>'
            '<section id="wsheet" class="wsheet" hidden aria-label="Full page"><div class="wsheet-bar"><b id="wsheet-title"></b>'
            '<span style="display:flex;gap:8px"><button type="button" id="wsheet-full" class="bchip" title="Open it as its own page">Full page</button>'
            '<button type="button" id="wsheet-x" class="bchip">Close</button></span></div><iframe id="wsheet-frame" title="Full page"></iframe></section>')


BOARD_CSS = r"""
/* the ticker: a crawl across the top while Theta is minimized, like a sports or news channel */
.ticker{position:fixed;top:calc(env(safe-area-inset-top,0px) + 14px);left:max(12px,env(safe-area-inset-left,0px));
 right:calc(env(safe-area-inset-right,0px) + 72px);height:38px;z-index:7;overflow:hidden;display:none;align-items:center;
 border:1px solid color-mix(in srgb,var(--mood,var(--accent)) 35%,var(--border));border-radius:10px;
 background:color-mix(in srgb,var(--surface) 78%,transparent);-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);
 -webkit-mask-image:linear-gradient(90deg,transparent,#000 14px,#000 calc(100% - 22px),transparent);mask-image:linear-gradient(90deg,transparent,#000 14px,#000 calc(100% - 22px),transparent)}
body.docked .ticker:not([hidden]){display:flex}
.tk-track{display:flex;gap:0;white-space:nowrap;will-change:transform;animation:tkcrawl var(--tkdur,40s) linear infinite}
.ticker:hover .tk-track,.ticker.held .tk-track{animation-play-state:paused}
.tk-item{display:inline-flex;align-items:center;gap:7px;padding:0 16px;font-size:13.5px;color:var(--text);text-decoration:none;border-right:1px solid var(--border)}
.tk-item b{font-family:var(--f-label);font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--mood,var(--accent))}
.tk-item.bad b{color:var(--bad)}
@keyframes tkcrawl{to{transform:translateX(-50%)}}
@media (prefers-reduced-motion:reduce){.tk-track{animation:none}.ticker{overflow-x:auto}}
:root[data-glassstyle="edge"] .ticker,:root[data-glassstyle="breach"] .ticker{border-radius:0}
:root[data-glassstyle="breach"] .tk-item b{background:var(--accent);color:var(--on);padding:1px 6px}
:root[data-glassstyle="console"] .ticker{border-radius:2px;font-family:var(--f-mono)}
/* minimized: nothing of Theta's middle shows under the widgets (hidden outright, not just faded) */
body.docked .hud-mid,body.docked .caption,body.docked #head-hint,body.docked .wordmark,body.docked .hud .talk,
body.docked #head-state,body.docked #head-said{visibility:hidden}

body.headchat .tabbar{display:none}
body.headchat{--tabh:env(safe-area-inset-bottom,0px)}
#board{position:fixed;left:0;right:0;top:max(calc(env(safe-area-inset-top,0px) + 66px),var(--deckb,0px));bottom:var(--formh,96px);z-index:2;display:none;
 overflow-y:auto;overscroll-behavior:contain;padding:4px max(14px,env(safe-area-inset-left,0px)) 14px max(14px,env(safe-area-inset-right,0px))}
body.docked #board{display:block}
.bhead{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:0 2px 10px;font-size:13px;color:var(--muted)}
.bchip{font:inherit;font-size:12.5px;font-weight:650;border:1px solid var(--border);background:var(--surface2);color:var(--text);border-radius:999px;padding:5px 12px;cursor:pointer}
.bgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:minmax(108px,auto);grid-auto-flow:dense;gap:10px}
@media (min-width:720px){.bgrid{grid-template-columns:repeat(4,minmax(0,1fr))}}
.w{position:relative;display:flex;flex-direction:column;gap:3px;min-width:0;overflow:hidden;cursor:pointer;text-align:left;font:inherit;color:var(--text);
 padding:12px 13px;animation:var(--in,pagein) var(--in-dur,.42s) var(--in-ease,cubic-bezier(.2,.8,.2,1)) backwards}
.w.s2{grid-column:span 2}.w.s3{grid-row:span 2}.w.s4{grid-column:span 2;grid-row:span 2}
.w .ey{font-size:11px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);font-family:var(--f-label)}
.w h3{font-size:14px;margin:0;font-family:var(--f-head)}
.w .big{font-size:21px;font-weight:760;line-height:1.15;overflow-wrap:anywhere;font-family:var(--f-head);display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.w.s1 .big{font-size:19px}
.w .sub{font-size:12.5px;color:var(--muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.w .rows{display:grid;grid-template-columns:auto minmax(0,1fr);gap:3px 9px;font-size:13px;margin-top:4px}
.w .rows b{font-weight:650;color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums}
.w .rows span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.w .items{display:flex;flex-direction:column;gap:7px;margin-top:4px;font-size:13.5px}
.w .items a{color:var(--text);text-decoration:none;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.w .items small{color:var(--muted);font-size:11px;margin-right:6px}
.w .thumb{width:100%;height:96px;object-fit:cover;border-radius:calc(var(--r) - 6px);margin:2px 0 4px}
.w.bad{border-color:color-mix(in srgb,var(--bad) 60%,var(--border))}.w.warn{border-color:color-mix(in srgb,var(--warn) 55%,var(--border))}
.w.important::after{content:"";position:absolute;top:10px;right:10px;width:8px;height:8px;border-radius:50%;background:var(--bad);box-shadow:0 0 8px var(--bad)}
.w.app{grid-row:span 1;justify-content:flex-end;min-height:0}
.w.app h3{font-size:15px}.w.app .ey{opacity:.7}
.board-open{position:fixed;left:50%;transform:translateX(-50%);bottom:calc(var(--formh,96px) + 10px);z-index:5;display:inline-flex;align-items:center;gap:8px;
 font:inherit;font-size:13px;font-weight:700;padding:8px 14px;border-radius:999px;border:1px solid color-mix(in srgb,var(--mood,var(--accent)) 50%,var(--border));
 background:color-mix(in srgb,var(--surface) 80%,transparent);color:var(--text);-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);cursor:pointer}
body.docked .board-open{display:none}
.bo-grid{width:12px;height:12px;background:linear-gradient(currentColor,currentColor) 0 0/5px 5px no-repeat,linear-gradient(currentColor,currentColor) 7px 0/5px 5px no-repeat,
 linear-gradient(currentColor,currentColor) 0 7px/5px 5px no-repeat,linear-gradient(currentColor,currentColor) 7px 7px/5px 5px no-repeat}
body.docked:not(.showchat) .msgs{display:none}
body.docked #head-note,body.docked #head-taps,body.docked .hud-row,body.docked .hud .reply{opacity:0;pointer-events:none}
body.showchat .msgs{opacity:1!important;pointer-events:auto!important;transform:none!important;z-index:6}
/* the terminal: Theta's cards (tables, quizzes, docs, code) above everything */
.term{position:fixed;left:max(10px,env(safe-area-inset-left,0px));right:max(10px,env(safe-area-inset-right,0px));top:calc(env(safe-area-inset-top,0px) + 64px);
 z-index:9;max-height:62dvh;display:flex;flex-direction:column;background:color-mix(in srgb,var(--bg) 94%,transparent);
 -webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);border:1px solid color-mix(in srgb,var(--accent) 45%,var(--border));border-radius:14px;
 box-shadow:0 18px 50px rgba(0,0,0,.45),0 0 0 1px color-mix(in srgb,var(--accent) 12%,transparent);animation:termin .35s cubic-bezier(.2,.8,.2,1)}
@keyframes termin{from{opacity:0;transform:translateY(-10px) scale(.98)}}
.term[hidden]{display:none}
.term-bar{display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid var(--border);font:600 12px var(--f-mono);color:var(--muted);letter-spacing:.04em}
.term-bar b{flex:1;color:var(--accent);font-weight:700}
.term-dots{display:flex;gap:5px}.term-dots i{width:8px;height:8px;border-radius:50%;background:var(--border)}.term-dots i:first-child{background:var(--bad)}
.term-bar button{font:inherit;font-size:20px;line-height:1;border:0;background:none;color:var(--text);cursor:pointer;padding:0 4px}
.term-body{overflow:auto;padding:8px 12px 12px}
.term-body .msg{margin:0;animation:none}.term-body .msg .meta{display:none}
:root[data-glassstyle="edge"] .term,:root[data-glassstyle="breach"] .term{border-radius:0}
:root[data-glassstyle="console"] .term,:root[data-glassstyle="hud"] .term{border-radius:3px}
/* the full page, opened from a widget */
.wsheet{position:fixed;inset:0;z-index:30;display:flex;flex-direction:column;background:var(--bg);padding-top:env(safe-area-inset-top,0px);animation:sheetup .32s cubic-bezier(.2,.8,.2,1)}
.wsheet[hidden]{display:none}
@keyframes sheetup{from{transform:translateY(24px);opacity:0}}
.wsheet-bar{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px max(14px,env(safe-area-inset-left,0px)) 10px max(14px,env(safe-area-inset-right,0px));border-bottom:1px solid var(--border)}
.wsheet-bar b{font-family:var(--f-head);font-size:16px}
.wsheet iframe{flex:1;width:100%;border:0;background:var(--bg)}
@media (prefers-reduced-motion:reduce){.w,.term,.wsheet{animation:none}}
"""

BOARD_JS = r"""
(() => {
  const body = document.body; if (!body.classList.contains("headchat")) return;
  const H = window.THETA_H, $ = id => document.getElementById(id);
  const boardEl = $("board"), grid = $("bgrid"), title = $("board-title"), allBtn = $("board-all"), openBtn = $("board-open"), countEl = $("board-count");
  const msg = $("chat-msg"), form = $("chat-form"), deck = $("deck");
  const get = (k, d) => { try { const v = JSON.parse(localStorage.getItem(k)); return v == null ? d : v; } catch (e) { return d; } };
  const put = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
  const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };
  const ST = () => window.thetaStage;
  let data = {widgets: [], apps: []}, seen = get("theta:seen", {}), shown = null, showAll = false, seenTimer = 0;

  // ---- where the board fits: under the corner (and any panels), above the message box
  function measure() {
    const fr = form && form.getBoundingClientRect();
    if (fr && fr.height) document.documentElement.style.setProperty("--formh", Math.max(60, innerHeight - fr.top + 6) + "px");
    const d = deck && deck.children.length ? deck.getBoundingClientRect().bottom : 0;
    document.documentElement.style.setProperty("--deckb", (d ? d + 8 : 0) + "px");
  }
  addEventListener("resize", measure); setInterval(measure, 1500);
  if (window.ResizeObserver && deck) new ResizeObserver(measure).observe(deck);

  // ---- what shows: important first, then anything new since you last saw it (decided once per refresh,
  // so a widget never vanishes while you're looking at it)
  function fresh() { return data.widgets.filter(w => w.important || seen[w.id] !== w.sig); }
  function visible() { if (!shown) shown = new Set(fresh().map(w => w.id)); return data.widgets.filter(w => showAll || shown.has(w.id)); }
  function card(w, i) {
    const c = el("article", "w card s" + (w.size || 1) + (w.tone ? " " + w.tone : "") + (w.important ? " important" : "") + (w.app ? " app" : ""));
    c.tabIndex = 0; c.setAttribute("role", "button"); c.style.animationDelay = Math.min(i, 8) * 45 + "ms";
    if (w.app) { c.append(el("span", "ey", "Open"), el("h3", null, w.title)); }
    else {
      if (w.eyebrow) c.append(el("span", "ey", w.eyebrow));
      c.append(el("h3", null, w.title));
      const img = (w.items || []).find(x => x.img);
      if (w.size === 4 && img) { const im = el("img", "thumb"); im.src = img.img; im.alt = ""; im.loading = "lazy"; c.append(im); }
      if (w.big) c.append(el("div", "big", w.big));
      if (w.sub) c.append(el("div", "sub", w.sub));
      if (w.rows && w.rows.length) { const r = el("div", "rows"); w.rows.slice(0, w.size >= 3 ? 6 : 2).forEach(([a, b]) => r.append(el("b", null, a), el("span", null, b))); c.append(r); }
      if (w.items && w.items.length) {
        const l = el("div", "items");
        w.items.slice(0, w.size === 4 ? 4 : 2).forEach(x => { const a = el("a"); a.href = x.u || "#"; if (x.s) a.append(el("small", null, x.s)); a.append(x.t);
          if (/^https?:/.test(x.u || "")) { a.target = "_blank"; a.rel = "noopener"; } a.onclick = e => { e.stopPropagation(); if (w.id === "news" || w.id === "breaking") tap({kind: "news", title: x.t}); if (!/^https?:/.test(x.u || "")) { e.preventDefault(); openW({open: x.u, title: w.title}); } }; l.append(a); });
        c.append(l);
      }
    }
    c.onclick = () => openW(w); c.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openW(w); } };
    return c;
  }
  function render() {
    const q = (msg && msg.value || "").trim().toLowerCase();
    let list, label;
    if (q && !q.startsWith("/") && !q.startsWith("@")) {
      const words = q.split(/\s+/).filter(Boolean);
      list = data.widgets.concat(data.apps).filter(w => words.every(x => (w.search || "").includes(x)));
      label = list.length ? `${list.length} on the board for “${q}” · send to ask Theta` : `Nothing on the board for “${q}” · send to ask Theta`;
    } else {
      const v = visible(), imp = v.filter(w => w.important).length, left = v.filter(w => w.cat === "task" && w.id !== "diagnostics-ok").length;
      list = v.concat(data.apps); taps = 0; // a new look at the board
      label = !left ? "All clear · just the world now" : `${left} to clear` + (imp ? ` · ${imp} important` : "") + (v.length > left ? ` · ${v.length - left} from the world` : "");
    }
    grid.replaceChildren(...list.map(card)); title.textContent = label;
    allBtn.hidden = !!q; allBtn.textContent = showAll ? "Only new" : "Show all";
    const n = fresh().length, imp = data.widgets.filter(w => w.important).length;
    countEl.textContent = imp ? `${imp} important` : n ? `${n} new` : "Widgets"; openBtn.hidden = false;
    clearTimeout(seenTimer);
    if (!q && ST() && ST().docked()) seenTimer = setTimeout(() => { visible().forEach(w => { seen[w.id] = w.sig; }); put("theta:seen", seen); }, 2500);
  }
  allBtn.onclick = () => { showAll = !showAll; render(); };

  // ---- opening: the full page in a sheet on this page (the only page), a link in a new tab, or the chat
  const sheet = $("wsheet"), frame = $("wsheet-frame");
  const look = () => (document.cookie.match(/(?:^|; )theta_ui=([^;]*)/) || [])[1] || "";
  let lookAt = "";
  function openSheet(path, name) {
    if (!path) return;
    lookAt = look();
    frame.src = path; $("wsheet-title").textContent = name || ""; sheet.hidden = false; body.classList.add("sheet-open");
    if (window.thetaSfx) thetaSfx.play();
  }
  function closeSheet() {
    sheet.hidden = true; frame.src = "about:blank"; body.classList.remove("sheet-open");
    if (look() !== lookAt) { location.reload(); return; } // a new theme, frame or font was picked in there: wear it here too
    load();
  }
  $("wsheet-x").onclick = closeSheet;
  $("wsheet-full").onclick = () => { // the page on its own, for anything a framed page can't do (like asking to send notifications)
    let u; try { u = new URL(frame.contentWindow.location.href); } catch (e) { u = new URL(frame.src, location.href); }
    u.searchParams.set("full", "1"); location.href = u.pathname + u.search + u.hash;
  };
  addEventListener("keydown", e => { if (e.key === "Escape" && !sheet.hidden) closeSheet(); });
  // what you open first in a look at the board counts most (the board learns your order; news only learns topics)
  let taps = 0;
  const tap = body_ => fetch("/api/board/click", {method: "POST", headers: H, body: JSON.stringify(body_)}).catch(() => {});
  function openW(w) {
    if (w.id === "breaking") tap({kind: "news", title: w.big || ""});
    else if (w.id && !w.app) tap({id: w.id, order: ++taps});
    const u = w.open || "";
    if (/^https?:/.test(u)) { window.open(u, "_blank", "noopener"); return; }
    if (u === "#chat") { body.classList.toggle("showchat"); return; }
    if (u) openSheet(u, w.title);
  }
  window.thetaBoard = {open: openSheet, refresh: () => load()};

  // ---- minimizing Theta: the Widgets button, typing (the type bar searches the board), or swiping up
  openBtn.onclick = () => { if (ST()) ST().dock("board"); };
  document.addEventListener("theta:docked", e => { if (e.detail) { measure(); render(); } else { shown = null; body.classList.remove("showchat"); } });
  if (msg) msg.addEventListener("input", () => {
    const q = msg.value.trim();
    if (q && !q.startsWith("/") && !q.startsWith("@") && ST() && !ST().docked()) ST().dock("search");
    render();
  });
  let y0 = null;
  addEventListener("touchstart", e => { y0 = e.touches[0].clientY; }, {passive: true});
  addEventListener("touchend", e => { if (y0 == null) return; const dy = y0 - e.changedTouches[0].clientY; y0 = null;
    if (dy > 80 && ST() && !ST().docked() && sheet.hidden && !e.target.closest("#msgs,.term,.hud-more")) ST().dock("board"); }, {passive: true});


  // ---- the ticker: Theta's last reply, then the weather, what's next, breaking news and headlines, crawling
  // across the top while Theta is minimized. Tap holds it still; tap an item to open it.
  const ticker = $("ticker"), track = $("tk-track");
  let lastReply = "";
  const clean = t => (t || "").replace(/```[\s\S]*?```/g, " ").replace(/https?:\/\/\S+/g, "").replace(/[*_#`>|]/g, "").replace(/\s+/g, " ").trim();
  document.addEventListener("theta:thread", e => {
    const ms = (e.detail || []).filter(x => x.from === "theta" && x.kind !== "event"), m = ms[ms.length - 1];
    if (m) { lastReply = clean(m.text); if (lastReply.length > 160) lastReply = lastReply.slice(0, 157) + "…"; tick(); }
  });
  function tick() {
    const it = [], W = Object.fromEntries((data.widgets || []).map(w => [w.id, w]));
    if (lastReply) it.push({k: "Theta", t: lastReply, u: "#chat"});
    if (W.weather) it.push({k: "Weather", t: `${W.weather.big} · ${W.weather.sub}${W.weather.eyebrow ? " · " + W.weather.eyebrow : ""}`});
    if (W.calendar) it.push({k: W.calendar.eyebrow || "Next", t: W.calendar.big + (W.calendar.sub ? " · " + W.calendar.sub : ""), u: "/calendar"});
    if (W.breaking) it.push({k: "Breaking", t: W.breaking.big, u: W.breaking.open, bad: true});
    (W.news && W.news.items || []).forEach(x => it.push({k: (x.s || "News").replace(/^For you · /, "For you"), t: x.t, u: x.u}));
    if (W.releases) W.releases.rows.forEach(([d, t]) => it.push({k: W.releases.eyebrow, t: `${t} (${d})`, u: "/lenz"}));
    (W.trending && W.trending.items || []).slice(0, 2).forEach(x => it.push({k: "Trending", t: x.t, u: x.u}));
    if (W.money) it.push({k: "Money", t: `${W.money.big} · ${W.money.sub}`, u: "/money", bad: W.money.tone === "bad"});
    if (!it.length) { ticker.hidden = true; return; }
    const make = () => it.map(x => {
      const a = el(x.u ? "a" : "span", "tk-item" + (x.bad ? " bad" : ""));
      a.append(el("b", null, x.k), el("span", null, x.t));
      if (x.u) { a.href = x.u; if (/^https?:/.test(x.u)) { a.target = "_blank"; a.rel = "noopener"; }
        a.onclick = e => { if (/^https?:/.test(x.u)) { if (x.k !== "Theta") tap({kind: "news", title: x.t}); return; } e.preventDefault(); openW({open: x.u, title: x.k}); }; }
      return a;
    });
    track.replaceChildren(...make(), ...make()); // twice, so the crawl loops without a gap
    const chars = it.reduce((n, x) => n + x.t.length + x.k.length, 0);
    track.style.setProperty("--tkdur", Math.max(18, Math.round(chars / 7)) + "s");
    ticker.hidden = false;
  }
  ticker.addEventListener("pointerdown", e => { if (!e.target.closest("a")) ticker.classList.toggle("held"); });
  async function load() {
    try {
      const d = await (await fetch("/api/board", {headers: H})).json();
      if (!d.ok) return;
      data = d; seen = get("theta:seen", {}); if (!(ST() && ST().docked())) shown = null; render(); tick();
    } catch (e) {}
  }
  load(); setInterval(() => { if (!document.hidden) load(); }, 120000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });

  // a page asked for directly (/settings, /money...) opens here, in the sheet
  const want = new URLSearchParams(location.search).get("open");
  if (want && /^\/[A-Za-z0-9\/#?=&._-]*$/.test(want) && !want.startsWith("//")) {
    setTimeout(() => openSheet(want, want.replace(/^\//, "").split(/[#?]/)[0] || "Home"), 300);
    history.replaceState(null, "", location.pathname);
  }

  // ---- the terminal: when Theta makes a card (a table, a quiz, a doc, code, buttons to press), it shows
  // above everything. The card itself is moved here, so its buttons keep working.
  const term = $("term"), tbody = $("term-body");
  let termId = null, closed = get("theta:termClosed", null), firstThread = true;
  const CARD = ".quizcard,.doccard,.cfgcard,.codeblock,table,.msg-acts";
  document.addEventListener("theta:thread", () => setTimeout(() => {
    const rows = [...document.querySelectorAll("#msgs .msg:not(.mine)")].filter(r => r.querySelector(CARD));
    const r = rows[rows.length - 1], wasFirst = firstThread; firstThread = false;
    if (!r) return;
    const id = r.dataset.id || "", t = r.querySelector("time"), at = t ? Date.parse(t.dateTime) : Date.now();
    if (id === String(closed) || (wasFirst && Date.now() - at > 30 * 60e3)) return;
    tbody.replaceChildren(r); term.hidden = false; termId = id;
  }, 0));
  $("term-x").onclick = () => { term.hidden = true; closed = termId; put("theta:termClosed", termId); };
})();
"""
