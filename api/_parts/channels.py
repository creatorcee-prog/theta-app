"""Lenz's channels, the request router.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Lenz's channels: YouTube uploads, subreddits and Twitch, checked from
# the 5-minute tick (every LENZ_FEEDS_MINUTES) so news lands quickly.
# YouTube channels and Twitch going live are pushed; subreddits get a daily
# digest of their top posts, and any post naming something you follow is
# pushed right away.
def _yt_entry(c):
    """A channel from LENZ_YOUTUBE: a UC... id, an @handle, or a channel link
    copied from YouTube (youtube.com/@name or youtube.com/channel/UC...)."""
    c = c.strip()
    m = re.search(r"youtube\.com/(?:channel/(UC[\w-]{20,})|(@[\w.-]+))", c)
    return (m.group(1) or m.group(2)) if m else c


LENZ_YOUTUBE = [_yt_entry(c) for c in os.environ.get("LENZ_YOUTUBE", "").split(",") if c.strip()]  # UC... ids, @handles or links
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")  # only to turn @handles into channel ids
LENZ_SUBREDDITS = [c.strip().removeprefix("r/") for c in os.environ.get("LENZ_SUBREDDITS", "").split(",") if c.strip()]
LENZ_TWITCH = [c.strip().lower() for c in os.environ.get("LENZ_TWITCH", "").split(",") if c.strip()]
TWITCH_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET", "")
LENZ_FEEDS_MINUTES = int(os.environ.get("LENZ_FEEDS_MINUTES", "10"))
YOUTUBE_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id="
REDDIT_BASE = "https://www.reddit.com"
TWITCH_API = "https://api.twitch.tv/helix"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"


def lenz_feeds_on():
    return bool(LENZ_YOUTUBE or LENZ_SUBREDDITS or (LENZ_TWITCH and TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET))


def youtube_channel_ids():
    """UC... ids for LENZ_YOUTUBE; @handles are looked up once (YOUTUBE_API_KEY)."""
    known = _meta_json("lenz:yt:ids", {})
    out, changed = [], False
    for c in LENZ_YOUTUBE:
        if c.startswith("UC"):
            out.append(c)
        elif c in known:
            out.append(known[c])
        elif YOUTUBE_API_KEY:
            try:
                items = _get_json("https://www.googleapis.com/youtube/v3/channels?" + urlencode(
                    {"part": "id", "forHandle": c if c.startswith("@") else "@" + c, "key": YOUTUBE_API_KEY})).get("items") or []
            except Exception:
                items = []
            if items:
                known[c] = items[0]["id"]
                out.append(items[0]["id"])
                changed = True
    if changed:
        store().set_meta("lenz:yt:ids", json.dumps(known))
    return out


def youtube_uploads():
    ids = youtube_channel_ids()
    out = []
    for cid, items in zip(ids, _fetch_feeds_with(lambda c: _feed_now(YOUTUBE_FEED + c), ids)):
        for it in items[:5]:
            vid = re.search(r"[?&]v=([\w-]{6,})", it["url"])
            out.append(dict(it, kind="youtube", channel=it.get("source") or cid,
                            image=it.get("image") or (f"https://i.ytimg.com/vi/{vid.group(1)}/hqdefault.jpg" if vid else None)))
    return out


def _feed_now(url, ua=None):
    """A feed fetched fresh (no widget cache): these drive pushes."""
    try:
        if ua:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": ua}), timeout=6) as resp:
                return _parse_rss(resp.read())
        return _parse_rss(_fetch_url(url))
    except Exception:
        return []


def subreddit_top(sub, limit=3):
    items = _feed_now(f"{REDDIT_BASE}/r/{quote(sub)}/top/.rss?t=day&limit={limit}", ua=WIKI_UA)  # Reddit wants a descriptive agent
    return [dict(it, kind="reddit", sub=sub) for it in items[:limit]]


def _twitch_token():
    tok = _meta_json("lenz:twitch:token", {})
    if tok.get("exp", 0) > time.time() + 60:
        return tok["token"]
    req = urllib.request.Request(TWITCH_TOKEN_URL, data=urlencode({"client_id": TWITCH_CLIENT_ID, "client_secret": TWITCH_CLIENT_SECRET,
                                                                  "grant_type": "client_credentials"}).encode())
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            d = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise LLMError(f"Twitch sign-in returned {e.code}: check TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise LLMError(f"Twitch unreachable: {e!r}")
    store().set_meta("lenz:twitch:token", json.dumps({"token": d["access_token"], "exp": time.time() + int(d.get("expires_in", 3600))}))
    return d["access_token"]


def twitch_live():
    """Which LENZ_TWITCH channels are live now: {login: stream}."""
    if not (LENZ_TWITCH and TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET):
        return {}
    url = TWITCH_API + "/streams?" + urlencode([("user_login", c) for c in LENZ_TWITCH[:100]] + [("first", "100")])
    try:
        d = _get_json(url, {"Client-Id": TWITCH_CLIENT_ID, "Authorization": f"Bearer {_twitch_token()}"})
    except urllib.error.HTTPError as e:
        if e.code == 401:
            store().set_meta("lenz:twitch:token", "{}")
        raise LLMError(f"Twitch returned {e.code}")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise LLMError(f"Twitch unreachable: {e!r}")
    out = {}
    for st in d.get("data", []):
        tags = [str(t).lower() for t in st.get("tags") or []]
        out[st["user_login"].lower()] = {
            "name": st.get("user_name") or st["user_login"], "title": st.get("title", ""), "game": st.get("game_name", ""),
            "viewers": st.get("viewer_count", 0), "url": f"https://www.twitch.tv/{st['user_login']}",
            "drops": any("drops" in t for t in tags),
            "image": (st.get("thumbnail_url") or "").replace("{width}", "640").replace("{height}", "360") or None}
    return out


def _mentions_followed(title):
    t = _norm_title(title)
    for it in library():
        if it["status"] in ("current", "waiting", "paused", "queue") or it.get("beloved"):
            if any(k and k in t for k in _follow_keys(it)):
                return it["title"]
    return None


def lenz_feeds_check(now=None, force=False):
    """From the tick: new uploads, streams going live, and subreddit posts
    about what you follow. Posts in #screen and pushes; returns what it did."""
    now = now or time.time()
    st = store()
    if not lenz_feeds_on() or (not force and now - float(st.get_meta("lenz:feeds:at") or 0) < LENZ_FEEDS_MINUTES * 60):
        return []
    st.set_meta("lenz:feeds:at", str(now))
    did = []
    first_run = st.get_meta("lenz:feeds:primed") != "1"  # don't announce a backlog the first time
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_yt = ex.submit(youtube_uploads) if LENZ_YOUTUBE else None
        f_tw = ex.submit(twitch_live)
        f_rd = ex.submit(lambda: [x for sub in LENZ_SUBREDDITS for x in subreddit_top(sub, 5)]) if LENZ_SUBREDDITS else None
        uploads = f_yt.result(timeout=20) if f_yt else []
        try:
            live, tw_err = f_tw.result(timeout=20), None
        except LLMError as e:
            live, tw_err = None, str(e)
        posts = f_rd.result(timeout=20) if f_rd else []
    seen = _seen("lenz:yt")
    fresh = [u for u in uploads if u["url"] not in seen and (not u.get("published") or now - u["published"] < 3 * 86400)]
    for u in fresh:
        _mark_seen("lenz:yt", u["url"])
    if fresh and not first_run:
        st.add_chat("lenz", "New on YouTube:\n" + "\n".join(f"- **{u['channel']}**: {u['title']}\n  {u['url']}" for u in fresh[:5]),
                    channel="screen")
        save_card("lenz", fresh[0]["title"], f"New from {fresh[0]['channel']}", fresh[0].get("image"), fresh[0]["url"], "YouTube")
        notify("Lenz", f"{fresh[0]['channel']} posted: {fresh[0]['title']}" + (f" (+{len(fresh) - 1} more)" if len(fresh) > 1 else ""),
               fresh[0]["url"])
        did.append(f"{len(fresh)} new video{'s' if len(fresh) != 1 else ''}")
    if live is not None:
        was = set(_meta_json("lenz:twitch:live", []))
        went = [s for login, s in live.items() if login not in was]
        st.set_meta("lenz:twitch:live", json.dumps(sorted(live)))
        if went and not first_run:
            st.add_chat("lenz", "Live on Twitch:\n" + "\n".join(
                f"- **{s['name']}**: {s['title']}" + (f" ({s['game']})" if s["game"] else "") + (" · drops on" if s["drops"] else "")
                + f"\n  {s['url']}" for s in went), channel="screen")
            s0 = went[0]
            notify("Lenz", f"{s0['name']} is live" + (f" playing {s0['game']}" if s0["game"] else "") + (" (drops on)" if s0["drops"] else ""),
                   s0["url"])
            did.append(f"{len(went)} went live")
    elif tw_err:
        did.append(f"Twitch: {tw_err[:60]}")
    seen_r = _seen("lenz:reddit")
    hot = [(p, _mentions_followed(p["title"])) for p in posts if p["url"] not in seen_r]
    hot = [(p, f) for p, f in hot if f]
    for p, _ in hot:
        _mark_seen("lenz:reddit", p["url"])
    if hot and not first_run:
        st.add_chat("lenz", "On Reddit about what you follow:\n" + "\n".join(
            f"- **{f}** (r/{p['sub']}): {p['title']}\n  {p['url']}" for p, f in hot[:5]), channel="screen")
        notify("Lenz", f"r/{hot[0][0]['sub']} on {hot[0][1]}: {hot[0][0]['title']}", hot[0][0]["url"])
        did.append(f"{len(hot)} Reddit post{'s' if len(hot) != 1 else ''} about your list")
    if first_run:
        st.set_meta("lenz:feeds:primed", "1")
        did.append("started watching your channels")
    return did


