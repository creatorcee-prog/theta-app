"""Agent windows (Home cards).

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Agent windows: each agent's latest output as a small card with a
# short title and a picture. Round jobs save cards; after each round the
# titles are condensed (one cheap model call) and missing pictures are
# looked up on Wikipedia. The dashboard only reads what's stored.
WINDOW_TITLE_MAX = 48
SHORT_KEEP = 400  # condensed titles remembered
IMAGE_TTL = 7 * 86400  # how long a Wikipedia lookup is trusted
WIKI_UA = "Theta-dashboard/1.0 (https://github.com/creatorcee-prog/dashboard-app)"
_CARD_LOCK = threading.Lock()


def _meta_json(key, default):
    try:
        return json.loads(store().get_meta(key) or "null") or default
    except ValueError:
        return default


def save_card(agent, title, text="", image=None, url=None, source=None):
    """What an agent just put out, for its window on the dashboard."""
    with _CARD_LOCK:  # round jobs run in parallel threads
        cards = _meta_json("cards", {})
        cards[agent] = {"title": title[:300], "text": text[:600], "image": image, "url": url,
                        "source": source, "at": time.time()}
        store().set_meta("cards", json.dumps(cards))


def _title_key(title):
    return hashlib.sha1(" ".join(title.lower().split()).encode()).hexdigest()[:16]


def trim_title(title, source=None, limit=WINDOW_TITLE_MAX):
    """A token-free short title: drop the outlet's name and "BREAKING:"
    style prefixes, then cut at a word boundary."""
    t = " ".join(title.split())
    if source:
        t = re.sub(r"\s+[-–—|:]\s+" + re.escape(source) + r"\s*$", "", t, flags=re.I)
    t = re.sub(r"^(breaking( news)?|live( updates)?|watch|exclusive|update|just in|developing)"
               r"\s*[:|–—-]\s*", "", t, flags=re.I)
    if len(t) <= limit:
        return t
    cut = t[:limit + 1].rsplit(" ", 1)[0].rstrip(",;:–—-| ")
    return (cut or t[:limit]) + "…"


def condense_titles(titles):
    """One miner-model call: a widget title (6 words at most) and the main
    subject for each title not condensed yet. Returns how many it added."""
    cache = _meta_json("cards:short", {})
    todo = list(dict.fromkeys(t for t in titles if t and _title_key(t) not in cache))[:30]
    if not todo:
        return 0
    listing = "\n".join(f"{i}. {t}" for i, t in enumerate(todo, 1))
    reply = llm_chat("miner", [
        {"role": "system", "content": "You write titles for small dashboard widgets."},
        {"role": "user", "content": "For each numbered headline, write a widget title of at most 6 "
         "words that keeps the names and the key fact: no clickbait, no ending period, nothing "
         "invented. Then ' | ' and the one person, place, film, show, song or thing it is mainly "
         "about, written as its Wikipedia article title, or 'none'. One line per headline, like "
         "'1. title | subject'.\n\n" + listing}], max_tokens=1600)
    added = 0
    for line in reply.splitlines():
        m = re.match(r"\s*(\d+)[.)]\s*(.+?)\s*\|\s*(.*?)\s*$", line)
        if not m or not 0 < int(m[1]) <= len(todo):
            continue
        short, subject = m[2].strip(" *\"'"), m[3].strip(" *\"'")
        if not short or len(short) > 70:
            continue
        cache[_title_key(todo[int(m[1]) - 1])] = [
            short, "" if subject.lower() in ("", "none", "n/a") else subject[:80]]
        added += 1
    if added:
        store().set_meta("cards:short", json.dumps(dict(list(cache.items())[-SHORT_KEEP:])))
    return added


def wiki_image(subject):
    """(answered, url): a free-licensed picture of `subject` from Wikipedia.
    answered is False when Wikipedia couldn't be asked (so don't remember it)."""
    base = {"action": "query", "format": "json", "formatversion": "2", "prop": "pageimages",
            "piprop": "thumbnail", "pithumbsize": "800"}
    for extra in ({"redirects": "1", "titles": subject},
                  {"generator": "search", "gsrsearch": subject, "gsrlimit": "1"}):
        req = urllib.request.Request("https://en.wikipedia.org/w/api.php?" + urlencode({**base, **extra}),
                                     headers={"User-Agent": WIKI_UA})
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                pages = json.loads(resp.read()).get("query", {}).get("pages", [])
        except (urllib.error.URLError, TimeoutError, ValueError):
            return False, None
        for pg in pages:
            src = (pg.get("thumbnail") or {}).get("source")
            if src:
                return True, src
    return True, None


def find_images(subjects, limit=8):
    """Look up pictures for subjects not looked up lately (a few per round)."""
    cache, now = _meta_json("cards:img", {}), time.time()
    todo = [x for x in dict.fromkeys(subjects)
            if x and now - cache.get(x.lower(), ["", 0])[1] > IMAGE_TTL][:limit]
    if not todo:
        return 0
    found = 0
    with ThreadPoolExecutor(max_workers=len(todo)) as ex:
        for subject, (answered, url) in zip(todo, ex.map(wiki_image, todo)):
            if answered:
                cache[subject.lower()] = [url or "", now]
                found += bool(url)
    keep = sorted(cache.items(), key=lambda kv: kv[1][1])[-300:]
    store().set_meta("cards:img", json.dumps(dict(keep)))
    return found


def _first_line(text, limit=160):
    line = next((ln.strip() for ln in (text or "").splitlines() if ln.strip() and not ln.startswith("http")), "")
    return line if len(line) <= limit else line[:limit - 1].rsplit(" ", 1)[0] + "…"


def _tile_svg(c1, c2, big, small, top=""):
    """A generated picture: a gradient tile with big text (dates, totals)."""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 200"><defs><linearGradient id="t" '
           f'x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
           f'</linearGradient></defs><rect width="320" height="200" fill="url(#t)"/>'
           f'<circle cx="290" cy="20" r="90" fill="#fff" opacity=".08"/><circle cx="20" cy="210" r="70" fill="#fff" opacity=".07"/>'
           f'<g fill="#fff" font-family="-apple-system,Segoe UI,Roboto,sans-serif" text-anchor="middle">'
           f'<text x="160" y="58" font-size="20" font-weight="600" opacity=".85">{_x(top)}</text>'
           f'<text x="160" y="128" font-size="64" font-weight="800">{_x(big)}</text>'
           f'<text x="160" y="164" font-size="18" font-weight="600" opacity=".9">{_x(small)}</text></g></svg>')
    return "data:image/svg+xml;charset=utf-8," + quote(svg)


def _bars_svg(c1, c2, rows):
    """A generated picture: budget bars (spent share per category)."""
    bars = []
    for i, (label, frac) in enumerate(rows[:4]):
        y = 34 + i * 40
        w = max(4, min(frac, 1) * 200)
        bars.append(f'<text x="24" y="{y + 15}" font-size="14" font-weight="600">{_x(label[:12])}</text>'
                    f'<rect x="110" y="{y + 2}" width="200" height="16" rx="8" fill="#fff" opacity=".22"/>'
                    f'<rect x="110" y="{y + 2}" width="{w:.0f}" height="16" rx="8" fill="#fff" '
                    f'opacity="{1 if frac < 1 else .95}"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 200"><defs><linearGradient id="t" '
           f'x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
           f'</linearGradient></defs><rect width="320" height="200" fill="url(#t)"/>'
           f'<g fill="#fff" font-family="-apple-system,Segoe UI,Roboto,sans-serif">{"".join(bars)}</g></svg>')
    return "data:image/svg+xml;charset=utf-8," + quote(svg)


def _win(agent, raw, sub="", image=None, href=None, at=None, tag=None, source=None, external=False, title=None,
         fit=False, text="", links=None, coverage=None):
    """One window. raw: the full title (condensed later); title: already short;
    fit: show the whole picture (charts) instead of filling the frame; text,
    links and coverage fill the sheet that opens when it's tapped."""
    url = href if external else None
    return {"agent": agent, "raw": raw, "title": title, "sub": sub, "image": image,
            "href": href or f"/agent/{agent}", "at": at, "tag": tag, "source": source,
            "external": external, "fit": fit, "text": text,
            "links": links if links is not None else ([[source or "Open", url]] if url else []),
            "coverage": coverage, "site": urlparse(url).netloc if url else ""}


