"""Home: smart stack, Today's check, settings cards, benchmark UI.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Smart stack: one widget slot on Home you swipe through, like the
# iPhone's. Cards come from stored data only (no slow fetches) and are
# ordered by how much they matter right now.
def stack_cards(now, todays, status, news, cards):
    out = []

    def add(score, kind, eyebrow, title, sub, href, tone=""):
        out.append({"score": score, "kind": kind, "eyebrow": eyebrow, "title": title, "sub": sub, "href": href, "tone": tone})
    t = now.timestamp()
    for r in reminders():  # due within the hour, overdue, or waiting to be marked done
        if r.get("pending") or r["at"] <= t + 3600:
            late = r["at"] <= t
            add(100 if late or r.get("pending") else 92, "remind", "Remi · reminder",
                r["what"], "Waiting for you to mark it done" if r.get("pending") else
                ("Due now" if late else f"At {_clock(datetime.fromtimestamp(r['at'], hub_tz()))}"), "/calendar#reminders", "warn")
    timed = [e for e in todays if not e["all_day"] and isinstance(e["start"], datetime) and e["end"] > now]
    if timed:
        e = timed[0]
        mins = (e["start"] - now).total_seconds() / 60
        add(95 if mins <= 120 else 70, "calendar", "Up next" if mins > 0 else "Happening now", e["title"],
            (f"{_clock(e['start'])}" + (f" · {e['location']}" if e.get("location") else "")
             + ((f" · in {int(mins)} min" if mins < 60 else f" · in {int(mins // 60)} h {int(mins % 60)} min")
                if 0 < mins < 600 else "")), "/calendar")
    elif todays:
        add(45, "calendar", "Today", todays[0]["title"], f"{len(todays)} on the calendar today", "/calendar")
    spent = sum(v["spent"] for v in status.values())
    budget = sum(v["budget"] or 0 for v in status.values())
    over = [(c, v) for c, v in status.items() if v["budget"] and v["spent"] >= v["budget"]]
    if over:
        c, v = max(over, key=lambda cv: cv[1]["spent"] / cv[1]["budget"])
        add(88, "money", "Glass · over budget", f"{c}: ${v['spent']:,.0f} of ${v['budget']:,.0f}",
            f"{len(over)} categor{'y' if len(over) == 1 else 'ies'} over this month", "/money", "bad")
    elif budget:
        share = spent / budget
        add(74 if share >= 0.9 else 30, "money", "Glass · this month", f"{share:.0%} of budget used",
            f"${spent:,.0f} of ${budget:,.0f}", "/money", "warn" if share >= 0.9 else "")
    breaking = [w for w in news if w.get("tag")]
    if breaking:
        add(84, "news", f"Breaking · {breaking[0]['source']}", breaking[0]["title"], "Tap to read", breaking[0].get("url") or "/#news", "bad")
    elif news:
        add(25, "news", f"Top story · {news[0]['source']}", news[0]["title"], f"{len(news)} stories from your outlets", "/#news")
    today = now.date().isoformat()
    out_today = [x for x in releases(now.date()) if x["date"] == today and x.get("followed")]
    if out_today:
        add(80, "release", "Out today", out_today[0]["title"], f"{RELEASE_KINDS[out_today[0]['kind']].rstrip('s').title()}"
            + (f" · +{len(out_today) - 1} more" if len(out_today) > 1 else ""), "/lenz")
    items, done = daily_items(), daily_done()
    left = [i for i in items if i["id"] not in done]
    if items:
        add(66 if left and now.hour >= 18 else 35 if left else 15, "daily", "Today's check",
            "All done" if not left else f"{len(left)} left: {left[0]['text']}",
            f"{daily_streak()}-day streak", "/#today", "warn" if left and now.hour >= 18 else "")
    lz = (cards or {}).get("lenz")
    if lz and t - lz.get("at", 0) < 6 * 3600:
        add(55, "watch", f"Lenz · {lz.get('source') or 'new'}", lz["title"], _first_line(lz.get("text", "")), lz.get("url") or "/lenz")
    return sorted(out, key=lambda c: -c["score"])


_STACK_ICONS = {"remind": "bell", "calendar": "calendar", "money": "money", "news": "news", "release": "play",
                "daily": "check", "watch": "play"}


def stack_html(cards):
    if not cards:
        return ""
    esc = html.escape

    def card(c):
        ext = c["href"].startswith("http")
        icon = ui_icon(_STACK_ICONS.get(c["kind"], "bolt")) if _STACK_ICONS.get(c["kind"]) in UI_ICONS else ""
        return (f'<a class="sc {c["tone"]}" href="{esc(c["href"])}"' + (' target="_blank" rel="noopener"' if ext else "")
                + f'><div class="sc-e">{icon}<span>{esc(c["eyebrow"])}</span></div><div class="sc-t">{esc(c["title"])}</div>'
                f'<div class="sc-s">{esc(c["sub"])}</div></a>')
    dots = "".join(f'<i{" class=on" if i == 0 else ""}></i>' for i in range(len(cards)))
    return (f'<section class="smart" aria-label="Smart stack, most important first"><div class="sc-track">'
            + "".join(card(c) for c in cards) + f'</div>' + (f'<div class="sc-dots" aria-hidden="true">{dots}</div>' if len(cards) > 1 else "")
            + '</section>')


# ---- Today's check: a short list of daily habits on Home (read the news,
# read a book or comic...). Ticks reset each day; a streak counts days with
# everything done; Remi nudges once in the evening if anything's left.
DAILY_DEFAULT = [{"id": "news", "text": "Read the news", "link": "/#news"},
                 {"id": "read", "text": "Read a book or comic", "link": "/lenz"}]
DAILY_NUDGE_TIME = os.environ.get("DAILY_NUDGE_TIME", "20:00")
_DAILY_LOCK = threading.Lock()


def daily_items():
    items = _meta_json("daily:items", None)
    return DAILY_DEFAULT if items is None else items


def daily_done(day=None):
    day = day or datetime.now(hub_tz()).date().isoformat()
    return set(_meta_json(f"daily:done:{day}", []))


def daily_streak(today=None):
    """Days in a row with everything ticked (today counts once it's done)."""
    today = today or datetime.now(hub_tz()).date()
    hist = _meta_json("daily:history", {})
    n, d = 0, today
    if hist.get(d.isoformat()) != "all":
        d -= timedelta(days=1)
    while hist.get(d.isoformat()) == "all":
        n += 1
        d -= timedelta(days=1)
    return n


def daily_toggle(item_id):
    today = datetime.now(hub_tz()).date().isoformat()
    with _DAILY_LOCK:
        done = daily_done(today)
        done.symmetric_difference_update({item_id})
        store().set_meta(f"daily:done:{today}", json.dumps(sorted(done)))
        ids = {i["id"] for i in daily_items()}
        hist = _meta_json("daily:history", {})
        hist[today] = "all" if ids and ids <= done else "some"
        store().set_meta("daily:history", json.dumps(dict(sorted(hist.items())[-400:])))
    return item_id in done


def daily_add(text):
    text = " ".join(str(text).split())[:80]
    if not text:
        raise ValueError("What's the habit?")
    with _DAILY_LOCK:
        items = list(daily_items())
        if len(items) >= 12:
            raise ValueError("Twelve is plenty for one day.")
        items.append({"id": f"d{int(time.time() * 1000) % 10**9}", "text": text})
        store().set_meta("daily:items", json.dumps(items))
    return items[-1]


def daily_remove(item_id):
    with _DAILY_LOCK:
        store().set_meta("daily:items", json.dumps([i for i in daily_items() if i["id"] != item_id]))


def daily_nudge(now=None):
    """From the tick: once a day after DAILY_NUDGE_TIME, Remi pushes what's left."""
    now = now or datetime.now(hub_tz())
    try:
        h, m = (int(x) for x in DAILY_NUDGE_TIME.split(":"))
    except ValueError:
        h, m = 20, 0
    today = now.date().isoformat()
    if (now.hour, now.minute) < (h, m) or store().get_meta("daily:nudged") == today:
        return None
    left = [i["text"] for i in daily_items() if i["id"] not in daily_done(today)]
    store().set_meta("daily:nudged", today)
    if not left:
        return None
    notify("Remi", "Still on today's check: " + ", ".join(left).lower() + ".", "/#today")
    return left


_DAILY_JS = r"""
(() => {
  const box = document.getElementById("today"); if (!box) return;
  const H = window.THETA_H, note = box.querySelector(".note");
  async function post(url, body) {
    const d = await (await fetch(url, {method: "POST", headers: H, body: JSON.stringify(body || {})})).json();
    if (!d.ok) throw new Error(d.error); return d;
  }
  box.addEventListener("change", async e => {
    const cb = e.target.closest("input[data-daily]"); if (!cb) return;
    try { const d = await post("/api/daily/toggle", {id: cb.dataset.daily}); box.querySelector(".streak").textContent = d.label; }
    catch (err) { cb.checked = !cb.checked; note.textContent = err.message; }
  });
  box.addEventListener("click", async e => {
    const x = e.target.closest("[data-daily-remove]"); if (!x) return;
    try { await post("/api/daily/remove", {id: x.dataset.dailyRemove}); x.closest("li").remove(); } catch (err) { note.textContent = err.message; }
  });
  const edit = box.querySelector("[data-daily-edit]");
  edit.onclick = () => { const on = box.classList.toggle("editing"); edit.textContent = on ? "Done" : "Edit"; };
  box.querySelector("form").onsubmit = async e => {
    e.preventDefault(); const inp = e.target.querySelector("input"), t = inp.value.trim(); if (!t) return;
    try { await post("/api/daily/add", {text: t}); location.reload(); } catch (err) { note.textContent = err.message; }
  };
})();
"""


def streak_label(n, all_done):
    if all_done and n:
        return f"All done · {n}-day streak"
    if all_done:
        return "All done today"
    return f"{n}-day streak" if n else "Start a streak"


def daily_card():
    items, done = daily_items(), daily_done()
    all_done = bool(items) and all(i["id"] in done for i in items)
    rows = "".join(
        f'<li><label class="dcheck"><input type="checkbox" data-daily="{html.escape(i["id"])}"{" checked" if i["id"] in done else ""}>'
        f'<span>{html.escape(i["text"])}</span></label>'
        + (f'<a class="muted small" href="{html.escape(i["link"])}"' + (' target="_blank" rel="noopener"' if i["link"].startswith("http") else "") + '>Open</a>' if i.get("link") else "")
        + f'<button type="button" class="dx" data-daily-remove="{html.escape(i["id"])}" aria-label="Remove {html.escape(i["text"])}">×</button></li>'
        for i in items)
    return (f'<section class="card stack daily" id="today" aria-label="Today\'s check"><div class="brow"><h2>Today\'s check</h2>'
            f'<span class="muted small"><span class="streak">{streak_label(daily_streak(), all_done)}</span> · '
            '<button type="button" class="linkbtn" data-daily-edit>Edit</button></span></div>'
            f'<ul class="dlist">{rows or "<li class=empty>Add a habit to check off each day.</li>"}</ul>'
            '<form class="dadd box"><input placeholder="Add a daily habit, like Stretch" aria-label="New daily habit" maxlength="80">'
            '<button class="btn small" type="submit">Add</button></form><p class="note"></p>'
            f'<script>{_DAILY_JS}</script></section>')


def home_page(headers):
    st = store()
    _fetch_feeds(list(dict.fromkeys(NEWS_FEEDS + ENTERTAINMENT_FEEDS + [u for us in SIDE_FEEDS.values() for u in us])))
    chat = st.list_chat(ALLCHAT_KEEP)
    shorts, images, cards = _meta_json("cards:short", {}), _meta_json("cards:img", {}), _meta_json("cards", {})
    crew = finish_windows(agent_windows(chat, cards), shorts, images)
    if ui_prefs(headers)[2] == "magazine":  # lead with the newest window that has a real photo
        photos = [w for w in crew if (w["image"] or "").startswith("http") and not w["fit"]]
        if photos:
            hero = max(photos, key=lambda w: w["at"] or 0)
            crew = [hero] + [w for w in crew if w is not hero]
    news = finish_windows(news_windows(), shorts, images)
    trend = finish_windows(trending_windows(), shorts, images)
    statuses = agent_statuses()
    now = datetime.now(hub_tz())
    hello = "Good morning" if 4 <= now.hour < 12 else "Good afternoon" if now.hour < 18 else "Good evening"
    month = now.strftime("%Y-%m")
    status = month_status(month)
    todays = []
    if calendar_linked():
        try:
            todays = [o for o in calendar_events(now.date(), now.date())]
        except Exception:
            todays = []
    swipe = lambda ws: "".join(win_html(w) for w in ws)
    attn = []
    for cat, v in sorted(status.items(), key=lambda kv: -kv[1]["spent"]):
        if v["budget"]:
            share = v["spent"] / v["budget"]
            if share >= 1:
                attn.append((f"{cat} is ${v['spent'] - v['budget']:,.2f} over its ${v['budget']:,.0f} budget", "/money"))
            elif share >= 0.9:
                attn.append((f"{cat} is at {share:.0%} of its ${v['budget']:,.0f} budget", "/money"))
    if todays:
        attn.append((f"{len(todays)} event{'s' if len(todays) != 1 else ''} today", "/calendar"))
    for a, err in _meta_json("round:failures", {}).items():
        attn.append((f"Last round failed for {AGENTS.get(a, {}).get('name', a)}: {str(err)[:80]}", "/diagnostics"))
    try:
        _f = watchdog_findings()
        _parts = []
        _h = sum(1 for sv, _ in _f if sv == "high")
        _w = sum(1 for sv, _ in _f if sv == "warn")
        _i = sum(1 for sv, _ in _f if sv == "info")
        if _h: _parts.append(f"{_h} need attention")
        if _w: _parts.append(f"{_w} to look at")
        if _i and not _parts: _parts.append(f"{_i} FYI")
        _qline = "All clear: QWERTY's checks flagged nothing." if not _f else " · ".join(_parts)
    except Exception:
        _qline = "QWERTY couldn't check right now."
    attention_html = (f'<section class="card attention"><h2>Needs attention</h2><ul>'
                      + "".join(f'<li><a href="{href}">{html.escape(text)}</a></li>' for text, href in attn)
                      + '</ul></section>' if attn else "")
    body = (
        f'<header class="top tight"><div><p class="eyebrow">{now:%A, %B} {now.day}</p><h1>{hello}</h1></div>'
        f'<button class="btn rr" type="button" data-run-round="round-status" aria-label="Run a round">{ui_icon("play")}'
        f'<span>Run a round</span></button></header><p class="note" id="round-status" style="margin:-8px 0 14px"></p>'
        + attention_html
        + stack_html(stack_cards(now, todays, status, news, cards))
        + daily_card() +
        f'<div class="sect"><h2>Your crew</h2><a href="/chat">Open chat →</a></div>'
        f'<section class="wins" aria-label="Agent windows">{"".join(win_html(w) for w in crew)}</section>'
        f'<div class="sect"><h2>Agents</h2><span class="muted small">Expand an agent for its controls.</span></div>'
        f'<details class="card stack" id="agent-lenz" style="margin-top:14px"><summary>Lenz — channels &amp; releases</summary>'
        '<ul class="list">'
        + (f'<li>YouTube: {len(LENZ_YOUTUBE)} channel(s)</li>' if LENZ_YOUTUBE else '<li>YouTube: not set</li>')
        + (f'<li>Reddit: {len(LENZ_SUBREDDITS)} subreddit(s)</li>' if LENZ_SUBREDDITS else '<li>Reddit: not set</li>')
        + (f'<li>Twitch: {len(LENZ_TWITCH)} channel(s)</li>' if LENZ_TWITCH else '<li>Twitch: not set</li>')
        + '</ul>'
        f'<p class="muted small">{"TMDB key set" if TMDB_API_KEY else "TMDB key not set"} · {len(releases())} upcoming in the calendar. Channels are set in Vercel → Environment Variables and need a redeploy.</p>'
        '<p><a href="/lenz">Open Lenz →</a> · <a href="#releases">Release calendar ↓</a></p></details>'
        f'<details class="card stack" id="agent-qwerty" style="margin-top:14px"><summary>QWERTY — security &amp; diagnostics</summary>'
        f'<p>{html.escape(_qline)}</p>'
        '<p><a href="/diagnostics#security">Open Security in Diagnostics →</a> · <a href="/diagnostics">Diagnostics →</a></p></details>'
        f'<details class="card stack" id="agent-mistral" style="margin-top:14px"><summary>Mistral — phone notifications</summary>'
        '<div><h2>Phone notifications</h2><p class="muted small">Mistral sends these: '
        'the morning digest, breaking news, budget alerts and birthdays. On iPhone, open Theta from its Home Screen icon.</p></div>'
        '<p><button class="btn" id="push-on" type="button">Turn on</button> <button class="btn ghost" id="push-test" '
        'type="button">Send a test</button></p><p class="note" id="push-status" style="white-space:pre-line"></p>'
        f'<script>{_PUSH_JS}</script></details>'
        f'<nav class="quickactions" aria-label="Quick actions"><a href="/chat">Chat</a><a href="/calendar">Calendar</a>'
        f'<a href="/money">Money</a><a href="/diagnostics">Diagnostics</a></nav>'
        f'<div class="sect" id="news"><h2>Top stories</h2><span class="muted small">{len(NEWS_FEEDS)} outlets, {NEWS_TOP} top + up to {NEWS_BREAKING_MAX} breaking</span></div>'
        + (f'<section class="wins swipe" aria-label="Top stories">{swipe(news)}</section>' if news else
           '<p class="empty">No headlines right now.</p>')
        + '<div class="sect"><h2>Watch &amp; listen</h2><a href="/agent/lenz">Lenz →</a></div>'
        + (f'<section class="wins swipe" aria-label="Trending">{swipe(trend)}</section>' if trend else
           '<p class="empty">Nothing trending right now.</p>')
        + release_strip()
        + '<footer class="foot">'
        + (f"<p>{TMDB_NOTICE}</p>" if TMDB_API_KEY else "")
        + ("<p>Storage: memory (not persistent). Connect Upstash Redis in Vercel and redeploy.</p>"
           if STORAGE_MODE.startswith("memory") else "")
        + "<p>Pictures come from each outlet's feed, TMDB, Apple Music and Wikipedia.</p></footer>")
    return page(headers, "Home", "/", body, statuses=statuses, chat=chat)


def chat_page(headers, query, head=False):
    """The chat. head=True: the Head page, which is the chat now too: Theta's
    rings, voice and Jarvis-style panels on top of the same thread and cards."""
    ch = query.get("ch", ["all"])[0]
    ch = ch if ch in CHANNEL_IDS else "all"
    c = CHANNEL_IDS[ch]
    statuses = agent_statuses()
    chans = "".join(
        f'<a href="/chat?ch={x["id"]}" class="{"on" if x["id"] == ch else ""}"><span class="hash">#</span>{html.escape(x["name"])}</a>'
        for x in CHANNELS)
    by_tier = []
    for tier in reversed(TIERS):
        rows = [a for a in statuses if a["bot_id"] in AGENTS and AGENTS[a["bot_id"]]["tier"] == tier]
        if rows:
            by_tier.append(f'<div class="label">{TIER_LABELS[tier]} — {sum(a["online"] for a in rows)}/{len(rows)}</div>' + "".join(
                f'<a class="mrow" href="/agent/{a["bot_id"]}"><span class="avw">{avatar_img(a["bot_id"], 34)}'
                f'<span class="dot{" on" if a["online"] else ""}"></span></span><span><b>{html.escape(a["name"])}</b>'
                f'<span class="muted">{html.escape(a["activity"])}</span></span></a>' for a in rows))
    agents = {a: {"name": v["name"], "color": AGENT_LOOKS.get(a, AGENT_LOOKS["hub"])[0],
                  "tier": TIER_LABELS[v["tier"]]} for a, v in AGENTS.items()}
    agents["hub"] = {"name": "Hub", "color": AGENT_LOOKS["hub"][0], "tier": ""}
    data = {"channel": ch, "channelNames": {x["id"]: x["name"] for x in CHANNELS}, "agents": agents,
            "to": query.get("to", [""])[0], "draft": (query.get("say", [""])[0] or "")[:300],
            "initial": allchat_view(80, ch)}
    body = (
        '<div class="chat">'
        f'<aside class="chans" aria-label="Channels"><div class="brand" style="padding-left:10px;font-size:18px">{APP_NAME} crew</div>'
        f'<div class="label">Channels</div>{chans}</aside>'
        '<section class="thread">' + (head_hud(headers) if head else "") +
        '<div class="msgs" id="msgs" role="log" aria-live="polite"></div>'
        '<form class="composer" id="chat-form"><ul id="chat-menu" role="listbox" hidden></ul>'
        '<div class="working" id="chat-working" role="status" aria-live="polite" hidden><div class="trail" id="chat-working-done"></div>'
        '<div class="wline"><span id="chat-working-av"></span><span class="wdots" aria-hidden="true"><i></i><i></i><i></i></span>'
        '<span id="chat-working-text"></span><span class="elapsed" id="chat-working-elapsed" aria-hidden="true"></span></div></div>'
        '<div class="attach" id="chat-attach" hidden></div>'
        f'<div class="box"><label class="btn ghost pick" aria-label="Attach an image">{ui_icon("photo")}'
        f'<input type="file" id="chat-file" accept="image/*,.pdf,.txt,.md" multiple hidden></label><textarea id="chat-msg" rows="1" placeholder="{"Talk or type to Theta" if head else "Message #" + html.escape(c["name"])}" '
        'aria-label="Message" aria-autocomplete="list" aria-controls="chat-menu"></textarea>'
        f'<button class="btn send" id="chat-send" aria-label="Send">{ui_icon("send")}</button></div>'
        '<div class="note" id="chat-status"></div></form></section>'
        f'<aside class="members glass" id="members" aria-label="Members">{"".join(by_tier)}</aside>'
        '<div class="scrim" id="scrim"></div></div>'
        + _json_script("HUB_MENU", menu_data()) + _json_script("HUB_CHAT", data)
        + f'<script src="/chat.js?v={_ASSET_V}" defer></script>' + (head_script(headers) if head else ""))
    if head:
        return page(headers, "Theta", "/head", body, "chatpage headchat", statuses)
    return page(headers, f"#{c['name']}", "/chat", body, "chatpage", statuses)


_LAYOUT_PICS = {
    "grid": '<rect x="2" y="2" width="26" height="18" rx="3"/><rect x="32" y="2" width="26" height="18" rx="3"/>'
            '<rect x="2" y="24" width="26" height="18" rx="3"/><rect x="32" y="24" width="26" height="18" rx="3"/>',
    "feed": '<rect x="10" y="2" width="40" height="24" rx="3"/><rect x="10" y="30" width="40" height="12" rx="3"/>',
    "magazine": '<rect x="2" y="2" width="56" height="22" rx="3"/><rect x="2" y="28" width="17" height="14" rx="3"/>'
                '<rect x="22" y="28" width="17" height="14" rx="3"/><rect x="42" y="28" width="16" height="14" rx="3"/>',
    "compact": '<rect x="2" y="3" width="10" height="10" rx="2"/><rect x="16" y="6" width="40" height="4" rx="2"/>'
               '<rect x="2" y="17" width="10" height="10" rx="2"/><rect x="16" y="20" width="34" height="4" rx="2"/>'
               '<rect x="2" y="31" width="10" height="10" rx="2"/><rect x="16" y="34" width="38" height="4" rx="2"/>',
}

_BENCH_JS = r"""
(() => {
  const H = window.THETA_H, out = document.getElementById("bench-out"), note = document.getElementById("bench-note");
  const btn = document.getElementById("bench-run");
  if (!btn) return;
  const el = (tag, text, style) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (style) e.style.cssText = style; return e; };
  const DID = {plain: "answered", escalate: "handed to Theta", search: "searched", remind: "set a reminder"};
  const median = xs => { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.floor((s.length - 1) / 2)] : 0; };
  function render(d) {
    if (!d || !d.rows) { out.replaceChildren(el("p", "No run yet.", "color:var(--muted)")); return; }
    const modes = d.modes || [["on", "Thinking on"], ["off", "Thinking off"]];
    const sum = el("table"); sum.className = "tbl";
    const sh = el("tr"); ["", "Typical time", "Did the right thing", "Words written (tokens)", "Read from cache", "Cost"].forEach(t => sh.append(el("th", t)));
    sum.append(sh);
    for (const [m, label] of modes) {
      const rs = d.rows.filter(r => r.mode === m), ok = rs.filter(r => r.ok).length;
      const tr = el("tr");
      tr.append(el("td", label, "font-weight:650"), el("td", median(rs.map(r => r.secs)).toFixed(1) + " s"),
                el("td", ok + " of " + rs.length, "font-weight:700;color:" + (ok === rs.length ? "var(--good)" : "var(--bad)")),
                el("td", String(rs.reduce((a, r) => a + (r.out || 0), 0))),
                el("td", String(rs.reduce((a, r) => a + (r.cache_read || 0), 0))),
                el("td", "$" + rs.reduce((a, r) => a + (r.usd || 0), 0).toFixed(4)));
      sum.append(tr);
    }
    const det = el("table"); det.className = "tbl";
    const dh = el("tr"); ["Message", "Should", ...modes.map(m => m[1])].forEach(t => dh.append(el("th", t)));
    det.append(dh);
    const qs = [...new Set(d.rows.map(r => r.q))];
    for (const q of qs) {
      const tr = el("tr"), first = d.rows.find(r => r.q === q);
      tr.append(el("td", q), el("td", first.about, "color:var(--muted)"));
      for (const [m] of modes) {
        const r = d.rows.find(x => x.q === q && x.mode === m), td = el("td");
        if (!r) { tr.append(td); continue; }
        td.append(el("div", (r.ok ? "✓ " : "✗ ") + (r.error ? "failed" : (DID[r.did] || "used " + r.did)) + " · " + r.secs + " s",
                      "font-weight:650;color:" + (r.ok ? "var(--good)" : "var(--bad)")));
        const more = el("details"), sm = el("summary", "Reply"); more.append(sm, el("p", r.error || r.reply, "white-space:pre-wrap;font-size:13px"));
        td.append(more); tr.append(td);
      }
      det.append(tr);
    }
    const w1 = el("div"), w2 = el("div"); w1.className = w2.className = "scrollx"; w1.append(sum); w2.append(det);
    out.replaceChildren(el("p", d.model + ", effort " + d.effort + " · run " + new Date(d.at * 1000).toLocaleString() + " · total $" + d.usd.toFixed(4), "color:var(--muted);font-size:13px"), w1, w2);
  }
  async function load() {
    try { const d = await (await fetch("/api/bench", {headers: H})).json(); if (d.ok) render(d.rows ? d : null); } catch (e) {}
  }
  btn.onclick = async () => {
    btn.disabled = true; note.textContent = "Running... about 20 seconds (up to a minute with your PC).";
    try {
      const d = await (await fetch("/api/bench", {method: "POST", headers: H, body: "{}"})).json();
      if (!d.ok) throw new Error(d.error);
      note.textContent = ""; render(d);
    } catch (err) { note.textContent = "Couldn't run it: " + err.message; }
    btn.disabled = false;
  };
  load();
})();
"""

def security_rows():
    try:
        findings = watchdog_findings()
    except Exception as e:
        return f'<li class="empty">QWERTY couldn\'t check right now: {html.escape(str(e)[:120])}</li>'
    label = {"high": ("Fix now", "var(--bad)"), "warn": ("Look at", "var(--warn)"), "info": ("FYI", "var(--muted)")}
    return "".join(
        f'<li><span class="chip" style="color:{label[sv][1]};border-color:currentColor">{label[sv][0]}</span> {html.escape(t)}</li>'
        for sv, t in findings) or '<li>All clear: QWERTY\'s checks flagged nothing.</li>'