def subreddit_digest(today):
    """Lenz's round, once a day: the top posts from each of your subreddits."""
    if not LENZ_SUBREDDITS or store().get_meta("lenz:reddit:day") == today.isoformat():
        return None
    store().set_meta("lenz:reddit:day", today.isoformat())
    groups = [(sub, subreddit_top(sub)) for sub in LENZ_SUBREDDITS]
    lines = [f"**r/{sub}**\n" + "\n".join(f"- {p['title']}\n  {p['url']}" for p in posts) for sub, posts in groups if posts]
    if not lines:
        return "Reddit gave nothing back (it sometimes blocks servers)"
    store().add_chat("lenz", "Today's top on your subreddits:\n\n" + "\n\n".join(lines), channel="screen")
    return f"posted the subreddit digest ({len(lines)} subs)"


def lenz_page(headers):
    lib = library()
    taste = taste_profile(lib)
    report = next((m["text"] for m in reversed(store().list_chat(ALLCHAT_KEEP))
                   if m["from"] == "lenz" and m["text"].startswith("Your week in media")), "")
    try:
        news = [{k: n[k] for k in ("title", "url", "source", "about")} for n in followed_news()]
    except Exception:
        news = []
    keep = ("id", "title", "kind", "status", "progress", "with", "note", "times", "rank", "tier", "group",
            "rating", "beloved", "image", "done_at")
    data = {"items": [{k: x.get(k) for k in keep} for x in lib], "kinds": KIND_LABELS, "taste": taste,
            "plural": {"game": "Games", "anime": "Anime", "show": "TV", "movie": "Movies", "manhwa": "Manhwa",
                       "web novel": "Web novels", "book": "Books", "comic": "Comics", "musical": "Musicals", "manga": "Manga"},
            "report": report, "news": news,
            "colors": {"anime": ("#f472b6", "#7c3aed"), "show": ("#38bdf8", "#1d4ed8"), "movie": ("#fbbf24", "#ea580c"),
                       "game": ("#34d399", "#0f766e"), "manga": ("#f87171", "#9f1239"), "manhwa": ("#fb7185", "#be123c"),
                       "web novel": ("#a78bfa", "#4c1d95"), "book": ("#a3a3a3", "#44403c"), "comic": ("#facc15", "#b45309"),
                       "musical": ("#f0abfc", "#a21caf")}}
    n = {s: sum(1 for x in lib if x["status"] == s) for s in STATUSES}
    rated = sum(1 for x in lib if x["status"] == "done" and x.get("rating"))
    tabs = [("now", "Now", True), ("next", "Up next", True), ("waiting", "Waiting", True), ("done", "Finished", True),
            ("top", "Top", False), ("taste", "Taste", False), ("news", "News", False)]
    kinds = [("all", "All"), ("anime", "Anime"), ("tv", "TV"), ("movies", "Movies"), ("games", "Games"), ("reading", "Reading")]
    opts = "".join(f'<option value="{k}">{v}</option>' for k, v in KIND_LABELS.items())
    sts = "".join(f'<option value="{k}">{v}</option>' for k, v in (("queue", "Up next"), ("current", "On it now"),
                                                                    ("done", "Finished"), ("waiting", "Waiting")))
    body = (
        f'<header class="top"><div class="hero">{avatar_img("lenz", 56)}<div><p class="eyebrow">Lenz · your library</p>'
        f'<h1>Entertainment</h1></div></div><a class="btn ghost" href="/chat?ch=screen&amp;to=lenz">{ui_icon("chat")}Ask Lenz</a></header>'
        '<div class="kpis">'
        + kpi_html(str(n["current"]), "On the go", "watching, playing, reading", icon="play")
        + kpi_html(str(n["queue"]), "Up next", f"{n['waiting']} waiting on new seasons", icon="calendar")
        + kpi_html(f"{rated}/{n['done']}" if n["done"] else "0", "Finished, rated", "rate the rest", rated / n["done"] if n["done"] else 0)
        + kpi_html(str(sum(1 for x in lib if x.get('beloved'))), "Most beloved",
                   next((x["title"] for x in lib if x.get("beloved")), "mark favorites in your log"), icon="bolt")
        + '</div>' + release_strip()
        + '<div class="chips" style="margin:16px 0 8px">' + "".join(f'<button type="button" class="chip" data-kind="{k}">{v}</button>' for k, v in kinds) + "</div>"
        + '<div class="seg ltabs" role="tablist">' + "".join(
            f'<button type="button" role="tab" data-tab="{k}">{v}{" <i></i>" if c else ""}</button>' for k, v, c in tabs) + "</div>"
        + '<p class="note" id="lenz-note"></p><div id="lenz-view"></div>'
        + '<section class="card stack" style="margin-top:18px"><h2>Log something</h2>'
          f'<form id="lenz-add" class="stack"><input id="lenz-title" class="field" placeholder="Title" aria-label="Title">'
          f'<div style="display:flex;gap:8px;flex-wrap:wrap"><select id="lenz-kind" class="field" aria-label="Kind">{opts}</select>'
          f'<select id="lenz-status" class="field" aria-label="Status">{sts}</select>'
          '<button class="btn" type="submit">Add</button></div></form></section>'
        + '<section class="card stack" style="margin-top:14px"><h2>Bring in your log</h2>'
          '<p class="muted small">Paste the text of your entertainment log (in Google Docs: select all, copy) and Lenz '
          'sorts it: Current, In Queue, Waiting, Rankings and type codes like (AN) or (G). Run it again any time; your '
          'ratings stay. Or have Lenz re-read it every day: share the doc "anyone with the link can view" and set '
          '<code>LENZ_DOC_URL</code> in Vercel. For MyAnimeList, set <code>MAL_CLIENT_ID</code> (myanimelist.net/apiconfig) '
          'and <code>MAL_USERNAME</code>; your list must be public.</p>'
          '<textarea id="lenz-paste" class="field" rows="5" placeholder="Paste your log here"></textarea>'
          '<p><button class="btn" type="button" id="lenz-import">Import</button> <span class="note" id="lenz-import-note"></span></p></section>'
        + _json_script("LENZ", data) + f"<script>{_LENZ_JS}</script>")
    return page(headers, "Lenz", "", body)


def agent_page(headers, agent):
    v = AGENTS[agent]
    st_row = next((a for a in agent_statuses() if a["bot_id"] == agent), None)
    win = finish_windows([w for w in agent_windows() if w["agent"] == agent])
    posts = [m for m in reversed(store().list_chat(ALLCHAT_KEEP)) if m["from"] == agent][:8]
    post_html = "".join(
        f'<div class="post"><div class="meta"><time>{html.escape(m["at"])} UTC</time></div>'
        f'<div class="text">{html.escape(m["text"])}</div>'
        + (f'<img class="att" src="{html.escape(m["image"])}" alt="">' if m.get("image") else "") + "</div>"
        for m in posts) or '<p class="empty">Nothing posted yet.</p>'
    persona = "".join(f'<span class="chip">{html.escape(k)}</span>' for k in PERSONAS.get(agent, []))
    extra = ""
    if agent == "james":
        fit = next(iter(store().list_fitness(1)), None)
        if fit and isinstance(fit.get("summary"), dict):
            extra += ('<section class="card stack" style="margin-bottom:14px"><h2>Health summary</h2><dl class="kv">' + "".join(
                f"<dt>{html.escape(str(k))}</dt><dd>{html.escape(str(v))}</dd>" for k, v in fit["summary"].items())
                + f'</dl><p class="muted small">From {html.escape(display_name(fit["bot_id"]))} at '
                f'{html.escape(fit["created_at"])} UTC</p></section>')
        j = james_summary()
        extra += (f'<section class="card stack"><h2>Training</h2><div class="text">{html.escape(j.get("summary") or "")}</div>'
                 + (f'<p><a href="{html.escape(FITNESS_APP_URL)}">Open Garage Gym →</a></p>' if FITNESS_APP_URL else "")
                 + "</section>") if j else ""
    ch = home_channel(agent)
    online = bool(st_row and st_row["online"])
    body = (
        f'<header class="top"><div class="hero"><span class="avw">{avatar_img(agent, 76)}<span class="dot{" on" if online else ""}"></span></span>'
        f'<div><p class="eyebrow">{TIER_LABELS[v["tier"]]}{" · " + html.escape(v["home"]) if v.get("home") else ""}</p>'
        f'<h1>{html.escape(v["name"])}</h1><p class="muted small">{html.escape(st_row["activity"] if st_row else "offline")}</p></div></div>'
        f'<a class="btn" href="/chat?ch={ch}&amp;to={agent}">{ui_icon("chat")}Message {html.escape(v["name"])}</a></header>'
        + (reminders_card() if agent == "remi" else "")
        + '<div class="grid2">'
        f'<section class="card stack"><h2>Latest</h2><div class="wins" style="grid-template-columns:minmax(0,1fr)">{"".join(win_html(w) for w in win)}</div></section>'
        '<section class="card stack"><h2>About</h2>'
        f'<dl class="kv"><dt>Job</dt><dd>{html.escape(v["role"])}</dd><dt>Can</dt><dd>{html.escape(ABILITIES.get(agent, "chat"))}</dd>'
        f'<dt>Model</dt><dd><code>{html.escape(agent_model(agent))}</code></dd><dt>Channel</dt><dd><a href="/chat?ch={ch}">#{CHANNEL_IDS[ch]["name"]}</a></dd></dl>'
        + (f'<div><h3>Persona</h3><div class="chips" style="margin-top:6px">{persona}</div></div>' if persona else "")
        + f'</section></div>{extra}<section class="card" style="margin-top:14px"><h2>Recent posts</h2>{post_html}</section>')
    return page(headers, v["name"], "", body)


_REMINDERS_JS = r"""
(() => {
  const H = window.THETA_H, out = document.getElementById("rem-status");
  async function post(url, body) {
    const d = await (await fetch(url, {method: "POST", headers: H, body: JSON.stringify(body || {})})).json();
    if (!d.ok) throw new Error(d.error);
    return d;
  }
  document.getElementById("rem-form").onsubmit = async e => {
    e.preventDefault();
    const box = document.getElementById("rem-text"), text = box.value.trim();
    if (!text) return;
    out.textContent = "Setting it...";
    try { const d = await post("/api/reminders", {text}); out.textContent = "Set: " + d.line; box.value = ""; setTimeout(() => location.reload(), 900); }
    catch (err) { out.textContent = err.message; }
  };
  document.querySelectorAll("[data-rem]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    try { await post("/api/reminders/" + b.dataset.rem + "/" + b.dataset.act); b.closest("li").remove(); }
    catch (err) { out.textContent = err.message; b.disabled = false; }
  });
})();
"""