def story_coverage(title):
    """Which of Red's, Gray's and Blue's outlets carried this story."""
    return {a: sorted({it["source"] for it in side_coverage(a, title, limit=20)}) for a in ("red", "gray", "blue")}


def _latest_post(chat, agent, with_image=False):
    for m in reversed(chat):
        if m["from"] == agent and m.get("kind") != "event" and (m.get("image") or not with_image):
            return m
    return None


def _at(stamp):
    """Epoch seconds from a stored "YYYY-MM-DD HH:MM:SS" UTC stamp."""
    try:
        return datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def remi_reminders(w, rems, look):
    """Remi's window leads with a reminder you haven't marked done, and
    its sheet lists your reminders with Done buttons and an add box."""
    pending = [r for r in rems if r.get("pending")]
    nxt = next((r for r in rems if not r.get("pending")), None)
    if pending:
        r = pending[0]
        w.update(raw=f"Still to do: {r['what']}", title=None, tag="Reminder", href=REMINDER_URL,
                 sub=f"{len(pending)} waiting for Done" if len(pending) > 1 else "Tap Done when it's handled")
    elif nxt and nxt["at"] - time.time() < 6 * 3600 and not w.get("sub", "").startswith("Today"):
        when = datetime.fromtimestamp(nxt["at"], hub_tz())
        w.update(raw=nxt["what"], title=None, tag="Reminder", sub=f"Reminder · {_clock(when)}", href=REMINDER_URL)
    lines = [reminder_line(r).split(" ", 1)[1] for r in rems[:6]]
    w["text"] = "\n".join(x for x in [("Reminders:\n" + "\n".join(lines)) if lines else "", w.get("text") or ""] if x)
    w["remind"] = {"pending": [[r["id"], r["what"]] for r in pending]}
    w["links"] = [["All reminders", REMINDER_URL]] + [l for l in (w.get("links") or []) if l[1] != REMINDER_URL]
    if gmail_connected():
        drafts = [t for t in mail_threads().values() if t.get("status") == "draft"]
        if drafts and not pending:
            w.update(raw=f"{len(drafts)} email repl{'y' if len(drafts) == 1 else 'ies'} to check", title=None,
                     tag="Email", href="/mail", sub="Remi drafted them; nothing sends until you tap Send")
        w["links"].append(["Email", "/mail"])


