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
                 "step that clears it. Reminders that aren't due yet, the calendar, a running focus session and ordinary "
                 "spending are for later, not to clear. A clear board is the user caught up; say so when it is.")

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
       tone="", search="", sig_parts=None, cat=None):
    rows = [r for r in (rows or []) if r and r[0]][:6]
    items = [i for i in (items or []) if i and i.get("t")]
    acts = [(r[2] if len(r) > 2 else None) for r in rows]
    return {"id": wid, "cat": cat or ("world" if wid in BOARD_WORLD else "task"), "size": size, "title": title, "eyebrow": eyebrow,
            "big": big, "sub": sub, "rows": [[str(r[0])[:80], str(r[1])[:80]] for r in rows], "acts": acts if any(acts) else [],
            "items": items[:5], "open": open_,
            "important": bool(important), "tone": tone, "score": score,
            "search": " ".join([title, eyebrow, big, sub, search] + [f"{r[0]} {r[1]}" for r in rows]
                               + [i.get("t", "") for i in items]).lower()[:1200],
            "sig": _sig(sig_parts if sig_parts is not None else [big, sub, [r[:2] for r in rows], [i.get("t") for i in items]])}


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
        when = lambda r: (("now" if r["at"] <= t else _clock(datetime.fromtimestamp(r["at"], hub_tz())))
                          if r["at"] - t < 20 * 3600 else datetime.fromtimestamp(r["at"], hub_tz()).strftime("%a"))
        done = lambda r: {"post": f"/api/reminders/{r['id']}/done?early=1", "label": "Done"} if (r in due and "id" in r) else None
        return _w("reminders", 2, "Reminders", 95 if late else 60 if due else 20,
                  eyebrow="Overdue" if late else "Due soon" if due else "Coming up",
                  rows=[(when(r), r["what"], done(r)) for r in show], open_="/calendar#reminders", important=bool(late),
                  tone="warn" if late else "", cat=None if due else "later")

    def w_calendar():
        """Today only, with the day as a ring: 24 hours round, each event an arc, a hand at now; the middle
        scores the day's schedule (how much of today's scheduled time is behind you, and what's left)."""
        if not calendar_linked():
            return None
        today = now.date()
        evs = [e for e in calendar_events(today, today + timedelta(days=1))
               if (e["start"] if e["all_day"] else e["start"].date()) == today and not e.get("birthday")]
        if not evs:
            return None
        timed = sorted((e for e in evs if not e["all_day"] and isinstance(e["start"], datetime)), key=lambda e: e["start"])
        day0 = datetime.combine(today, datetime.min.time(), hub_tz())
        m = lambda d: max(0, min(1440, round((d - day0).total_seconds() / 60)))
        nowm = m(now)
        arcs = [{"s": m(e["start"]), "e": max(m(e["start"]) + 10, m(e["end"])), "t": e["title"][:40]} for e in timed]
        total = sum(x["e"] - x["s"] for x in arcs)
        behind = sum(max(0, min(x["e"], nowm) - x["s"]) for x in arcs)
        left = [e for e in timed if e["end"] > now]
        nxt = left[0] if left else None
        mins = (nxt["start"] - now).total_seconds() / 60 if nxt else None
        allday = [e for e in evs if e["all_day"]]
        w = _w("calendar", 2, "Today", 90 if mins is not None and mins <= 120 else 50,
               eyebrow=("Happening now" if mins is not None and mins <= 0 else f"Next in {int(mins)} min" if mins is not None and mins < 120
                        else f"Next at {_clock(nxt['start'])}" if nxt else "Nothing left today"),
               big=nxt["title"][:60] if nxt else ("All done for today" if timed else allday[0]["title"][:60]),
               sub=((_clock(nxt["start"]) + (f" \u00b7 {nxt['location']}" if nxt.get("location") else "")) if nxt else
                    (f"all day \u00b7 {len(allday)} event{'s' if len(allday) != 1 else ''}" if allday and not timed else "")),
               rows=[(_clock(e["start"]), e["title"]) for e in left[1:3]] + [("all day", e["title"]) for e in allday[:1] if timed],
               open_="/calendar", important=mins is not None and mins <= 60, cat="later",
               sig_parts=[today.isoformat(), [x["t"] for x in arcs], len(left), bool(nxt and mins is not None and mins <= 0)])
        w["ring"] = {"now": nowm, "arcs": arcs, "score": round(100 * behind / total) if total else None,
                     "left": len(left), "total": len(timed)}
        return w

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
                  important=share >= .9, tone="warn" if share >= .9 else "", cat=None if share >= .9 else "later")

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
        return _w("diagnostics", 2, "Diagnostics", 97 if high else 66,
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
        if not left:
            return None  # all done today: cleared
        return _w("daily", 2, "Today's check", 55, eyebrow=f"{len(items) - len(left)} of {len(items)} done",
                  rows=[("\u2610", i["text"], {"post": "/api/daily/toggle", "body": {"id": i["id"]}, "label": "Done"}) for i in left[:4]],
                  open_="/#today", sig_parts=[now.date().isoformat(), len(left)])

    def w_focus():
        f = focus_state()
        if not f or f.get("until", 0) <= time.time():
            return None
        left = max(1, round((f["until"] - time.time()) / 60))
        return _w("focus", 1, "Focus", 93, eyebrow="Focusing", big=f"{left} min", sub=f["task"][:40], important=True,
                  open_="", sig_parts=[f["task"], f["until"]], cat="later")

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
                  rows=[(f"#{j['id']}", f"{j['status']}: {j['task'][:60]}") for j in reversed(js)], open_="#chat",
                  cat="later" if live else None)

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
           w_weather, w_jobs, w_dreams)  # the crew's old windows repeat what other widgets say: off the board (2026-11-04)
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
.w.important::after{z-index:1;content:"";position:absolute;top:10px;right:10px;width:8px;height:8px;border-radius:50%;background:var(--bad);box-shadow:0 0 8px var(--bad)}
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
body.showchat .msgs{opacity:1!important;pointer-events:auto!important;transform:none!important;z-index:6;top:calc(env(safe-area-inset-top,0px) + 56px);bottom:calc(var(--formh,96px) + 8px);max-height:none;background:color-mix(in srgb,var(--bg) 92%,transparent);-webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px);border:1px solid var(--border);border-radius:14px;padding:10px 12px;overflow-y:auto;overscroll-behavior:contain}
/* the chat replaces the board while it's open, so the two never sit on top of each other */
body.showchat #board,body.showchat .board-open{visibility:hidden}
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
/* ---- live board (2026-11-04): dots, Start here, one-tap Done, leaving, cleared toast, app chips */
.w.isnew::after{content:"";position:absolute;top:10px;right:10px;width:8px;height:8px;border-radius:50%;background:var(--accent2);box-shadow:0 0 8px var(--accent2)}
.w .start{position:absolute;top:-1px;left:12px;font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--on);background:var(--accent);padding:1px 7px;border-radius:0 0 6px 6px}
.w.first{box-shadow:0 0 0 2px color-mix(in srgb,var(--accent) 55%,transparent),var(--shadow)}
.w.first .ey{margin-top:8px}
.w .rows{display:flex;flex-direction:column;gap:2px}
.w .rrow{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:9px;align-items:center;min-height:30px;transition:opacity .3s}
.w .rrow.doneit{opacity:.35;text-decoration:line-through}
.w .rdone{width:32px;height:32px;border-radius:50%;border:1.5px solid color-mix(in srgb,var(--good) 70%,var(--border));background:transparent;color:var(--good);font-size:15px;font-weight:800;cursor:pointer;flex:none}
.w .rdone:active{transform:scale(.9);background:color-mix(in srgb,var(--good) 20%,transparent)}
@media (pointer:coarse){.w .rdone{width:40px;height:40px}.bchip{min-height:38px}}
.w.kept{animation:none}
.w.leaving{animation:wleave .4s ease forwards;pointer-events:none}
@keyframes wleave{to{opacity:0;transform:scale(.92)}}
.approw{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.bchip.more{grid-column:1/-1;justify-self:start}
#board.allclear .bhead span{color:var(--good);font-weight:700}
.btoast{position:fixed;left:50%;bottom:calc(var(--formh,96px) + 60px);transform:translate(-50%,10px);z-index:12;opacity:0;pointer-events:none;
 padding:9px 16px;border-radius:999px;background:color-mix(in srgb,var(--good) 22%,var(--surface));border:1px solid color-mix(in srgb,var(--good) 60%,transparent);
 color:var(--text);font-weight:700;font-size:14px;transition:opacity .25s,transform .25s;max-width:86vw;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.btoast.in{opacity:1;transform:translate(-50%,0)}
@media (prefers-reduced-motion:reduce){.w.leaving{animation:none;display:none}}

/* the calendar's day ring */
.w.hasring{display:grid;grid-template-columns:112px minmax(0,1fr);column-gap:12px;align-items:start}
.w.hasring > *{grid-column:2}.w.hasring > .dayring{grid-column:1;grid-row:1 / span 6;width:112px;height:112px;align-self:center}
.dayring .dr-track{fill:none;stroke:color-mix(in srgb,var(--text) 12%,transparent);stroke-width:8}
.dayring .dr-tick{stroke:color-mix(in srgb,var(--text) 35%,transparent);stroke-width:1.5}
.dayring .dr-left{fill:none;stroke:var(--accent);stroke-width:8;stroke-linecap:butt}
.dayring .dr-done{fill:none;stroke:color-mix(in srgb,var(--accent) 35%,transparent);stroke-width:8}
.dayring .dr-now{stroke:var(--text);stroke-width:2.5;stroke-linecap:round}
.dayring .dr-score{fill:var(--text);font:800 19px var(--f-head);text-anchor:middle}
.dayring .dr-sub{fill:var(--muted);font:600 10.5px var(--f-body);text-anchor:middle}
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

  // ---- what shows: important first, then anything new since you last saw it. The set grows live (something
  // new or newly important appears at once) and a widget whose thing got dealt with leaves at once; one you've
  // only looked at stays until you next minimize Theta, so nothing vanishes under your finger.
  let newIds = new Set(), moreOpen = false;
  const TASKS_MAX = 4; // more than four things to do at once is a wall, not a list
  function fresh() { return data.widgets.filter(w => w.important || seen[w.id] !== w.sig); }
  function visible() {
    if (!shown) shown = new Set();
    fresh().forEach(w => { if (!shown.has(w.id)) { shown.add(w.id); if (!w.important && seen[w.id] !== w.sig) newIds.add(w.id); } });
    return data.widgets.filter(w => showAll || shown.has(w.id));
  }
  const isTask = w => w.cat === "task" && w.id !== "diagnostics-ok";
  function act(w, i, btn) { // one tap clears a row (a reminder done, a daily check ticked); the board updates at once
    const a = w.acts[i]; if (!a) return;
    btn.disabled = true; btn.closest(".rrow").classList.add("doneit");
    fetch(a.post, {method: "POST", headers: H, body: JSON.stringify(a.body || {})}).then(r => r.json()).then(d => {
      if (!d.ok) throw new Error(d.error || "didn’t work"); if (window.thetaSfx) thetaSfx.play(); setTimeout(load, 350);
    }).catch(e => { btn.disabled = false; btn.closest(".rrow").classList.remove("doneit"); toast(e.message || String(e)); });
  }
  function card(w, i, first) {
    const c = el("article", "w card s" + (w.size || 1) + (w.tone ? " " + w.tone : "") + (w.important ? " important" : newIds.has(w.id) ? " isnew" : "") + (first ? " first" : ""));
    c.dataset.id = w.id; c.tabIndex = 0; c.setAttribute("role", "button"); c.style.animationDelay = Math.min(i, 8) * 45 + "ms";
    c.setAttribute("aria-label", w.title + (w.important ? ", important" : newIds.has(w.id) ? ", new" : ""));
    if (first) c.append(el("span", "start", "Start here"));
    if (w.eyebrow) c.append(el("span", "ey", w.eyebrow));
    c.append(el("h3", null, w.title));
    const img = (w.items || []).find(x => x.img);
    if (w.size === 4 && img) { const im = el("img", "thumb"); im.src = img.img; im.alt = ""; im.loading = "lazy"; c.append(im); }
    if (w.ring) { c.classList.add("hasring"); c.append(dayRing(w.ring)); }
    if (w.big) c.append(el("div", "big", w.big));
    if (w.sub) c.append(el("div", "sub", w.sub));
    if (w.rows && w.rows.length) {
      const r = el("div", "rows");
      w.rows.slice(0, w.size >= 3 ? 6 : 3).forEach(([a, b], k) => {
        const row = el("div", "rrow"); row.append(el("b", null, a), el("span", null, b));
        if (w.acts && w.acts[k]) { const bt = el("button", "rdone", "✓"); bt.type = "button"; bt.title = w.acts[k].label; bt.setAttribute("aria-label", w.acts[k].label + ": " + b);
          bt.onclick = e => { e.stopPropagation(); act(w, k, bt); }; row.append(bt); }
        r.append(row);
      });
      c.append(r);
    }
    if (w.items && w.items.length) {
      const l = el("div", "items");
      w.items.slice(0, w.size === 4 ? 4 : 2).forEach(x => { const a = el("a"); a.href = x.u || "#"; if (x.s) a.append(el("small", null, x.s)); a.append(x.t);
        if (/^https?:/.test(x.u || "")) { a.target = "_blank"; a.rel = "noopener"; } a.onclick = e => { e.stopPropagation(); if (w.id === "news" || w.id === "breaking") tap({kind: "news", title: x.t}); if (!/^https?:/.test(x.u || "")) { e.preventDefault(); openW({open: x.u, title: w.title}); } }; l.append(a); });
      c.append(l);
    }
    c.onclick = () => openW(w); c.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openW(w); } };
    return c;
  }
  function dayRing(r) { // the day as a ring: midnight at the top, each event an arc (done ones dim), a hand at now
    const NS = "http://www.w3.org/2000/svg", S = 112, C = S / 2, R = 44, svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${S} ${S}`); svg.setAttribute("class", "dayring"); svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", r.total ? `${r.score}% of today's schedule is behind you, ${r.left} left` : "Nothing timed today");
    const pt = (min, rad) => { const a = min / 1440 * 2 * Math.PI - Math.PI / 2; return [C + Math.cos(a) * rad, C + Math.sin(a) * rad]; };
    const mk = (tag, at) => { const e = document.createElementNS(NS, tag); for (const k in at) e.setAttribute(k, at[k]); svg.append(e); return e; };
    mk("circle", {cx: C, cy: C, r: R, class: "dr-track"});
    [0, 360, 720, 1080].forEach(h => { const [x1, y1] = pt(h, R - 7), [x2, y2] = pt(h, R - 3); mk("line", {x1, y1, x2, y2, class: "dr-tick"}); });
    const arc = (s, e, cls) => { if (e - s < 1) return; const [x1, y1] = pt(s, R), [x2, y2] = pt(Math.min(e, 1439.9), R);
      mk("path", {d: `M${x1} ${y1} A${R} ${R} 0 ${e - s > 720 ? 1 : 0} 1 ${x2} ${y2}`, class: cls}); };
    r.arcs.forEach(a => { arc(a.s, Math.min(a.e, r.now), "dr-done"); arc(Math.max(a.s, r.now), a.e, "dr-left"); });
    const [hx, hy] = pt(r.now, R + 6), [ix, iy] = pt(r.now, R - 12); mk("line", {x1: ix, y1: iy, x2: hx, y2: hy, class: "dr-now"});
    const t1 = mk("text", {x: C, y: C - 2, class: "dr-score"}); t1.textContent = r.total ? r.score + "%" : "Free";
    const t2 = mk("text", {x: C, y: C + 14, class: "dr-sub"}); t2.textContent = r.total ? (r.left ? r.left + " left" : "all done") : "day";
    return svg;
  }
  function chips(apps) { // the full pages, as small chips at the end: always there, never in the way
    const row = el("div", "approw"); row.setAttribute("aria-label", "Pages");
    apps.forEach(a => { const b = el("button", "bchip", a.title); b.type = "button"; b.onclick = () => openW(a); row.append(b); });
    return row;
  }
  // live, keyed: a widget that's still there keeps its element (no flicker); one that left slides out
  function place(list, extra) {
    const old = new Map([...grid.children].filter(n => n.dataset.id).map(n => [n.dataset.id, n]));
    const next = list.map(([w, i, first]) => { const o = old.get(w.id);
      if (o && o.dataset.sig === w.sig + (first ? "1" : "") + (newIds.has(w.id) ? "n" : "")) { old.delete(w.id); o.style.animationDelay = "0ms"; o.classList.add("kept"); return o; }
      const c = card(w, i, first); c.dataset.sig = w.sig + (first ? "1" : "") + (newIds.has(w.id) ? "n" : ""); return c; });
    old.forEach(n => { if (n.classList.contains("leaving")) return; n.classList.add("leaving"); });
    const leaving = [...old.values()];
    grid.replaceChildren(...next, ...leaving, ...extra);
    setTimeout(() => leaving.forEach(n => n.remove()), 420);
  }
  function render() {
    const q = (msg && msg.value || "").trim().toLowerCase();
    let list = [], label, extra = [];
    if (q && !q.startsWith("/") && !q.startsWith("@")) {
      const words = q.split(/\s+/).filter(Boolean), hit = w => words.every(x => (w.search || "").includes(x));
      list = data.widgets.filter(hit).map((w, i) => [w, i, false]);
      const apps = data.apps.filter(hit); if (apps.length) extra = [chips(apps)];
      const n = list.length + apps.length;
      label = n ? `${n} on the board for “${q}” · send to ask Theta` : `Nothing on the board for “${q}” · send to ask Theta`;
    } else {
      const v = visible(), tasks = v.filter(isTask), rest = v.filter(w => !isTask(w)), imp = tasks.filter(w => w.important).length;
      const showT = moreOpen ? tasks : tasks.slice(0, TASKS_MAX);
      list = showT.map((w, i) => [w, i, i === 0]).concat(rest.map((w, i) => [w, showT.length + i, false]));
      if (tasks.length > showT.length) { const m = el("button", "bchip more", `+${tasks.length - showT.length} more to clear`); m.type = "button"; m.onclick = () => { moreOpen = true; render(); }; extra.push(m); }
      extra.push(chips(data.apps)); taps = 0; // a new look at the board
      const done = clearedToday();
      label = !tasks.length ? `All clear · just the world now${done ? ` · ${done} cleared today ✓` : ""}`
        : `${tasks.length} to clear` + (imp ? ` · ${imp} important` : "") + (done ? ` · ${done} cleared today ✓` : "");
      boardEl.classList.toggle("allclear", !tasks.length);
    }
    place(list, extra); title.textContent = label;
    allBtn.hidden = !!q; allBtn.textContent = showAll ? "Only new" : "Show all";
    const imp = data.widgets.filter(w => w.important).length, n = fresh().length;
    countEl.textContent = imp ? `${imp} important` : n ? `${n} new` : "Widgets"; openBtn.hidden = false;
    clearTimeout(seenTimer);
    if (!q && ST() && ST().docked()) seenTimer = setTimeout(() => { visible().forEach(w => { seen[w.id] = w.sig; }); put("theta:seen", seen); }, 2500);
  }
  // ---- cleared: a task widget that leaves because its thing got done counts, with a small toast
  const today = () => new Date().toDateString();
  function clearedToday() { const c = get("theta:cleared", {}); return c.day === today() ? c.n || 0 : 0; }
  function addCleared(names) { const c = get("theta:cleared", {}); const n = (c.day === today() ? c.n || 0 : 0) + names.length; put("theta:cleared", {day: today(), n}); }
  let toastEl = null, toastT = 0;
  function toast(text) {
    if (!toastEl) { toastEl = el("div", "btoast"); toastEl.setAttribute("role", "status"); document.body.append(toastEl); }
    toastEl.textContent = text; toastEl.classList.add("in"); clearTimeout(toastT); toastT = setTimeout(() => toastEl.classList.remove("in"), 2600);
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
  if (msg) { msg.addEventListener("focus", () => $("ticker").classList.add("held")); msg.addEventListener("blur", () => $("ticker").classList.remove("held")); }
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
      const before = new Map((data.widgets || []).filter(isTask).map(w => [w.id, w.title]));
      data = d; seen = get("theta:seen", {});
      if (!(ST() && ST().docked())) { shown = null; newIds = new Set(); moreOpen = false; }
      const gone = [...before].filter(([id]) => !d.widgets.some(w => w.id === id && isTask(w))).map(([, t]) => t); // dealt with: gone, or no longer a task
      if (gone.length && before.size) { addCleared(gone); toast("\u2713 Cleared: " + gone.join(", ")); }
      render(); tick();
    } catch (e) {}
  }
  // live: every 20 s while the board is up, every 2 min otherwise, at once after Theta answers or acts
  load(); setInterval(() => { if (!document.hidden && ST() && ST().docked()) load(); }, 20000);
  setInterval(() => { if (!document.hidden && !(ST() && ST().docked())) load(); }, 120000);
  let lastTheta = null;
  document.addEventListener("theta:thread", e => {
    const ms = (e.detail || []).filter(x => x.from === "theta"), m = ms[ms.length - 1];
    if (!m) return; if (lastTheta !== null && m.id !== lastTheta) setTimeout(load, 1200); lastTheta = m.id;
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });

  // a page asked for directly (/settings, /money...) opens here, in the sheet
  const want = new URLSearchParams(location.search).get("open");
  if (want && /^\/[A-Za-z0-9\/#?=&._-]*$/.test(want) && !want.startsWith("//")) {
    setTimeout(() => openSheet(want, want.replace(/^\//, "").split(/[#?]/)[0] || "Home"), 300);
    history.replaceState(null, "", location.pathname);
  }

  // ---- the terminal: when Theta makes a card (a table, a quiz, a doc, code, buttons to press), it shows
  // above everything. It shows a copy, so the message stays in the chat too; taps and typing in the copy are
  // passed to the real card (found by the message's id, since the chat re-draws), and the copy refreshes after.
  const term = $("term"), tbody = $("term-body");
  let termId = null, closed = get("theta:termClosed", null), firstThread = true;
  const CARD = ".quizcard,.doccard,.cfgcard,.codeblock,table,.msg-acts:not(.macts)"; // .macts is the copy/share footer every reply has
  const CTRL = "button,input,label,select,textarea,a";
  const realRow = () => document.querySelector(`#msgs .msg[data-id="${CSS.escape(String(termId))}"]`);
  function mirror(r) { if (r.querySelector(".caret")) return void setTimeout(() => { const x = realRow(); if (x) mirror(x); }, 300); // still typing: copy it once it's whole
    const c = r.cloneNode(true); c.removeAttribute("id"); c.querySelectorAll("[id]").forEach(n => n.removeAttribute("id")); tbody.replaceChildren(c); }
  function twin(e) { // the real control matching the one touched in the copy
    const copy = tbody.firstElementChild, real = realRow(); if (!copy || !real) return null;
    const t = e.target.closest(CTRL); if (!t || !copy.contains(t)) return null;
    const i = [...copy.querySelectorAll(CTRL)].indexOf(t); return i < 0 ? null : real.querySelectorAll(CTRL)[i] || null;
  }
  tbody.addEventListener("click", e => {
    const t = e.target.closest(CTRL), o = twin(e); if (!o) return;
    if (t.tagName === "A" && t.target === "_blank") return; // links open as they are
    if (/^(TEXTAREA|SELECT)$/.test(t.tagName) || (t.tagName === "INPUT" && !/^(radio|checkbox|button|submit)$/.test(t.type))) return;
    e.preventDefault(); o.click(); setTimeout(() => { const r = realRow(); if (r) mirror(r); }, 250);
  });
  tbody.addEventListener("input", e => { const o = twin(e); if (o && "value" in o) { o.value = e.target.value; o.dispatchEvent(new Event("input", {bubbles: true})); } });
  tbody.addEventListener("change", e => { const o = twin(e); if (o && "value" in o) { o.value = e.target.value; o.dispatchEvent(new Event("change", {bubbles: true})); } });
  document.addEventListener("theta:thread", () => setTimeout(() => {
    const rows = [...document.querySelectorAll("#msgs .msg:not(.mine)")].filter(r => r.querySelector(CARD));
    const r = rows[rows.length - 1], wasFirst = firstThread; firstThread = false;
    if (!r) return;
    const id = r.dataset.id || "", t = r.querySelector("time"), at = t ? Date.parse(t.dateTime) : Date.now();
    if (id === String(closed) || (wasFirst && Date.now() - at > 30 * 60e3)) return;
    if (id === termId && !term.hidden && tbody.contains(document.activeElement)) return; // you're typing in it: leave it be
    termId = id; mirror(r); term.hidden = false;
  }, 0));
  $("term-x").onclick = () => { term.hidden = true; closed = termId; put("theta:termClosed", termId); };
})();
"""


# ---- Spotlight, the entertainment background (2026-11-04): what's coming that you'd care about, as a picture
# that changes, with where it was found. Ranked: titles you follow (your library), then titles on topics you've
# opened on the board, then what's popular and soon. Release data is the hub's own (TMDB, RAWG, Jikan, the
# entertainment feeds); nothing is fetched here.
def spotlight(now=None, limit=12):
    now = now or datetime.now(hub_tz())
    likes = board_topics()
    items = []
    try:
        for x in releases(now.date()):
            if not x.get("image") or not str(x.get("url") or "").startswith("https://"):
                continue
            img = x["image"].replace("/t/p/w342/", "/t/p/w780/")
            days = (date.fromisoformat(x["date"]) - now.date()).days
            hit = sorted(w for w in topic_words(x["title"]) if likes.get(w, 0) >= .5)
            score = (100 if x.get("followed") else 0) + min(60, 25 * sum(likes.get(w, 0) for w in hit)) \
                + 4 * math.log10((x.get("pop") or 0) + 1) + (10 if days <= 30 else 0)
            why = ("In your library" if x.get("followed") else f"You've been reading about {hit[0]}" if hit else
                   "Coming soon" if days <= 30 else "Popular")
            items.append({"title": x["title"], "image": img, "kind": x["kind"], "date": x["date"], "days": days,
                          "url": x["url"], "site": urlparse(x["url"]).hostname.removeprefix("www."), "why": why, "score": score})
    except Exception as e:
        print(f"spotlight releases failed: {e!r}")
    try:
        for w in trending_windows()[:10]:
            img, url = str(w.get("image") or ""), str(w.get("href") or "")
            if not img.startswith("https://") or not url.startswith("https://"):
                continue
            title = (w.get("raw") or w.get("title") or "")[:120]
            hit = sorted(x for x in topic_words(title) if likes.get(x, 0) >= .5)
            items.append({"title": title, "image": img, "kind": "news", "date": "", "days": None, "url": url,
                          "site": urlparse(url).hostname.removeprefix("www."), "why": f"You've been reading about {hit[0]}" if hit else "Trending",
                          "score": 12 + min(60, 25 * sum(likes.get(x, 0) for x in hit))})
    except Exception as e:
        print(f"spotlight trending failed: {e!r}")
    items.sort(key=lambda x: -x["score"])
    seen, out = set(), []
    for x in items:
        k = x["title"].lower()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out[:limit]