def reminders_card():
    rows = "".join(
        f'<li><div class="brow" style="align-items:center"><span>{html.escape(r["what"])}</span><span style="display:flex;gap:6px">'
        + (f'<button class="btn small" type="button" data-rem="{r["id"]}" data-act="done">Done</button>' if r.get("pending") else "")
        + f'<button class="btn ghost small" type="button" data-rem="{r["id"]}" data-act="delete" aria-label="Remove {html.escape(r["what"])}">Remove</button>'
        f'</span></div><div class="muted small">{html.escape(reminder_line(r).split(": ", 1)[1])}</div></li>'
        for r in reminders())
    return (f'<section class="card stack" id="reminders" style="margin-bottom:14px"><div><h2>Reminders</h2>'
            '<p class="muted small">Remi sends these to your phone. Say it like you would to her: '
            '"8am every day take my meds until done", "in 20 min check the oven", "fri 6pm pay rent weekly". '
            '"Until done" keeps nudging every 15 minutes until you tap Done (or tell Remi "done").</p></div>'
            '<form id="rem-form" class="box" style="padding:5px 5px 5px 14px"><input id="rem-text" '
            'placeholder="8am every day take my meds until done" aria-label="New reminder" '
            'style="flex:1;border:0;background:transparent;outline:none;padding:8px 0;min-width:0">'
            '<button class="btn small" type="submit">Add</button></form><p class="note" id="rem-status"></p>'
            f'<ul class="list">{rows or "<li class=empty>No reminders yet.</li>"}</ul></section>'
            f"<script>{_REMINDERS_JS}</script>")