def agent_windows(chat=None, cards=None):
    """A window for every agent, from saved cards, then live data, then
    their latest post. No model calls."""
    chat = store().list_chat(ALLCHAT_KEEP) if chat is None else chat
    cards = _meta_json("cards", {}) if cards is None else cards
    out = {}
    for a in ("red", "blue", "gray"):
        c = cards.get(a)
        if c:
            urls = re.findall(r"https?://\S+", c["text"])
            links = [[c.get("source") or "Story", c["url"]]] if c.get("url") else []
            links += [[urlparse(u).netloc.removeprefix("www."), u] for u in urls if u != c.get("url")]
            out[a] = _win(a, c["title"], _first_line(c["text"]), c.get("image"), c.get("url"), c["at"],
                          source=c.get("source"), external=bool(c.get("url")),
                          text=re.sub(r"\s*https?://\S+", "", c["text"]).strip(), links=links,
                          coverage=story_coverage(c["title"]))
        else:
            heads = side_headlines(a, 1)
            if heads:
                h = heads[0]
                out[a] = _win(a, h["title"], f"Top story at {h['source']}", h.get("image"), h["url"],
                              h.get("published"), source=h["source"], external=True, text=h.get("summary", ""),
                              coverage=story_coverage(h["title"]))
            else:
                out[a] = _win(a, "", "Their outlets have nothing new", title="No headlines yet")
    c = cards.get("lenz")
    if c:
        out["lenz"] = _win("lenz", c["title"], _first_line(c["text"]), c.get("image"), c.get("url"), c["at"],
                           external=bool(c.get("url")), text=re.sub(r"\s*https?://\S+", "", c["text"]).strip())
    else:
        try:
            pick = (tmdb_trending() or [None])[0]
        except LLMError:
            pick = None
        if pick:
            out["lenz"] = _win("lenz", pick["title"], f"Trending {pick['kind'].lower()}"
                               + (f" · {pick['rating']}/10" if pick["rating"] else ""), pick.get("image"),
                               pick["url"], external=True, text=pick.get("overview", ""), source="TMDB")
        else:
            feed = widget_items(ENTERTAINMENT_FEEDS)
            pick = next((w for w in feed if w.get("kind") == "song"), None) or next(iter(feed), None)
            out["lenz"] = (_win("lenz", pick["title"], "Most played right now" if pick.get("kind") == "song"
                                else f"New at {pick['source']}", pick.get("image"), pick["url"], external=True,
                                text=pick.get("summary", ""), source=pick["source"])
                           if pick else _win("lenz", "", "Nothing trending yet", title="Nothing to pitch yet"))
    look = AGENT_LOOKS
    month = datetime.now(hub_tz()).strftime("%Y-%m")
    status = month_status(month)
    spent = sum(v["spent"] for v in status.values())
    budget = sum(v["budget"] or 0 for v in status.values())
    hot = sorted(((v["spent"] / v["budget"], k) for k, v in status.items() if v["budget"]), reverse=True)
    if hot and hot[0][0] >= 0.9:
        g_title = f"{hot[0][1]} {'over budget' if hot[0][0] >= 1 else f'at {hot[0][0]:.0%}'}"
    elif spent:
        g_title = f"${spent:,.0f} spent in {datetime.now(hub_tz()):%B}"
    else:
        g_title = "No spending logged yet"
    g_sub = (f"{spent / budget:.0%} of ${budget:,.0f} budgeted" if budget else
             "Set GLASS_BUDGETS or import a Rocket Money export")
    g_img = (_bars_svg(look["glass"][0], look["glass"][1], [(k, f) for f, k in hot]) if hot else
             _tile_svg(look["glass"][0], look["glass"][1], f"${spent:,.0f}", "this month", f"{datetime.now(hub_tz()):%B}"))
    out["glass"] = _win("glass", "", g_sub, g_img, "/money", title=g_title,
                        text="\n".join(status_lines(month)) or "Nothing logged this month.",
                        links=[["Open Money", "/money"]])
    today = datetime.now(hub_tz()).date()
    rems = reminders()
    if calendar_linked():
        try:
            soon = calendar_events(today, today + timedelta(days=14))
        except Exception:
            soon = []
        now_dt = datetime.now(hub_tz())
        upcoming = [o for o in soon if (o["start"] if o["all_day"] else o["start"]) >=
                    (today if o["all_day"] else now_dt)] if soon else []
        todays = [o for o in soon if (o["start"] if o["all_day"] else o["start"].date()) == today]
        if upcoming:
            o = upcoming[0]
            d = o["start"] if o["all_day"] else o["start"].date()
            when = "Today" if d == today else "Tomorrow" if d == today + timedelta(days=1) else f"{d:%a %b} {d.day}"
            out["remi"] = _win("remi", o["title"], f"{when}{'' if o['all_day'] else ' · ' + _clock(o['start'])}"
                               f" · {len(todays)} on today", _tile_svg(look["remi"][0], look["remi"][1],
                               str(d.day), when if when in ("Today", "Tomorrow") else f"{d:%A}", f"{d:%B}"),
                               "/calendar", text="\n".join(occurrence_text(x, with_day=True) for x in upcoming[:8]),
                               links=[["Open the calendar", "/calendar"]])
        else:
            out["remi"] = _win("remi", "", "Nothing in the next two weeks", _tile_svg(
                look["remi"][0], look["remi"][1], str(today.day), f"{today:%A}", f"{today:%B}"),
                "/calendar", title="A clear calendar")
    else:
        out["remi"] = _win("remi", "", "Link your Google Calendar to see what's next", _tile_svg(
            look["remi"][0], look["remi"][1], str(today.day), f"{today:%A}", f"{today:%B}"),
            "/calendar", title="No calendar linked")
    remi_reminders(out["remi"], rems, look)
    chart = _latest_post(chat, "charter", with_image=True)
    if chart:
        out["charter"] = _win("charter", chart["text"], "Latest chart", chart["image"], at=_at(chart["at"]), fit=True,
                              text=chart["text"], links=[["Open the chart", chart["image"]]])
    elif spent:
        caption, svg = _chart_spending(month)
        out["charter"] = _win("charter", caption, "Ask me for any chart",
                              "data:image/svg+xml;charset=utf-8," + quote(svg), fit=True)
    else:
        out["charter"] = _win("charter", "", "Ask in #money: \"@charter chart my spending\"",
                              title="No charts yet")
    for a, idle in (("mistral", "Digest and alerts land here"), ("theta", "Reviews and decisions land here")):
        c = cards.get(a)
        post = _latest_post(chat, a)
        if c:
            out[a] = _win(a, c["title"], _first_line(c["text"]), c.get("image"), c.get("url"), c["at"],
                          external=bool(c.get("url")), text=c["text"], source=c.get("source"))
        elif post:
            out[a] = _win(a, _first_line(post["text"], 300), "", at=_at(post["at"]), text=post["text"])
        else:
            out[a] = _win(a, "", idle, title="Nothing yet")
    j = james_summary()
    james_img = f"{GARAGE_GYM_URL}/james.png" if GARAGE_GYM_URL else None
    fit = None if j else next(iter(store().list_fitness(1)), None)
    if fit and isinstance(fit.get("summary"), dict) and fit["summary"]:
        k, v = next(iter(fit["summary"].items()))
        out["james"] = _win("james", "", f"From {display_name(fit['bot_id'])}", james_img,
                            at=_at(fit["created_at"]), title=f"{k}: {v}"[:60])
    elif j and j.get("summary"):
        lines = [ln.strip("-• ") for ln in j["summary"].splitlines() if ln.strip()]
        out["james"] = _win("james", next((ln for ln in lines if any(ch.isdigit() for ch in ln)), lines[0]),
                            "From Garage Gym", james_img, text=j["summary"],
                            links=[["Open Garage Gym", FITNESS_APP_URL]] if FITNESS_APP_URL else [])
    else:
        out["james"] = _win("james", "", "Link Garage Gym to see your training" if not GARAGE_GYM_SECRET
                            else "Garage Gym hasn't answered yet", james_img, title="Training")
    try:
        findings = watchdog_findings()
    except Exception:
        findings = None
    q1, q2 = AGENT_LOOKS["qwerty"][:2]
    if findings is None:
        out["qwerty"] = _win("qwerty", "", "Couldn't check just now", href="/diagnostics#security", title="Watchdog")
    else:
        worst = [t for sv, t in findings if sv == "high"] or [t for sv, t in findings if sv == "warn"]
        out["qwerty"] = _win("qwerty", "", worst[0] if worst else "QWERTY's checks flagged nothing",
                             _tile_svg(q1, q2, "OK" if not worst else str(len(worst)),
                                       "all clear" if not worst else ("thing to fix" if len(worst) == 1 else "things to fix"),
                                       "Watchdog"), "/diagnostics#security",
                             title="All clear" if not worst else f"{len(worst)} thing{'s' if len(worst) != 1 else ''} to look at",
                             text="\n".join(f"[{sv}] {t}" for sv, t in findings) or "All clear.",
                             links=[["Open Security", "/diagnostics#security"]])
    if "lenz" in out:  # Lenz's window opens his library
        now_on = [x for x in library() if x["status"] == "current"]
        out["lenz"].update(href="/lenz", external=False, nosheet=True,
                           sub=(f"On the go: {now_on[0]['title']}" + (f" (+{len(now_on) - 1} more)" if len(now_on) > 1 else ""))
                           if now_on else out["lenz"]["sub"])
    return [out[a] for a in AGENTS if a in out]


def _pushed_windows(event_type):
    """Items bots sent with /api/report, as windows from that bot."""
    out = []
    for r in store().list_reports(50, event_type=event_type):
        p = r["payload"]
        if isinstance(p, dict) and p.get("title"):
            bot = r["bot_id"] if r["bot_id"] in AGENTS else ""
            out.append(_win(bot, p["title"], f"From {display_name(r['bot_id'])}", p.get("image"),
                            p.get("url") or (f"/agent/{bot}" if bot else "/settings"), _at(r["created_at"]),
                            source=p.get("source") if bot else display_name(r["bot_id"]), external=bool(p.get("url"))))
        if len(out) >= 6:
            break
    return out


def news_windows():
    breaking, top = news_items()
    briefs = _meta_json("briefs", {})  # stories the bots have read
    return [_win("", it["title"], "", it.get("image"), it["url"], it.get("published"),
                 tag="Breaking" if it in breaking else None, source=it["source"], external=True,
                 text=brief_text(briefs[it["url"]]) if it["url"] in briefs else it.get("summary", ""),
                 coverage=story_coverage(it["title"]))
            for it in breaking + top] + _pushed_windows("news")


def trending_windows():
    out = _pushed_windows("entertainment")
    try:
        for it in tmdb_trending()[:6]:
            out.append(_win("lenz", it["title"], it["kind"] + (f" · {it['rating']}/10" if it["rating"] else ""),
                            it.get("image"), it["url"], external=True, text=it.get("overview", ""), source="TMDB"))
    except LLMError:
        pass
    for it in widget_items(ENTERTAINMENT_FEEDS):
        if len(out) >= 12:
            break
        out.append(_win("lenz", it["title"], "Most played song" if it.get("kind") == "song" else it["source"],
                        it.get("image"), it["url"], external=True, text=it.get("summary", ""),
                        source="Apple Music" if it.get("kind") == "song" else it["source"]))
    return out