def calendar_page(headers, query):
    """Remi's tab: a month grid plus the same month as a day-by-day list."""
    tz = hub_tz()
    today = datetime.now(tz).date()
    try:
        y, m = (int(x) for x in query.get("month", [""])[0].split("-"))
        first = date(y, m, 1)
    except ValueError:
        first = today.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    prev = (first - timedelta(days=1)).replace(day=1)
    head = (f'<header class="top"><div class="hero">{avatar_img("remi", 56)}<div><p class="eyebrow">Remi\'s calendar</p>'
            f'<h1>{first:%B %Y}</h1></div></div><div class="monthnav"><a class="btn ghost small" href="/calendar?month={prev:%Y-%m}">'
            f'← {prev:%b}</a><a class="btn ghost small" href="/calendar">Today</a><a class="btn ghost small" '
            f'href="/calendar?month={nxt:%Y-%m}">{nxt:%b} →</a></div></header>')
    head += reminders_card()
    if not calendar_linked():
        return page(headers, "Calendar", "/calendar", head + (
            '<section class="card"><h2>No calendar linked yet</h2><p>In Google Calendar on a computer: Settings → '
            'your calendar → <b>Integrate calendar</b> → copy <b>Secret address in iCal format</b>. In Vercel, set '
            '<code>REMI_CALENDAR_URLS</code> to it (comma-separate several) and redeploy. Treat it like a password.</p></section>'))
    grid_start = first - timedelta(days=(first.weekday() + 1) % 7)  # Sunday
    grid_end = grid_start + timedelta(days=41)
    occ = calendar_events(grid_start, grid_end)
    by_day = {}
    for o in occ:
        d0 = o["start"] if o["all_day"] else o["start"].date()
        d1 = (o["end"] - timedelta(days=1)) if o["all_day"] else o["end"].date()
        d = max(d0, grid_start)
        while d <= max(d0, d1) and d <= grid_end:
            by_day.setdefault(d, []).append(o)
            d += timedelta(days=1)
    rows = []
    for w in range(6):
        cells = []
        for i in range(7):
            d = grid_start + timedelta(days=w * 7 + i)
            items = by_day.get(d, [])
            evs = "".join(
                f"<div class=\"e{' b' if o['birthday'] else ''}\">"
                f"{'' if o['all_day'] else html.escape(_clock(o['start'])) + ' '}{html.escape(o['title'])}</div>"
                for o in items[:3])
            more = f"<div>+{len(items) - 3} more</div>" if len(items) > 3 else ""
            cls = " ".join(c for c in ("out" if d.month != first.month else "",
                                       "today" if d == today else "") if c)
            cells.append(f"<td class=\"{cls}\"><div class=\"n\">{d.day}</div>{evs}{more}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    listing = []
    d = first
    while d < nxt:
        items = by_day.get(d, [])
        if items:
            listing.append(f"<div class=\"day\">{d:%A %B} {d.day}</div><ul class=\"list\">" + "".join(
                f"<li>{html.escape(occurrence_text(o))}"
                f"{' <span class=chip>birthday</span>' if o['birthday'] else ''}</li>" for o in items) + "</ul>")
        d += timedelta(days=1)
    body = head + (
        "<section class=\"card scrollx\" style=\"padding:10px\"><table class=\"cal\"><tr>"
        + "".join(f"<th>{d}</th>" for d in ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"))
        + "</tr>" + "".join(rows) + "</table></section>"
        + f"<section class=\"card\" style=\"margin-top:14px\">{''.join(listing) or '<p class=empty>Nothing scheduled this month.</p>'}</section>"
        + f"<p class=\"foot\">Times in {html.escape(HUB_TIMEZONE)}. From your Google Calendar "
          "(read-only), refreshed every 10 minutes.</p>")
    return page(headers, "Calendar", "/calendar", body)



def _limit(query, default):
    """Parse ?limit=; None means invalid (not an int in 1..100)."""
    try:
        n = int(query.get("limit", [str(default)])[0])
    except ValueError:
        return None
    return n if 1 <= n <= 100 else None


def handle(method, path, query, headers, body):
    """Returns (status, content_type, body_bytes). `query` maps names
    to lists of values; `headers` maps lowercased names to values."""
    if method == "POST":
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            return _json(400, {"ok": False, "error": "bad json"})

        if path == "/api/report":
            bot_id, event_type = data.get("bot_id"), data.get("event_type")
            if not bot_id or not event_type or not _auth_bot(bot_id, headers):
                return _json(401, {"ok": False, "error": "bad bot_id or key"})
            store().add_report(bot_id, event_type, data.get("payload", {}))
            post_event(bot_id, f"{display_name(bot_id)} reported {event_type}: "
                               f"{_gist(data.get('payload', {}))}")
            return _json(200, {"ok": True})

        if path == "/api/escalate":
            bot_id, issue = data.get("bot_id"), data.get("issue")
            if not bot_id or not issue or not _auth_bot(bot_id, headers):
                return _json(401, {"ok": False, "error": "bad bot_id or key"})
            from_role = role_of(bot_id)
            to_role = data.get("target") or next_role(from_role)
            if to_role not in TIERS:
                return _json(400, {"ok": False, "error": "unknown target tier"})
            status = "awaiting_master" if to_role == "master" else "open"
            esc_id = store().add_escalation(
                bot_id, from_role, to_role, issue, data.get("context", {}), status)
            post_event(bot_id, f"{display_name(bot_id)} escalated #{esc_id} to the "
                               f"{TIER_LABELS[to_role]}: {str(issue)[:200]}")
            return _json(200, {"ok": True, "escalation_id": esc_id,
                               "from_role": from_role, "to_role": to_role,
                               "status": status})

        if path == "/api/commandeer":
            bot_id, request = data.get("bot_id"), data.get("request")
            if not bot_id or not request or not _auth_bot(bot_id, headers):
                return _json(401, {"ok": False, "error": "bad bot_id or key"})
            if role_of(bot_id) != "master":
                return _json(403, {"ok": False, "error": "only master may commandeer"})
            order_id = store().add_order(request, bot_id)
            post_event(bot_id, f"{display_name(bot_id)} issued order #{order_id}: {str(request)[:200]}")
            return _json(200, {"ok": True, "order_id": order_id, "status": "active"})

        if path.startswith("/api/orders/") and path.endswith("/ack"):
            bot_id = data.get("bot_id")
            if not bot_id or not _auth_bot(bot_id, headers):
                return _json(401, {"ok": False, "error": "bad bot_id or key"})
            try:
                order_id = int(path.split("/")[3])
            except (IndexError, ValueError):
                return _json(400, {"ok": False, "error": "bad order id"})
            acked = store().ack_order(order_id, bot_id)
            if acked is None:
                return _json(404, {"ok": False, "error": "no such order"})
            post_event(bot_id, f"{display_name(bot_id)} acknowledged order #{order_id}")
            return _json(200, {"ok": True, "order_id": order_id, "acked_by": acked})

        if path == "/api/fitness":
            bot_id, summary = data.get("bot_id"), data.get("summary")
            if not bot_id or not isinstance(summary, dict) or not _auth_bot(bot_id, headers):
                return _json(401, {"ok": False, "error": "bad bot_id, key or summary"})
            store().add_fitness(bot_id, summary)
            post_event(bot_id, f"{display_name(bot_id)} posted a fitness summary")
            return _json(200, {"ok": True})

        if path == "/api/summary":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            result = summarize(store().unprocessed_reports(50))
            return _json(200 if result["ok"] else 502, result)

        if path == "/api/chat":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            agent, msgs = data.get("agent"), data.get("messages")
            if agent not in AGENTS:
                return _json(400, {"ok": False, "error": "unknown agent"})
            if not isinstance(msgs, list) or not msgs:
                return _json(400, {"ok": False, "error": "messages must be a non-empty list"})
            history = []
            for m in msgs[-CHAT_HISTORY:]:
                if (not isinstance(m, dict) or m.get("role") not in ("user", "assistant")
                        or not isinstance(m.get("content"), str)):
                    return _json(400, {"ok": False, "error": "bad message"})
                history.append({"role": m["role"], "content": m["content"][:4000]})
            if history[-1]["role"] != "user":
                return _json(400, {"ok": False, "error": "last message must be from user"})
            try:
                parsed = (parse_expense(history[-1]["content"])
                          if agent == "glass" and looks_like_purchase(history[-1]["content"]) else None)
                chart = charter_reply(history[-1]["content"]) if agent == "charter" else None
                image = None
                if chart:
                    reply, image = chart
                elif parsed:
                    reply = glass_log_reply(parsed)
                elif agent == "james":
                    reply = james_chat(history)
                else:
                    reply = run_actions(agent, llm_chat(AGENTS[agent]["tier"], [
                        {"role": "system", "content": system_prompt(agent, tools=True)}] + history))
                    if isinstance(reply, dict):  # a proposal: its buttons live in Chat
                        store().add_chat(agent, reply["text"][:4000], buttons=reply["buttons"])
                        reply = reply["text"] + "\n\n(Approve or decline it in Chat.)"
            except LLMError as e:
                return _json(502, {"ok": False, "error": str(e)})
            return _json(200, {"ok": True, "agent": agent, "name": AGENTS[agent]["name"],
                               "model": agent_model(agent), "reply": reply, "image": image})

        if path == "/api/voice/say":  # the Head page: a sentence or two in Theta's Orpheus voice, as WAV
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            try:
                audio = server_say(str(data.get("text") or ""), str(data.get("voice") or ""))
            except ValueError as e:
                return _json(400, {"ok": False, "error": str(e)})
            except LLMError as e:
                return _json(429 if getattr(e, "status", None) == 429 else 502, {"ok": False, "error": str(e)})
            kind = "audio/wav" if audio[:4] == b"RIFF" else "audio/mpeg"  # Fish Audio sends MP3
            return 200, kind, audio, [("Cache-Control", "no-store")]

        if path == "/api/board/click":  # a tap on the board: what you open first counts most (board.py)
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            return _json(200, {"ok": True, **board_click(data.get("id"), data.get("order"), str(data.get("title") or "")[:200],
                                                        "news" if data.get("kind") == "news" else "widget")})

        if path == "/api/voice/fish/config":  # Settings: Theta's Fish Audio voice and the paid voice's monthly cap
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            try:
                cfg = fish_set(voice=data.get("voice") if "voice" in data else None,
                               name=data.get("name"), cap=data.get("cap") if "cap" in data else None,
                               keep=data.get("keep") if "keep" in data else None,
                               seeded=data.get("seeded") if "seeded" in data else None,
                               page=data.get("page") if "page" in data else None)
            except ValueError as e:
                return _json(400, {"ok": False, "error": str(e)})
            return _json(200, {"ok": True, **cfg})

        if path.startswith("/api/personas"):  # personas: save, switch, delete
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            return _json(200, personas_route("POST", path, data))

        if path == "/api/voice/hear":  # Glasses mode: a recorded clip -> text (Groq Whisper)
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            try:
                audio = base64.b64decode(str(data.get("audio") or ""), validate=True)
                return _json(200, {"ok": True, "text": groq_hear(audio, str(data.get("mime") or "audio/mp4"))})
            except ValueError as e:  # bad base64 is a ValueError too
                return _json(400, {"ok": False, "error": str(e) or "bad audio"})
            except LLMError as e:
                return _json(429 if getattr(e, "status", None) == 429 else 502, {"ok": False, "error": str(e)})

        if path in ("/api/convo/start", "/api/convo/chunk", "/api/convo/end", "/api/voice/translate"):
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            try:
                if path == "/api/convo/start":  # a conversation recording begins (Head page)
                    cid = hashlib.sha1(f"{time.time_ns()}".encode()).hexdigest()[:12]
                    convo_open(cid)
                    return _json(200, {"ok": True, "id": cid})
                if path == "/api/convo/end":
                    return _json(200, {"ok": True, "text": convo_end(str(data.get("id") or ""), str(data.get("title") or ""))})
                audio = base64.b64decode(str(data.get("audio") or ""), validate=True)
                mime = str(data.get("mime") or "audio/mp4")
                if path == "/api/convo/chunk":
                    return _json(200, {"ok": True, "text": convo_add(str(data.get("id") or ""), audio, mime)})
                return _json(200, {"ok": True, **translate_clip(audio, mime, str(data.get("to") or ""))})
            except ValueError as e:  # bad base64 is a ValueError too
                return _json(400, {"ok": False, "error": str(e) or "bad audio"})
            except LLMError as e:
                return _json(429 if getattr(e, "status", None) == 429 else 502, {"ok": False, "error": str(e)})

        if path == "/api/typing":  # the composer, while you type (typing guard)
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            store().set_meta("user:typing", str(time.time()))
            return _json(200, {"ok": True})

        if path == "/api/allchat":
            text, bot_id = data.get("text"), data.get("bot_id")
            ch = data.get("channel") if data.get("channel") in CHANNEL_IDS else "all"
            pic = data.get("image") if isinstance(data.get("image"), str) and not bot_id else None
            try:
                cleaned = validate_attachments(data.get("attachments")) if data.get("attachments") is not None else None
            except ValueError as e:
                return _json(400, {"ok": False, "error": str(e)})
            if (pic or cleaned) and text is None:
                text = ""
            if not isinstance(text, str) or not (text.strip() or pic or cleaned):
                return _json(400, {"ok": False, "error": "text required"})
            _REQ.rid = re.sub(r"[^\w-]", "", str(data.get("rid") or ""))[:24] or None  # for "who's working" notes
            if bot_id:  # a bot posting: no replies, so agents can't loop
                if not _auth_bot(bot_id, headers):
                    return _json(401, {"ok": False, "error": "bad bot_id or key"})
                text, leaked = redact_secrets(text)
                warn_secrets(leaked)
                store().add_chat(bot_id, text.strip()[:2000], channel=data.get("channel") if ch != "all" else None)
                return _json(200, {"ok": True, "messages": allchat_view(channel=ch), "latest": latest_by_channel()})
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            text, leaked = redact_secrets(text)  # before it's saved or sent to any model
            warn_secrets(leaked)
            if text.strip().startswith("/") and not pic and not cleaned:
                try:
                    result = run_command(text)
                except CommandError as e:
                    return _json(400, {"ok": False, "error": str(e)})
                return _json(200, {"ok": True, "command": True, "result": result, "latest": latest_by_channel(),
                                   "messages": allchat_view(channel=ch), "errors": {}, "routed": []})
            st = store()
            atts_out, image = [], None
            try:
                if cleaned is not None:
                    for name, kind, data_url, _size in cleaned:
                        if kind == "image":
                            url = save_upload(data_url)
                        else:
                            url, _k, _s = save_file(name, data_url)
                        atts_out.append({"url": url, "name": name, "kind": kind})
                        if kind == "image" and image is None:
                            image = url
                elif pic:
                    image = save_upload(pic)
            except ValueError as e:
                return _json(400, {"ok": False, "error": str(e)})
            st.add_chat("you", text.strip()[:2000], image=image, channel=ch,
                        attachments=atts_out or None)
            thread = (st.list_chat(CHAT_HISTORY) if ch == "all" else
                      [m for m in st.list_chat(ALLCHAT_KEEP) if message_channel(m) == ch][-CHAT_HISTORY:])
            errors, routed = {}, []
            _REQ.ch = ch if ch != "all" else None  # activity lines land in this conversation
            _diag("allchat.start", channel=ch, thread=len(thread))
            if CHAT_MODE != "crew" or head_on():  # the front desk (or the single head) answers (Theta for hard ones); plain commands run at once
                try:
                    quick = desk_shortcut(thread)
                    if quick and head_on():  # the instant command still runs; Theta is who says so
                        quick = ("theta", quick[1])
                    replies, errors = (([(quick[0], quick[1], reply_extra())], {}) if quick else
                                       head_replies(thread, spoken=data.get("spoken") is True) if head_on()
                                       else desk_replies(thread))
                except Exception as e:
                    _diag("desk.compute_failed", error_class=type(e).__name__, error=str(e))
                    replies, errors = [], {AGENTS[DESK]["name"]: str(e)[:200]}
                _diag("allchat.replies", replies=len(replies), errors=len(errors))
                try:
                    for who, reply, extra in replies:
                        if isinstance(reply, tuple):  # Charter's (caption, chart url)
                            st.add_chat(who, reply[0], image=reply[1], channel=ch, extra=extra)
                        elif isinstance(reply, dict):
                            st.add_chat(who, reply["text"][:4000], channel=ch, buttons=reply.get("buttons"), extra=extra)
                        elif reply:
                            st.add_chat(who, reply.strip()[:4000], channel=ch, extra=extra)
                        if who == "theta":
                            routed = [who]
                except Exception as e:
                    # The tools already ran before this save, so the user
                    # must hear that: a blind retry would run them twice.
                    _diag("reply.persist_failed", error_class=type(e).__name__, error=str(e))
                    return _json(502, {"ok": False, "error": "couldn't save the reply — anything it already did, like a task it created, still happened; check before sending it again"})
                has_buttons = any(isinstance(r[1], dict) and r[1].get("buttons") for r in replies)
                working_final(_REQ.rid, "failed" if (errors and not replies) else
                              "waiting_approval" if has_buttons else "completed")
                try:
                    view = allchat_view(channel=ch)
                    latest = latest_by_channel()
                except Exception as e:
                    _diag("reply.view_failed", error_class=type(e).__name__, error=str(e))
                    return _json(502, {"ok": False, "error": "couldn't load the updated chat — the reply itself was saved; refresh to see it"})
                return _json(200, {"ok": True, "messages": view, "errors": errors,
                                   "routed": [AGENTS[a]["name"] for a in routed], "latest": latest})
            agents = mentioned_agents(text)
            members = CHANNEL_IDS[ch]["members"]
            if not agents and ch == "news":
                agents = list(members)  # the debate channel: all three weigh in
            elif not agents and len(members) == 1:
                agents = list(members)
            elif not agents and ALLCHAT_AUTO:
                try:
                    agents = routed = pick_responders(thread, members or None)
                except LLMError as e:
                    errors["Mistral (picking who answers)"] = str(e)
                    if members:
                        agents = members[:1]

            def answer(a):
                try:
                    return a, allchat_reply(a, thread), None
                except (LLMError, ValueError, KeyError) as e:
                    return a, None, str(e)
            crew_ok, crew_buttons = 0, False
            if agents:
                with ThreadPoolExecutor(max_workers=len(agents)) as ex:
                    for a, reply, err in ex.map(answer, agents):
                        if isinstance(reply, tuple):  # Charter's (caption, chart url)
                            crew_ok += 1
                            st.add_chat(a, reply[0], image=reply[1], channel=ch)
                        elif isinstance(reply, dict):  # James's workout reply, with buttons
                            crew_ok += 1
                            crew_buttons = True
                            st.add_chat(a, reply["text"][:4000], channel=ch, buttons=reply["buttons"])
                        elif reply:
                            crew_ok += 1
                            st.add_chat(a, reply.strip()[:4000], channel=ch)
                        else:
                            errors[AGENTS[a]["name"]] = err
            working_final(_REQ.rid, "failed" if (agents and not crew_ok) else
                          "waiting_approval" if crew_buttons else "completed")
            return _json(200, {"ok": True, "messages": allchat_view(channel=ch), "errors": errors,
                               "routed": [AGENTS[a]["name"] for a in routed], "latest": latest_by_channel()})

        if path == "/api/glass/expense":
            bot_id = data.get("bot_id")
            if not (_auth_bot(bot_id, headers) if bot_id else _auth_dashboard(query, headers)):
                return _json(401, {"ok": False, "error": "dashboard key or bot key required"})
            try:
                amount = float(data.get("amount"))
            except (TypeError, ValueError):
                return _json(400, {"ok": False, "error": "amount must be a number"})
            if amount <= 0 or not str(data.get("category") or "").strip():
                return _json(400, {"ok": False, "error": "positive amount and a category required"})
            day = _parse_day(str(data.get("date") or "")) if data.get("date") else None
            exp = add_expense(amount, str(data["category"]), str(data.get("note") or ""), day=day,
                              source=bot_id or "dashboard")
            post_event("glass", f"Glass logged ${amount:,.2f} for {exp['category']}"
                                + (f" from {display_name(bot_id)}" if bot_id else ""))
            return _json(200, {"ok": True, "expense": exp})

        if path == "/api/glass/remove":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            month, item = str(data.get("month") or ""), str(data.get("id") or "")
            if not re.fullmatch(r"\d{4}-\d{2}", month) or item not in store().expense_items(month):
                return _json(404, {"ok": False, "error": "That expense isn't there any more."})
            e = store().expense_items(month)[item]
            store().remove_expenses(month, [item])
            post_event("glass", f"You removed ${e['amount']:,.2f} for {e['category']} ({e['note']}) from {e['date']}")
            return _json(200, {"ok": True})

        if path == "/api/glass/import":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            if not isinstance(data.get("csv"), str):
                return _json(400, {"ok": False, "error": "send {\"csv\": <file text>}"})
            result = import_csv(data["csv"])
            if result["ok"] and result["added"]:
                post_event("glass", f"Glass imported {result['added']} expenses from a CSV "
                                    f"({', '.join(result['months'])})")
            return _json(200 if result["ok"] else 400, result)

        if path == "/api/push/subscribe":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            sub = data.get("subscription")
            if not (isinstance(sub, dict) and str(sub.get("endpoint", "")).startswith("https://")
                    and isinstance(sub.get("keys"), dict) and sub["keys"].get("p256dh") and sub["keys"].get("auth")):
                return _json(400, {"ok": False, "error": "not a push subscription"})
            subs = [x for x in push_subs() if x.get("endpoint") != sub["endpoint"]]
            subs.append({"endpoint": sub["endpoint"], "keys": {"p256dh": sub["keys"]["p256dh"], "auth": sub["keys"]["auth"]},
                         "made": time.time(), "device": device_label(headers.get("user-agent")), "place": _place(headers),
                         "sess": (current_session(headers) or _REQ.session or {}).get("id")})
            store().set_meta("push:subs", json.dumps(subs[-10:]))
            store().set_meta("push:last_error", "")
            post_event("mistral", "Mistral will now send phone notifications to a new device")
            return _json(200, {"ok": True, "devices": len(subs[-10:])})

        if path == "/api/push/fail":  # the phone's own reason notifications didn't turn on
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            fails = _meta_json("push:fails", [])
            fails.append({"at": time.time(), "stage": str(data.get("stage") or "?")[:20],
                          "error": str(data.get("error") or "?")[:200], "standalone": bool(data.get("standalone")),
                          "device": device_label(headers.get("user-agent"))})
            store().set_meta("push:fails", json.dumps(fails[-10:]))
            return _json(200, {"ok": True})

        if path == "/api/push/remove":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            target = str(data.get("id") or "")
            subs = push_subs()
            keep = [x for x in subs if hashlib.sha1(x.get("endpoint", "").encode()).hexdigest()[:10] != target]
            if len(keep) == len(subs):
                return _json(404, {"ok": False, "error": "no such device"})
            store().set_meta("push:subs", json.dumps(keep))
            return _json(200, {"ok": True})

        if path == "/api/push/test":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            store().set_meta("push:last", "")
            sent = notify("Mistral", f"Test: phone notifications from {APP_NAME} work.")
            problem = push_problem()
            results = (_meta_json("push:last", {}) or {}).get("results", [])
            return _json(200, {"ok": True, "sent": sent, "results": results, "error": (problem[1] if problem else None)
                               or (None if sent else store().get_meta("push:last_error"))
                               or (None if sent else "no device has turned notifications on yet")})

        if path == "/api/status":
            bot_id, activity = data.get("bot_id"), data.get("activity")
            if not isinstance(activity, str) or not activity.strip():
                return _json(400, {"ok": False, "error": "activity required, e.g. \"researching\""})
            if not bot_id or not _auth_bot(bot_id, headers):
                return _json(401, {"ok": False, "error": "bad bot_id or key"})
            st = store()
            before = st.list_status().get(bot_id, {}).get("activity")
            st.touch(bot_id, activity.strip()[:80])
            if before != activity.strip()[:80]:
                post_event(bot_id, f"{display_name(bot_id)} is now {activity.strip()[:80]}")
            return _json(200, {"ok": True})

        if path == "/api/gym/ask":  # Garage Gym's James forwarding a question he couldn't answer
            sent = str(headers.get("x-hub-secret") or "")
            if not (GARAGE_GYM_SECRET and hmac.compare_digest(sent, GARAGE_GYM_SECRET)):
                return _json(401, {"ok": False, "error": "hub secret required"})
            try:
                out = gym_ask(data.get("question") or "", data.get("context") or "")
            except ValueError as e:
                return _json(429 if "today" in str(e) else 400, {"ok": False, "error": str(e)})
            except LLMError as e:
                return _json(502, {"ok": False, "error": str(e)[:200]})
            return _json(200, {"ok": True, **out})

        if path == "/api/phone/event":  # a Shortcuts automation: "arrived at the gym", "alarm stopped"
            if not (ask_key_ok(headers) or _auth_dashboard(query, headers)):
                return _json(401, {"ok": False, "error": "key required"})
            try:
                return _json(200, {"ok": True, "did": phone_event(data.get("event") or data.get("text"))})
            except ValueError as e:
                return _json(400, {"ok": False, "error": str(e)})

        if path == "/api/ask":  # Siri Shortcut: say it, the crew answers, Siri reads it out
            ask_ok = ASK_KEY and hmac.compare_digest(str(headers.get("x-ask-key") or ""), ASK_KEY)
            if not (ask_ok or _auth_dashboard(query, headers)):
                return _json(401, {"ok": False, "error": "key required"})
            if ask_ok:
                try:
                    note_key_use(headers, "Siri ask key")
                except Exception:
                    pass
            _REQ.quiet = True
            text = str(data.get("text") or "").strip()[:2000]
            if not text:
                return _json(400, {"ok": False, "speech": "I didn't catch that."})
            names = {v["name"].lower(): v["name"] for v in AGENTS.values()}
            lead = re.match(r"^\s*(?:hey\s+|ok\s+)?([A-Za-z]+)[,.:!]?\s+", text)  # "Remi, remind me..." from dictation
            if lead and lead.group(1).lower() in names:
                text = f"@{names[lead.group(1).lower()]} " + text[lead.end():]
            inner = {**headers, "x-dashboard-key": DASHBOARD_KEY} if DASHBOARD_KEY else headers
            before = max([m["id"] for m in store().list_chat(ALLCHAT_KEEP)] + [0])
            status, _, out, *_ = handle("POST", "/api/allchat", {}, inner, json.dumps(
                {"text": text, "channel": str(data.get("channel") or "all")}).encode())
            d = json.loads(out)
            if d.get("command"):
                return _json(200, {"ok": d.get("ok", False), "speech": speakable(d.get("result") or d.get("error") or "Done.")})
            replies = [m for m in store().list_chat(ALLCHAT_KEEP) if m["id"] > before and m["from"] not in ("you", "hub")
                       and m.get("kind") != "event"]
            if not replies:
                why = "; ".join(f"{k}: {v}" for k, v in (d.get("errors") or {}).items()) or d.get("error") or "Nobody answered."
                return _json(200, {"ok": False, "speech": speakable(why)})
            speech = " ".join(f"{chat_name(m['from'])} says: {speakable(m['text'])}" if len(replies) > 1 else speakable(m["text"])
                              for m in replies)
            return _json(200, {"ok": True, "speech": speech[:1500],
                               "replies": [{"from": chat_name(m["from"]), "text": m["text"]} for m in replies]})

        if path == "/api/settings/notifs":  # Settings → Notifications: one kind on or off
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            try:
                notif_set(str(data.get("kind") or ""), bool(data.get("on")))
            except ValueError as e:
                return _json(400, {"ok": False, "error": str(e)})
            return _json(200, {"ok": True})

        if path == "/api/settings/notify":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            store().set_meta("notify:rounds", "on" if data.get("rounds") else "off")
            return _json(200, {"ok": True})

        if path == "/api/chat/check":  # ticking a checklist item in a chat message
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            try:
                mid, idx = int(data.get("msg")), int(data.get("index"))
            except (TypeError, ValueError):
                return _json(400, {"ok": False, "error": "msg and index required"})
            checks = _meta_json("chat:checks", {})
            checks.setdefault(str(mid), {})[str(idx)] = bool(data.get("on"))
            store().set_meta("chat:checks", json.dumps(dict(list(checks.items())[-300:])))
            return _json(200, {"ok": True})

        if path == "/api/chat/press":  # a button on an agent's message (James's workout buttons)
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            mid, bid = data.get("msg"), str(data.get("id") or "")
            m = next((x for x in store().list_chat(ALLCHAT_KEEP) if x["id"] == mid), None)
            b = next((x for x in (m or {}).get("buttons") or [] if x["id"] == bid and x.get("value") == data.get("value")), None)
            pressed = _meta_json("chat:pressed", [])
            proposal = bool(re.match(r"^qp:[0-9a-f]{8}:(yes|no)$", bid))
            # Approve / Decline (and Keep / No, Move to tomorrow) work on whoever posted them: QWERTY's
            # proposals, and Theta's own offers since it answers everything (single head). James's
            # workout buttons are his.
            if not m or not b or not (proposal or m["from"] == "james"):
                return _json(400, {"ok": False, "error": "That button is gone."})
            if mid in pressed:
                return _json(409, {"ok": False, "error": "Already done."})
            store().set_meta("chat:pressed", json.dumps((pressed + [mid])[-300:]))  # one press per message, like Discord
            if proposal:
                pm = re.match(r"^qp:([0-9a-f]{8}):(yes|no)$", bid)
                try:
                    line = apply_proposal(pm.group(1), pm.group(2) == "yes") if pm else "That button is gone."
                except ValueError as e:
                    line = str(e)
                ch = message_channel(m)
                if line.startswith("\u2717"):  # it didn't work: the buttons come back, to try again
                    store().set_meta("chat:pressed", json.dumps([x for x in _meta_json("chat:pressed", []) if x != mid]))
                store().add_chat("theta" if head_on() else "qwerty", line, channel=ch)
                return _json(200, {"ok": True, "messages": allchat_view(channel=str(data.get("channel") or ch)),
                                   "latest": latest_by_channel()})
            try:
                r = james_command(component=bid, values=[b["value"]] if b.get("value") else [])
            except LLMError as e:
                store().set_meta("chat:pressed", json.dumps([x for x in _meta_json("chat:pressed", []) if x != mid]))
                return _json(502, {"ok": False, "error": str(e)})
            ch = message_channel(m)
            store().add_chat("james", r["text"][:4000], channel=ch, buttons=r["buttons"])
            return _json(200, {"ok": True, "messages": allchat_view(channel=str(data.get("channel") or ch)),
                               "latest": latest_by_channel()})

        if path == "/api/devices/hello":  # Settings says what this device is: Home Screen app? its notification sign-up?
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            me = current_session(headers) or _REQ.session
            if not me:
                return _json(200, {"ok": True, "changed": False})
            changed = False
            app = "Home Screen app" if data.get("standalone") else None
            with _SESS_LOCK:
                live = sessions()
                for v in live.values():
                    if v["id"] == me["id"] and app and v.get("app") != app:
                        v["app"], changed = app, True
                if changed:
                    store().set_meta("sessions", json.dumps(live))
            endpoint = str(data.get("endpoint") or "")
            if endpoint:
                subs = push_subs()
                for x in subs:
                    if x.get("endpoint") == endpoint and x.get("sess") != me["id"]:
                        x["sess"], changed = me["id"], True
                if changed:
                    store().set_meta("push:subs", json.dumps(subs))
            return _json(200, {"ok": True, "changed": changed})

        if path == "/api/lock/away":  # sent (beacon) when the app goes to the background
            sess = current_session(headers)
            if sess and sess.get("lock") and not sess.get("locked") and not sess.get("hidden"):
                update_session(_REQ.sess_key, hidden=time.time())
            return _json(200, {"ok": True})

        if path == "/api/lock/set":
            if not _auth_dashboard(query, headers) or not _REQ.sess_key:
                return _json(401, {"ok": False, "error": "Sign in on this device first."})
            me = sessions().get(_REQ.sess_key, {})
            if data.get("on"):
                rp_id, origin = _rp(headers)
                try:  # proves this device can unlock before it can be locked
                    verify_passkey(data.get("assertion") or {}, rp_id, origin)
                except (ValueError, KeyError, TypeError) as e:
                    passkey_fail(headers, "lock", str(e), rp_id)
                    return _json(400, {"ok": False, "error": f"Face ID didn't pass ({str(e)[:120]}), so the lock is still off."})
                update_session(_REQ.sess_key, lock=True, locked=None, hidden=None, unlocked=time.time())
                post_event("qwerty", f"Face ID lock turned on for {device_name(me)}")
            else:
                update_session(_REQ.sess_key, lock=None, locked=None, hidden=None)
                post_event("qwerty", f"Face ID lock turned off for {device_name(me)}")
            return _json(200, {"ok": True})

        if path == "/api/devices/name":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            if not name_device(str(data.get("id") or ""), str(data.get("name") or "")):
                return _json(404, {"ok": False, "error": "That device isn't signed in any more."})
            return _json(200, {"ok": True})

        if path == "/api/devices/signout":
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            me = current_session(headers) or _REQ.session or {}
            target = str(data.get("id") or "")
            if not target or target == me.get("id"):
                return _json(400, {"ok": False, "error": "Pick another device (this one stays signed in)."})
            gone = sign_out_device(target, keep=me.get("id"))
            post_event("qwerty", f"QWERTY signed out {gone} device{'s' if gone != 1 else ''}")
            return _json(200, {"ok": True, "signed_out": gone})

        if path == "/api/seat/remove":  # an agent's own note, from Settings
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            item = str(data.get("id") or "")
            with _TOOL_LOCK:
                for a in AGENTS:
                    mine = seat_notes(a)
                    if any(n["id"] == item for n in mine):
                        store().set_meta(f"seat:{a}", json.dumps([n for n in mine if n["id"] != item]))
            return _json(200, {"ok": True})

        if path in ("/api/memory/remove", "/api/notes/remove"):
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            key, item = path.split("/")[2], str(data.get("id") or "")
            with _TOOL_LOCK:
                store().set_meta(key, json.dumps([x for x in _meta_json(key, []) if x["id"] != item]))
            return _json(200, {"ok": True})

        if path.startswith("/api/daily/"):
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            try:
                if path == "/api/daily/toggle":
                    on = daily_toggle(str(data.get("id") or ""))
                    items, done = daily_items(), daily_done()
                    all_done = bool(items) and all(i["id"] in done for i in items)
                    return _json(200, {"ok": True, "done": on, "label": streak_label(daily_streak(), all_done)})
                if path == "/api/daily/add":
                    return _json(200, {"ok": True, "item": daily_add(data.get("text") or "")})
                if path == "/api/daily/remove":
                    daily_remove(str(data.get("id") or ""))
                    return _json(200, {"ok": True})
            except ValueError as e:
                return _json(400, {"ok": False, "error": str(e)})
            return _json(404, {"ok": False, "error": "unknown route"})

        if path.startswith(("/api/mail/", "/api/gmail/")):
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            try:
                if path == "/api/gmail/disconnect":
                    gmail_disconnect()
                    return _json(200, {"ok": True})
                if not gmail_connected():
                    return _json(400, {"ok": False, "error": "Gmail isn't connected. Settings → Gmail."})
                tid = str(data.get("id") or "")
                if path == "/api/mail/sync":
                    return _json(200, {"ok": True, "did": gmail_sync(deadline=time.time() + 45)})
                if path == "/api/mail/send":
                    mail_send(tid, data.get("text"))
                    return _json(200, {"ok": True})
                if path == "/api/mail/skip":
                    mail_skip(tid)
                    return _json(200, {"ok": True})
                if path == "/api/mail/draft":
                    return _json(200, {"ok": True, "draft": mail_draft_now(tid)["text"]})
                if path == "/api/mail/sender":
                    mail_set_sender(str(data.get("email") or ""), str(data.get("cat") or ""))
                    return _json(200, {"ok": True})
            except ValueError as e:
                return _json(400, {"ok": False, "error": str(e)})
            except LLMError as e:
                return _json(502, {"ok": False, "error": str(e)})
            return _json(404, {"ok": False, "error": "unknown route"})

        if path.startswith("/api/lenz/"):
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            if path == "/api/lenz/import":
                entries = parse_media_log(str(data.get("text") or ""))
                if not entries:
                    return _json(400, {"ok": False, "error": "Lenz couldn't find any titles in that. Paste the "
                                       "whole log, headings included (Current, In Queue, Rankings...)."})
                r = merge_into_library(entries)
                post_event("lenz", f"Lenz imported your log: {r['added']} new, {r['updated']} updated, {r['total']} in all")
                return _json(200, {"ok": True, **r})
            if path == "/api/lenz/items":
                title = str(data.get("title") or "").strip()
                if not title:
                    return _json(400, {"ok": False, "error": "title required"})
                it, _ = add_library_item(title, data.get("kind"), data.get("status") or "queue")
                return _json(200, {"ok": True, "item": it})
            iid = path[len("/api/lenz/items/"):] if path.startswith("/api/lenz/items/") else ""
            action = data.get("action")
            if not iid.isdigit() or action not in ("watched", "rate", "start", "next", "status", "delete"):
                return _json(400, {"ok": False, "error": "unknown item or action"})
            value = data.get("value")
            if action in ("rate",) and not (isinstance(value, int) and 1 <= value <= 10):
                return _json(400, {"ok": False, "error": "rating must be 1-10"})
            it = update_library_item(int(iid), action, value)
            if not it:
                return _json(404, {"ok": False, "error": "no such item"})
            line = ""
            if action == "watched":
                line = lenz_logged_line(it)
                store().add_chat("lenz", line, channel="screen")
            return _json(200, {"ok": True, "item": it, "line": line})

        if path.startswith("/api/passkey/"):
            rp_id, origin = _rp(headers)
            if path == "/api/passkey/unlock":  # Face ID lock: open this device again
                sess = current_session(headers)
                if not sess:
                    return _json(401, {"ok": False, "error": "This device isn't signed in any more. Sign in instead."})
                try:
                    verify_passkey(data, rp_id, origin)
                except (ValueError, KeyError, TypeError) as e:
                    passkey_fail(headers, "unlock", str(e), rp_id)
                    return _json(401, {"ok": False, "error": str(e)[:160]})
                update_session(_REQ.sess_key, locked=None, hidden=None, unlocked=time.time())
                return _json(200, {"ok": True})
            if path == "/api/passkey/login":
                try:
                    pk = verify_passkey(data, rp_id, origin)
                except (ValueError, KeyError, TypeError) as e:
                    passkey_fail(headers, "sign-in", str(e), rp_id)
                    return _json(401, {"ok": False, "error": str(e)[:160]})
                new_session(headers, f"Face ID: {pk['name']}")
                return _json(200, {"ok": True})
            if path == "/api/passkey/fail":  # the browser's own error, so QWERTY can see why Face ID failed
                passkey_fail(headers, str(data.get("stage") or "?")[:20], str(data.get("error") or "?"), rp_id)
                return _json(200, {"ok": True})
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            if path == "/api/passkey/register":
                try:
                    pk = register_passkey(data, rp_id, origin, data.get("name") or "This device")
                except (ValueError, KeyError, TypeError, IndexError) as e:
                    passkey_fail(headers, "adding", str(e), rp_id)
                    return _json(400, {"ok": False, "error": str(e)[:160]})
                return _json(200, {"ok": True, "name": pk["name"]})
            if path == "/api/passkey/remove":
                with _PK_LOCK:
                    keys = [k for k in passkeys() if k["id"] != data.get("id")]
                    store().set_meta("passkeys", json.dumps(keys))
                return _json(200, {"ok": True})
            return _json(404, {"ok": False, "error": "unknown route"})

        if path == "/api/tick":  # Supabase Cron, every few minutes: reminders that are due
            cron = bool(CRON_SECRET) and headers.get("authorization") == f"Bearer {CRON_SECRET}"
            if not (cron or (DASHBOARD_KEY and _auth_dashboard(query, headers))):
                return _json(401, {"ok": False, "error": "CRON_SECRET or dashboard key required"})
            out = run_tick()
            try:
                refresh_shared()  # keep feeds, trending and calendars fresh for the next page
            except Exception as e:
                print(f"refresh during tick failed: {e!r}")
            return _json(200, {"ok": True, **out})

        if path == "/api/refresh":  # a page saw stale data and asked for new, after it loaded
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            last = float(store().get_meta("refresh:at") or 0)
            if time.time() - last < SNAP_REFRESH_EVERY:
                return _json(200, {"ok": True, "skipped": "refreshed moments ago"})
            store().set_meta("refresh:at", str(time.time()))
            refresh_shared()
            return _json(200, {"ok": True})

        if path == "/api/reminders" or path.startswith("/api/reminders/"):
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            if path == "/api/reminders":
                try:
                    r = add_reminder(str(data.get("text") or ""))
                except ValueError as e:
                    return _json(400, {"ok": False, "error": str(e)})
                return _json(200, {"ok": True, "reminder": r, "line": reminder_line(r)})
            parts = path.split("/")  # /api/reminders/<id>/<done|delete>
            if len(parts) != 5 or not parts[3].isdigit() or parts[4] not in ("done", "delete"):
                return _json(404, {"ok": False, "error": "unknown route"})
            r = (ack_reminder(int(parts[3]), early=query.get("early", [""])[0] == "1") if parts[4] == "done"
                 else delete_reminder(int(parts[3])))
            return _json(200 if r else 404, {"ok": bool(r), **({} if r else {"error": "no such reminder"})})

        if path == "/api/round":
            cron = bool(CRON_SECRET) and headers.get("authorization") == f"Bearer {CRON_SECRET}"
            if not (cron or (DASHBOARD_KEY and _auth_dashboard(query, headers))):
                return _json(401, {"ok": False, "error": "CRON_SECRET or dashboard key required"})
            return _json(200, run_round(force=bool(data.get("force"))))

        if path == "/api/hbench":  # Diagnostics → Harness test: one message one way per request
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            try:
                hb_run(str(data.get("case") or ""), str(data.get("mode") or ""))
            except ValueError as e:
                return _json(400, {"ok": False, "error": str(e)})
            rows = _meta_json("hbench:last", {}).get("rows", [])
            return _json(200, {"ok": True, "rows": rows, "totals": hb_totals(rows), "sizes": prompt_sizes()})

        if path == "/api/bench":  # Settings → Mistral benchmark: ~12 Haiku calls, a few cents
            if not _auth_dashboard(query, headers):
                return _json(401, {"ok": False, "error": "dashboard key required"})
            if not master_ready() and not (LOCAL_LLM_URL and LOCAL_LLM_MODEL) and not os.environ.get("DEEPSEEK_API_KEY"):
                return _json(400, {"ok": False, "error": "Claude isn't available (ANTHROPIC_API_KEY unset, or this "
                                                         "month's cap is reached) and your PC isn't linked, so there's "
                                                         "nothing to benchmark"})
            last = _meta_json("bench:last", {})
            if time.time() - last.get("at", 0) < 60:
                return _json(429, {"ok": False, "error": "It just ran. Give it a minute before running it again."})
            return _json(200, {"ok": True, **run_bench()})

        return _json(404, {"ok": False, "error": "unknown route"})

    # GET
    if path.startswith("/api/personas"):
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, personas_route("GET", path, {k: v[0] for k, v in query.items()}))
    if path == "/sw.js":
        return 200, "text/javascript; charset=utf-8", _SW_JS.encode(), [("Cache-Control", "no-cache")]
    assets = {"/ui.css": ("text/css; charset=utf-8", _UI_CSS), "/ui.js": ("text/javascript; charset=utf-8", _UI_JS),
              "/chat.js": ("text/javascript; charset=utf-8", _CHAT_JS)}
    if path in ("/head.js", "/head.css"):  # the Theta page's own script and styles, versioned (?v=) like ui.js
        a = head_assets()
        assets[path] = ("text/javascript; charset=utf-8", a["js"]) if path == "/head.js" else ("text/css; charset=utf-8", a["css"])
    if path in assets:  # versioned URLs (?v=), so they can be cached for good
        kind, text = assets[path]
        return 200, kind, text.encode(), [("Cache-Control", "public, max-age=31536000, immutable")]
    m = re.fullmatch(r"/fonts/([a-z0-9-]+-\d00)\.woff2", path)
    if m and os.path.isfile(os.path.join(_PARTS_DIR, "fonts", m.group(1) + ".woff2")):  # fixed names only
        with open(os.path.join(_PARTS_DIR, "fonts", m.group(1) + ".woff2"), "rb") as fh:
            return 200, "font/woff2", fh.read(), [("Cache-Control", "public, max-age=31536000, immutable")]
    if path.startswith("/avatar/") and path.endswith(".svg"):
        who = path[len("/avatar/"):-len(".svg")]
        return (200, "image/svg+xml", avatar_svg(who if who in AGENT_LOOKS else "hub").encode(),
                [("Cache-Control", "public, max-age=86400")])
    if path in ("/icon-192.png", "/icon-512.png", "/apple-touch-icon.png", "/favicon.ico"):
        size = {"/icon-192.png": 192, "/icon-512.png": 512, "/favicon.ico": 32}.get(path, 180)
        return 200, "image/png", _icon_png(size), [("Cache-Control", "public, max-age=604800")]
    if path == "/manifest.webmanifest":
        # Opened signed in (Safari's "Add to Home Screen"), the app starts with the
        # key, so the Home Screen copy (which has its own cookies) is signed in too.
        # The app opens on Theta (the Theta page is the chat too).
        start = (f"/head?key={DASHBOARD_KEY}" if DASHBOARD_KEY and _auth_dashboard(query, headers) else "/head")
        manifest = {"name": APP_NAME, "short_name": APP_NAME, "start_url": start, "scope": "/",
                    "display": "standalone", "background_color": THEMES["theta"]["dark"]["bg"],
                    "theme_color": AGENT_LOOKS["theta"][0],
                    "icons": [{"src": "/icon-192.png?v=2", "sizes": "192x192", "type": "image/png"},
                              {"src": "/icon-512.png?v=2", "sizes": "512x512", "type": "image/png"}]}
        return (200, "application/manifest+json", json.dumps(manifest).encode(),
                [("Cache-Control", "no-store")])
    if path == "/api/push/key":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        problem = push_problem()
        return _json(200, {"ok": True, "publicKey": None if problem else VAPID_PUBLIC_KEY,
                           "problem": problem[1] if problem else None, "devices": len(push_subs())})
    if path == "/api/push/health":
        # Public on purpose: says whether push is configured, never with what.
        problem = push_problem()
        return _json(200, {"ok": True, "status": problem[0] if problem else "ok",
                           "devices": len(push_subs())})
    if path == "/api/push/new-keys":
        if not _auth_dashboard(query, headers) or not DASHBOARD_KEY:
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, {"ok": True, **new_vapid_keys(), "next": "Add both to Vercel (Production and Preview, "
                           "Sensitive on), redeploy, then tap Turn on in the Home Screen app. Keep "
                           "VAPID_PRIVATE_KEY secret; this page makes a new pair each time."})

    if path == "/":
        if not _auth_dashboard(query, headers):
            return 401, "text/html; charset=utf-8", signin_page(headers).encode()
        st = store()
        host = headers.get("host")
        if host and st.get_meta("hub:origin") != f"https://{host}":
            st.set_meta("hub:origin", f"https://{host}")  # the push "subject" when VAPID_SUBJECT is unset
        return 200, "text/html; charset=utf-8", home_page(headers).encode(), _login_cookie(query)

    # In single-head mode the chat and the Head page are one page.
    pages = {"/chat": lambda: chat_page(headers, query, head=head_on()), "/calendar": lambda: calendar_page(headers, query),
             "/diagnostics": lambda: diagnostics_page(headers), "/lenz": lambda: lenz_page(headers),
             "/mail": lambda: mail_page(headers),
             "/money": lambda: money_page(headers), "/settings": lambda: settings_page(headers),
             "/head": lambda: chat_page(headers, query, head=True)}
    agent_path = path.startswith("/agent/") and path[len("/agent/"):] in AGENTS
    if path in pages or agent_path:
        if not _auth_dashboard(query, headers):
            return 401, "text/html; charset=utf-8", signin_page(headers).encode()
        out = agent_page(headers, path[len("/agent/"):]) if agent_path else pages[path]()
        return 200, "text/html; charset=utf-8", out.encode(), _login_cookie(query)

    if path == "/api/spotlight":  # the Spotlight background: upcoming entertainment you'd care about (board.py)
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, {"ok": True, "items": spotlight()})

    if path == "/api/board":  # the Theta page's widgets (board.py)
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, {"ok": True, **board()})

    if path == "/api/voice/fish/voices":  # Settings: Fish Audio's top English voices, to listen to and pick
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        try:
            return _json(200, {"ok": True, "voices": fish_voices(query.get("q", [""])[0], query.get("page", ["1"])[0])})
        except ValueError:
            return _json(400, {"ok": False, "error": "page must be a number"})
        except LLMError as e:
            return _json(502, {"ok": False, "error": str(e)})

    if path == "/api/voice/fish/sample":  # Settings: a voice sample through the hub, so the effect can be heard on it
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        try:
            kind, audio = fish_sample(query.get("url", [""])[0])
        except ValueError as e:
            return _json(400, {"ok": False, "error": str(e)})
        except LLMError as e:
            return _json(502, {"ok": False, "error": str(e)})
        return 200, kind, audio, [("Cache-Control", "private, max-age=86400")]

    if path == "/api/feed":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        limit = _limit(query, 20)
        if limit is None:
            return _json(400, {"ok": False, "error": "limit must be 1-100"})
        return _json(200, store().list_reports(limit))

    if path == "/api/orders":
        bot_id = query.get("bot_id", [None])[0]
        if not bot_id or not _auth_bot(bot_id, headers):
            return _json(401, {"ok": False, "error": "bad bot_id or key"})
        return _json(200, [o for o in store().list_active_orders()
                           if not o.get("targets") or bot_id in o["targets"]])

    if path == "/api/escalations":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, store().list_escalations(50))

    if path == "/api/widgets":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        fit_rows = store().list_fitness(1)
        breaking, top = news_items()
        return _json(200, {
            "entertainment": (pushed_items("entertainment") + widget_items(ENTERTAINMENT_FEEDS))[:20],
            "news": breaking + top + pushed_items("news"),
            "fitness": fit_rows[0] if fit_rows else None,
            "james": james_summary(),
        })

    if path == "/api/fitness":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        limit = _limit(query, 10)
        if limit is None:
            return _json(400, {"ok": False, "error": "limit must be 1-100"})
        return _json(200, store().list_fitness(limit))

    if path == "/api/bots":
        bots = []
        for bot_id in list(AGENTS) + sorted((set(BOT_KEYS) | set(BOT_ROLES)) - set(AGENTS)):
            bots.append({"bot_id": bot_id, "name": display_name(bot_id), "role": role_of(bot_id),
                         "model": agent_model(bot_id) if bot_id in AGENTS else MODELS[role_of(bot_id)]})
        return _json(200, bots)

    if path == "/api/phone/script":  # the widget's script, for Settings' Copy button (no secrets in it)
        return 200, "text/plain; charset=utf-8", widget_script(_rp(headers)[1]).encode()

    if path == "/api/phone/widget":  # the Scriptable Home Screen widget
        if not (ask_key_ok(headers) or _auth_dashboard(query, headers)):
            return _json(401, {"ok": False, "error": "key required"})
        return _json(200, phone_widget())

    if path == "/api/agents":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, agent_statuses())

    if path == "/api/allchat":
        bot_id = query.get("bot_id", [None])[0]
        if not (_auth_dashboard(query, headers) if not bot_id else _auth_bot(bot_id, headers)):
            return _json(401, {"ok": False, "error": "dashboard key or bot key required"})
        return _json(200, {"ok": True, "messages": allchat_view(channel=query.get("channel", ["all"])[0]),
                           "latest": latest_by_channel()})

    if path.startswith("/upload/"):
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        got = _decode_data_url(upload_data(path))
        if not got or got[0] not in ("image/jpeg", "image/png", "image/webp", "image/gif",
                                     "application/pdf", "text/plain", "text/markdown"):
            return _json(404, {"ok": False, "error": "no such upload"})
        return 200, got[0], got[1], [("Cache-Control", "private, max-age=86400")]

    if path.startswith("/chart/") and path.endswith(".svg"):
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        cid = path[len("/chart/"):-len(".svg")]
        svg = store().get_meta(f"chart:{cid}") if cid.isalnum() else None
        if not svg:
            return _json(404, {"ok": False, "error": "no such chart"})
        return 200, "image/svg+xml", svg.encode(), [("Cache-Control", "private, max-age=86400")]

    if path == "/api/glass":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        month = query.get("month", [datetime.now(hub_tz()).strftime("%Y-%m")])[0]
        return _json(200, {"ok": True, "month": month, "status": month_status(month),
                           "expenses": sorted(store().list_expenses(month), key=lambda e: e["date"])})

    if path == "/api/lenz":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, {"ok": True, "items": library(), "taste": taste_profile()})

    if path == "/api/gmail/connect":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        if not gmail_configured():
            return _json(400, {"ok": False, "error": "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET first."})
        return 302, "text/plain", b"", [("Location", gmail_connect_url(headers))]
    if path == "/api/gmail/callback":  # Google sends you back here; the state ties it to your own start
        q = lambda k: (query.get(k) or [""])[0]
        try:
            if q("error"):
                raise ValueError("You didn't allow access, so nothing changed.")
            who = gmail_finish_connect(q("code"), q("state"), headers)
            msg = f"Connected {who}. Theta can read your inbox now."
            store().set_meta("gmail:last_error", "")
        except (ValueError, LLMError) as e:
            msg = str(e)
            print(f"gmail connect failed: {msg[:300]}")  # in Vercel's logs, so a failed connect can be looked into
            store().set_meta("gmail:last_error", json.dumps({"at": time.time(), "why": msg[:300]}))
        store().set_meta("gmail:flash", msg[:200])
        return 302, "text/plain", b"", [("Location", "/settings#gmail")]

    if path == "/api/passkey/options":
        kind = query.get("type", ["login"])[0]
        if kind == "register" and not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        if not DASHBOARD_KEY:
            return _json(400, {"ok": False, "error": "set DASHBOARD_KEY first; with no key there's nothing to sign in to"})
        rp_id, _ = _rp(headers)
        return _json(200, {"ok": True, "challenge": new_challenge("create" if kind == "register" else "get"),
                           "rpId": rp_id, "userId": _b64u(hashlib.sha256(DASHBOARD_KEY.encode()).digest()[:16]),
                           "have": [k["id"] for k in passkeys()] if kind == "register" else []})

    if path == "/api/reminders":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, {"ok": True, "reminders": [dict(r, line=reminder_line(r)) for r in reminders()]})

    if path == "/api/head/hello":  # the Theta page's opening greeting
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        try:
            away = max(0.0, float(query.get("away", ["0"])[0]))
        except ValueError:
            away = 0.0
        return _json(200, {"ok": True, **head_hello(away)})

    if path == "/api/hbench":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        rows = _meta_json("hbench:last", {}).get("rows", [])
        return _json(200, {"ok": True, "rows": rows, "totals": hb_totals(rows), "sizes": prompt_sizes()})

    if path == "/api/bench":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, {"ok": True, **_meta_json("bench:last", {})})

    if path == "/api/lock/status":  # the app asks when it comes back to the front
        sess = current_session(headers)
        locked = bool(sess) and lock_check(sess, _REQ.sess_key)
        return _json(200, {"ok": True, "on": bool(sess and sess.get("lock")), "locked": locked})

    if path == "/api/chat/working":  # the chat polls this while it waits for a reply
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        note = _meta_json("chat:working", {}).get(query.get("rid", [""])[0])
        if not note:
            return _json(200, {"ok": True})
        now = time.time()
        started = note.get("started", note.get("at", now))
        return _json(200, {"ok": True, "agent": note.get("agent"), "name": note.get("name"),
                           "step": note.get("step", ""), "done": note.get("done", []),
                           "state": note.get("state", "working"), "started": started,
                           "updated": note.get("at", now), "elapsed": max(0, int(now - started))})

    if path == "/api/doctor":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        checks = doctor_checks()
        return _json(200, {"ok": True, "checks": checks, "summary": doctor_line(checks)})

    if path == "/api/wiring":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, {"ok": True, "agents": wiring(fresh=query.get("fresh", [""])[0] == "1")})

    if path == "/api/models":
        if not _auth_dashboard(query, headers):
            return _json(401, {"ok": False, "error": "dashboard key required"})
        return _json(200, {
            "in_use": {t: f"{p}: {m}" for t, (p, m) in TIER_LLM.items()},
            **{p: _list_models(p) for p in PROVIDERS},  # asked fresh: this is the diagnostic
        })

    if path == "/api/tiers":
        return _json(200, {
            "tiers": TIERS,
            "models": {t: (MODELS[t] or "unset") for t in TIERS},
        })

    return _json(404, {"ok": False, "error": "unknown route"})