def finish_windows(wins, shorts=None, images=None):
    """Short titles and looked-up pictures for windows, from the caches."""
    shorts = _meta_json("cards:short", {}) if shorts is None else shorts
    images = _meta_json("cards:img", {}) if images is None else images
    for w in wins:
        hit = shorts.get(_title_key(w["raw"])) if w["raw"] else None
        if not w["title"]:
            w["title"] = hit[0] if hit and hit[0] else trim_title(w["raw"], w.get("source"))
        if not w["image"] and hit and hit[1]:
            w["image"] = (images.get(hit[1].lower()) or [None])[0] or None
    return wins


def refresh_windows(deadline=None):
    """After a round: condense new titles and find pictures for windows
    that have none, skipping a step that might not finish by `deadline`
    (the round must end inside Vercel's time limit; the next round
    catches up). Returns a short note, or "" when nothing changed."""
    deadline = deadline or time.time() + 60
    wins = agent_windows() + news_windows() + trending_windows()
    added = found = 0
    if time.time() < deadline - LLM_TIMEOUT - 2:
        added = condense_titles([w["raw"] for w in wins if w["raw"] and not w["title"]])
    if time.time() < deadline - 14:  # one batch of lookups: 2 tries x 6 s
        shorts = _meta_json("cards:short", {})
        subjects = [shorts.get(_title_key(w["raw"]), ["", ""])[1] for w in wins if w["raw"] and not w["image"]]
        found = find_images([x for x in subjects if x], limit=6)
    bits = ([f"{added} new window title{'s' if added != 1 else ''}"] if added else []) + (
        [f"{found} picture{'s' if found != 1 else ''}"] if found else [])
    return ", ".join(bits)
