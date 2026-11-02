"""Lenz's library: what you watch, play and read.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Lenz's library: everything you watch, play and read, with your
# progress, ratings and rankings. Imported from your log (a Google Doc's
# text, pasted or synced from LENZ_DOC_URL) and kept here after that.
# MyAnimeList (MAL_CLIENT_ID + MAL_USERNAME) syncs your anime list in.
KINDS = {"G": "game", "AN": "anime", "S": "show", "M": "movie", "MW": "manhwa", "WN": "web novel",
         "B": "book", "C": "comic", "P": "musical", "MANGA": "manga"}
KIND_LABELS = {"game": "Game", "anime": "Anime", "show": "TV", "movie": "Movie", "manhwa": "Manhwa",
               "web novel": "Web novel", "book": "Book", "comic": "Comic", "musical": "Musical", "manga": "Manga"}
STATUSES = {"current": "Now", "queue": "Up next", "waiting": "Waiting", "done": "Finished",
            "paused": "Paused", "dropped": "Dropped"}
LENZ_DOC_URL = os.environ.get("LENZ_DOC_URL", "")
_LIB_LOCK = threading.Lock()
_CODE = r"(?:AN|MW|WN|MANGA|G|S|M|B|C|P)"
_NOTE_START = re.compile(
    r"^(waiting|updates|stopped|cannot|multiple|manga only|ongoing|light novel|obscure|limited|too vague|"
    r"does not|children|experimental|chinese|high fan|adult swim|\d{4} |early|read |rewatch)", re.I)
_PROGRESS = re.compile(r"^(?:ep|eps|episode|ch|chapter|vol|volume|season|s\d+)\b", re.I)


def _norm_title(title):
    t = re.sub(r"^(the|a|an) ", "", title.lower().replace("’", "'"))
    return re.sub(r"[^a-z0-9]", "", t)


def parse_media_line(line):
    """One line of the log -> {title, kind, progress, with, note, times,
    scores, eps, hours, price, paused}. Unknown bits stay in the title."""
    s = " " + line.replace("’", "'").strip() + " "
    out = {"kind": None, "progress": "", "with": "", "notes": [], "times": 0, "scores": {}, "eps": None,
           "hours": None, "price": "", "paused": False}

    def cut(pattern, flags=re.I):
        nonlocal s
        found = list(re.finditer(pattern, s, flags))
        for m in reversed(found):
            s = s[:m.start()] + " " + s[m.end():]
        return found
    for m in cut(r"\(\s*w/\s*([^)]*)\)"):
        inner = m.group(1)
        p = re.search(r"(?:S\d+\s*)?Ep\s*\d+", inner, re.I)
        if p:
            out["progress"] = p.group(0)
            inner = inner.replace(p.group(0), "")
        out["with"] = " ".join(inner.split()).strip(" ,")
    codes = cut(r"\(\s*(" + _CODE + r"(?:\s*[+/]\s*" + _CODE + r")?)\s*\??\s*\)")
    codes += cut(r"(?<=\s)-\s*(" + _CODE + r"(?:\s*[+/]\s*" + _CODE + r")?)(?=[\s\dx+]*$)")
    if codes:
        out["kind"] = KINDS.get(re.split(r"[+/]", codes[-1].group(1))[0].strip().upper())
    times = [int(m.group(1)) for m in cut(r"\b(\d{1,2})x\+?(?=\s|$)")]
    out["times"] = max(times) if times else 0
    for m in cut(r"\$(\d+)"):
        out["price"] = f"${m.group(1)}"
    for m in cut(r"\b(IMDB|MAL)\s*(\d{1,2}(?:\.\d)?)(?:\s*[/,])?", flags=0):
        out["scores"][m.group(1)] = float(m.group(2))
    for m in cut(r"\(\s*(Movie|~?\d+\+?\s*eps)\b([^)]*)\)"):
        if m.group(1).lower() == "movie":
            out["kind"] = out["kind"] or "movie"
        else:
            out["eps"] = int(re.sub(r"\D", "", m.group(1)))
        h = re.search(r"([\d.]+)\s*hrs", m.group(0))
        out["hours"] = float(h.group(1)) if h else None
    for m in cut(r"\(\s*([\d.]+)\s*hrs\)"):
        out["hours"] = float(m.group(1))
    for m in cut(r"\(?\bstopped at ([^)\-]*?)\)?(?=\s-|\s*$)"):
        out["notes"].append(f"Stopped at {m.group(1).strip()}")
        out["paused"] = True
    for m in cut(r"\((rewatch|read [^)]*|sub|dub|netflix|youtube|adult swim|as of [^)]*|ongoing [^)]*|"
                 r"unknown[^)]*|\d{4}s)\)"):
        out["notes"].append(m.group(1).strip().capitalize())
    segs = [x.strip(" -") for x in re.split(r"\s+-\s*|\s*-\s+", s.strip())]
    segs = [x for x in segs if x]
    title = segs[0] if segs else ""
    for seg in segs[1:]:
        if _PROGRESS.match(seg) and not out["progress"]:
            out["progress"] = seg
        elif _NOTE_START.match(seg):
            out["notes"].append(seg.rstrip("."))
        else:
            title += " - " + seg
    title = re.sub(r"^watching\s+", "", title, flags=re.I)
    m = re.search(r"\s((?:S\d+\s*)?Ep\s*\d+\??)$", title, re.I)  # "Old Country Bumpkin ... Ep 5"
    if m and not out["progress"]:
        out["progress"], title = m.group(1), title[:m.start()]
    out["title"] = " ".join(title.split()).strip(" -:,")
    out["note"] = "; ".join(out.pop("notes"))
    return out


_HEADINGS = [
    (r"^key\b", {"section": "key"}),
    (r"^waiting for new", {"section": "waiting"}),
    (r"^current\b", {"section": "current"}),
    (r"^in queue\b", {"section": "queue"}),
    (r"^overall rankings\b", {"section": "ranked"}),
    (r"^rankings\b", {"section": "done"}),
    (r"^most beloved\b", {"section": "beloved"}),
    (r"^games?$", {"medium": "game"}),
    (r"^video$", {"medium": "video"}),
    (r"^text$", {"medium": "text"}),
    (r"^([sabcd])-tier\b", {"tier": 1}),
    (r"^anime$", {"kind": "anime"}),
    (r"^tv series", {"kind": "show"}),
    (r"^movies\b", {"kind": "movie"}),
    (r"^(family|main|other)$", {"group": 1}),
]


def parse_media_log(text):
    """A log like your Google Doc ("Current", "In Queue", "Rankings",
    "Overall Rankings", type codes like (AN)) -> list of entries."""
    state = {"section": None, "medium": None, "tier": None, "kind": None, "group": None}
    out, parent_indent, last = [], None, None
    for raw in text.replace("﻿", "").splitlines():
        if not raw.strip() or re.match(r"^\s*[_\-=]{4,}\s*$", raw) or "end list" in raw:
            continue
        indent = len(raw) - len(raw.lstrip())
        m = re.match(r"^\s*(?:[*•●○■-]|\d+\.)\s+(.*)$", raw)
        item = m is not None
        content = (m.group(1) if m else raw).strip().lstrip("#").strip()
        bare = re.sub(r"\s*\(.*$", "", content).strip(" :").lower()
        head = next(((pat, upd) for pat, upd in _HEADINGS if re.match(pat, bare)), None)
        if head and (not item or bare in ("family", "main", "other", "tv series")):
            hm = re.match(head[0], bare)
            for k, v in head[1].items():
                state[k] = hm.group(1).upper() if (v == 1 and k == "tier") else (
                    hm.group(1).title() if v == 1 else v)
            if "section" in head[1]:
                state.update(medium=None, tier=None, kind=None, group=None)
            if "medium" in head[1]:
                state.update(kind=None, group=None)
            if "tier" in head[1]:
                state["kind"] = None
            parent_indent = indent if "group" in head[1] else None
            last = None
            continue
        sec = state["section"]
        if sec in (None, "key") or (not item and sec != "beloved"):
            continue  # descriptions like "Highest quality shows - worth prioritizing"
        if last is not None and item and indent > (last["_indent"]):
            last["note"] = "; ".join(x for x in (last["note"], content.strip()) if x)  # a nested detail
            continue
        e = parse_media_line(content)
        if not e["title"]:
            continue
        e["kind"] = e["kind"] or state["kind"] or {"game": "game"}.get(state["medium"]) or (
            ("anime" if "MAL" in e["scores"] else "show") if e["eps"] else None)
        e.update(status={"waiting": "waiting", "current": "current", "queue": "queue", "done": "done",
                         "ranked": "done", "beloved": "done"}[sec], tier=state["tier"] if sec == "queue" else None,
                 group=state["group"] if sec == "current" else None, rank=None, beloved=sec == "beloved",
                 _indent=indent)
        if e["paused"] and e["status"] == "done":
            e["status"] = "paused"
        if sec == "ranked":
            e["rank"] = sum(1 for x in out if x.get("rank")) + 1
        out.append(e)
        last = e
    for e in out:
        e.pop("_indent", None)
        e.pop("paused", None)
    return out


def library():
    return _meta_json("lenz:lib", [])


def _save_library(lib):
    store().set_meta("lenz:lib", json.dumps(lib))


_STATUS_RANK = {"current": 5, "waiting": 4, "paused": 3, "queue": 2, "done": 1, "dropped": 0}


def merge_into_library(entries, source="import"):
    """Add or update entries by title. Your ratings and finish dates are
    never overwritten; a title in several sections keeps its liveliest
    status (watching beats waiting beats up next beats finished)."""
    with _LIB_LOCK:
        lib = library()
        by_key = {_norm_title(x["title"]): x for x in lib}
        added = updated = 0
        for e in entries:
            key = _norm_title(e["title"])
            if not key:
                continue
            cur = by_key.get(key)
            if not cur:
                cur = {"id": max([x["id"] for x in lib] + [0]) + 1, "title": e["title"], "kind": e.get("kind"),
                       "status": e.get("status", "queue"), "progress": "", "with": "", "note": "", "times": 0,
                       "rank": None, "tier": None, "group": None, "rating": None, "beloved": False, "scores": {},
                       "eps": None, "hours": None, "price": "", "added": time.time(), "updated": time.time(),
                       "done_at": None, "source": source}
                lib.append(cur)
                by_key[key] = cur
                added += 1
            else:
                updated += 1
                # What you set here (finished, started...) beats an older log.
                if not cur.get("pinned") and _STATUS_RANK.get(e.get("status"), 0) > _STATUS_RANK.get(cur["status"], 0):
                    cur["status"] = e["status"]
            for k in ("kind", "progress", "with", "note", "tier", "group", "price", "eps", "hours"):
                if e.get(k) and not cur.get(k):
                    cur[k] = e[k]
            for k in ("progress", "with", "note", "group") if e.get("status") == "current" and not cur.get("pinned") else ():
                if e.get(k):
                    cur[k] = e[k]
            cur["times"] = max(cur.get("times") or 0, e.get("times") or 0)
            cur["scores"] = {**(cur.get("scores") or {}), **(e.get("scores") or {})}
            if e.get("rank"):
                cur["rank"] = e["rank"]
            if e.get("beloved"):
                cur["beloved"] = True
            if e.get("rating") and not cur.get("rating"):
                cur["rating"] = e["rating"]
            for k in ("mal_id", "image", "genres"):
                if e.get(k) and not cur.get(k):
                    cur[k] = e[k]
        _save_library(lib)
    return {"added": added, "updated": updated, "total": len(lib)}


def update_library_item(iid, action, value=None):
    """watched (value: rating or None), start, next (+1 episode/chapter),
    rate, status, delete. Returns the item (or None) and a note for chat."""
    with _LIB_LOCK:
        lib = library()
        it = next((x for x in lib if x["id"] == iid), None)
        if not it:
            return None
        it["updated"] = time.time()
        if action in ("watched", "start", "status", "next"):
            it["pinned"] = True  # set here, so a re-imported log won't undo it
        if action == "delete":
            lib.remove(it)
        elif action == "watched":
            it.update(status="done", done_at=time.time(), times=(it.get("times") or 0) + (1 if it["status"] == "done" else 0))
            if value is not None:
                it["rating"] = max(1, min(10, int(value)))
        elif action == "rate":
            it["rating"] = max(1, min(10, int(value)))
        elif action == "start":
            it["status"] = "current"
        elif action == "status" and value in STATUSES:
            it["status"] = value
        elif action == "next":
            m = re.search(r"(\d+)(?!.*\d)", it.get("progress") or "")
            unit = "Ch" if it.get("kind") in ("manhwa", "manga", "comic", "web novel", "book") else "Ep"
            if m:
                it["progress"] = it["progress"][:m.start()] + str(int(m.group(1)) + 1) + it["progress"][m.end():]
            else:
                it["progress"] = f"{unit} 1"
        _save_library(lib)
    return it


def add_library_item(title, kind=None, status="queue"):
    r = merge_into_library([{"title": title.strip()[:160], "kind": kind if kind in KIND_LABELS else None,
                             "status": status if status in STATUSES else "queue"}], source="added")
    return next((x for x in library() if _norm_title(x["title"]) == _norm_title(title)), None), r


def taste_profile(lib=None, since=None):
    """What your log says about your taste: counts and average rating per
    kind, top-rated, and (with `since`) what you finished after it."""
    lib = library() if lib is None else lib
    done = [x for x in lib if x["status"] == "done"]
    kinds = {}
    for x in done:
        k = kinds.setdefault(x.get("kind") or "other", {"n": 0, "rated": []})
        k["n"] += 1
        if x.get("rating"):
            k["rated"].append(x["rating"])
    genres = {}
    for x in done:
        for g in x.get("genres") or []:
            genres[g] = genres.get(g, 0) + (x.get("rating") or 6)
    recent = [x for x in done if since and (x.get("done_at") or 0) >= since]
    return {"finished": len(done), "rated": sum(1 for x in done if x.get("rating")),
            "kinds": {k: {"n": v["n"], "avg": round(sum(v["rated"]) / len(v["rated"]), 1) if v["rated"] else None}
                      for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]["n"])},
            "genres": [g for g, _ in sorted(genres.items(), key=lambda kv: -kv[1])[:6]],
            "top": [x["title"] for x in sorted(done, key=lambda x: (-(x.get("rating") or 0), x.get("rank") or 999))[:5]],
            "recent": [{"title": x["title"], "rating": x.get("rating"), "kind": x.get("kind")} for x in recent]}


def sync_library_doc():
    """Re-import LENZ_DOC_URL (a Google Doc shared "anyone with the link")."""
    if not LENZ_DOC_URL:
        return None
    m = re.search(r"/document/d/([\w-]+)", LENZ_DOC_URL)
    url = f"https://docs.google.com/document/d/{m.group(1)}/export?format=txt" if m else LENZ_DOC_URL
    try:
        text = _fetch_url(url, timeout=10).decode("utf-8", "replace")
    except Exception as e:
        raise LLMError(f"couldn't read LENZ_DOC_URL ({str(e)[:80]}); is the doc shared 'anyone with the link'?")
    if "<html" in text[:500].lower():
        raise LLMError("LENZ_DOC_URL gave a web page, not the doc's text; share it 'anyone with the link'")
    return merge_into_library(parse_media_log(text), source="doc")


MAL_CLIENT_ID = os.environ.get("MAL_CLIENT_ID", "")
MAL_USERNAME = os.environ.get("MAL_USERNAME", "")
LENZ_NEWS_FEEDS = [u.strip() for u in os.environ.get(
    "LENZ_NEWS_FEEDS",
    "https://myanimelist.net/rss/news.xml,https://feeds.feedburner.com/ign/games-all,"
    "https://www.gamespot.com/feeds/game-news,https://www.polygon.com/rss/index.xml").split(",") if u.strip()]
_MAL_STATUS = {"watching": "current", "reading": "current", "completed": "done", "on_hold": "paused",
               "dropped": "dropped", "plan_to_watch": "queue", "plan_to_read": "queue"}


def lenz_channels_context():
    """Lenz's own channel setup, exactly as the hub sees it."""
    last = float(store().get_meta("lenz:feeds:at") or 0)
    known = _meta_json("lenz:yt:ids", {})
    yt = [c + ("" if c.startswith("UC") or c in known else
               " (not looked up yet" + ("" if YOUTUBE_API_KEY else ": YOUTUBE_API_KEY isn't set") + ")")
          for c in LENZ_YOUTUBE]
    return ("\n\nYour channels (exact, from the hub's settings):\n"
            f"- YouTube (LENZ_YOUTUBE): {', '.join(yt) if yt else 'none set'}\n"
            f"- Subreddits (LENZ_SUBREDDITS): {', '.join(LENZ_SUBREDDITS) or 'none set'}\n"
            f"- Twitch (LENZ_TWITCH): {', '.join(LENZ_TWITCH) or 'none set'}"
            + ("" if not LENZ_TWITCH or (TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET) else
               " (TWITCH_CLIENT_ID/SECRET not set, so not checked)") + "\n"
            f"- Last checked: {_when(last) if last else 'never yet'}; checked every {LENZ_FEEDS_MINUTES} min. "
            "The first check only records what's there; new posts show from the next one.")


def lenz_context():
    """The user's library, for Lenz's prompt: what they're on, waiting for,
    their favorites and ratings, so his picks fit their taste."""
    lib = library()
    if not lib:
        return lenz_channels_context()
    by = lambda st: [x for x in lib if x["status"] == st]
    fmt = lambda x: x["title"] + (f" ({KIND_LABELS.get(x.get('kind'), '')}, {x['progress']})" if x.get("progress") else
                                  f" ({KIND_LABELS.get(x.get('kind'), '')})" if x.get("kind") else "")
    ranked = sorted((x for x in lib if x.get("rank")), key=lambda x: x["rank"])[:15]
    rated = sorted((x for x in lib if x.get("rating")), key=lambda x: -x["rating"])[:10]
    prof = taste_profile(lib)
    parts = ["\n\nThe user's library (exact; it's theirs, so use it to fit picks to their taste):",
             "Watching/playing/reading now: " + "; ".join(fmt(x) for x in by("current")[:20]),
             "Waiting on new seasons: " + "; ".join(x["title"] for x in by("waiting")[:15]),
             "Their all-time favorites, in order: " + "; ".join(x["title"] for x in ranked)]
    if rated:
        parts.append("Their ratings: " + "; ".join(f"{x['title']} {x['rating']}/10" for x in rated))
    if prof["genres"]:
        parts.append("Genres they rate highest: " + ", ".join(prof["genres"]))
    parts.append(f"Up next: {len(by('queue'))} titles. Finished: {prof['finished']}, {prof['rated']} rated.")
    return "\n".join(p for p in parts if not p.endswith(": ")) + lenz_channels_context()


def mal_entries():
    """Your MyAnimeList anime and manga lists (public lists, read with
    MAL_CLIENT_ID; no password needed)."""
    if not (MAL_CLIENT_ID and MAL_USERNAME):
        return []
    out = []
    for kind, path in (("anime", "animelist"), ("manga", "mangalist")):
        fields = "list_status,genres,mean,media_type," + ("num_episodes" if kind == "anime" else "num_chapters")
        url = (f"https://api.myanimelist.net/v2/users/{quote(MAL_USERNAME)}/{path}?"
               + urlencode({"fields": fields, "limit": "1000", "nsfw": "true"}))
        req = urllib.request.Request(url, headers={"X-MAL-CLIENT-ID": MAL_CLIENT_ID, "User-Agent": WIKI_UA})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read()).get("data", [])
        except urllib.error.HTTPError as e:
            raise LLMError(f"MyAnimeList returned {e.code}: check MAL_CLIENT_ID, and that "
                           f"{MAL_USERNAME}'s list is public")
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise LLMError(f"MyAnimeList unreachable: {e!r}")
        for row in data:
            node, ls = row.get("node", {}), row.get("list_status", {})
            done_n = ls.get("num_episodes_watched") or ls.get("num_chapters_read") or 0
            mt = node.get("media_type") or ""
            out.append({"title": node.get("title", ""), "status": _MAL_STATUS.get(ls.get("status"), "queue"),
                        "kind": "anime" if kind == "anime" else ("manhwa" if mt == "manhwa" else
                                                                  "web novel" if mt in ("novel", "light_novel") else "manga"),
                        "progress": (f"{'Ep' if kind == 'anime' else 'Ch'} {done_n}" if done_n else ""),
                        "rating": ls.get("score") or None, "mal_id": node.get("id"),
                        "image": (node.get("main_picture") or {}).get("large"),
                        "genres": [g["name"] for g in node.get("genres", [])],
                        "scores": {"MAL": node["mean"]} if node.get("mean") else {}})
    return out


_READING = ("manga", "manhwa", "web novel", "comic", "book")


def sync_mal():
    rows = mal_entries()
    if not rows:
        return None
    # The same title on your anime and manga lists stays two entries.
    watch_keys = {_norm_title(x["title"]) for x in library() if x.get("kind") not in _READING}
    watch_keys |= {_norm_title(r["title"]) for r in rows if r["kind"] == "anime"}
    for r in rows:
        if r["kind"] in _READING and _norm_title(r["title"]) in watch_keys:
            r["title"] += " (manga)"
    with _LIB_LOCK:  # MAL is newer than the doc for anime: its status wins
        lib = library()
        by_key = {_norm_title(x["title"]): x for x in lib}
        for r in rows:
            cur = by_key.get(_norm_title(r["title"]))
            if cur and r["status"] != cur["status"]:
                cur["status"] = r["status"]
                if r["status"] == "done" and not cur.get("done_at"):
                    cur["done_at"] = time.time()
            if cur and r["progress"]:
                cur["progress"] = r["progress"]
        _save_library(lib)
    return merge_into_library(rows, source="mal")


def _jikan(kind, title):
    """Anime or manga facts from Jikan (a free MyAnimeList mirror)."""
    url = f"https://api.jikan.moe/v4/{kind}?" + urlencode({"q": title, "limit": "1", "sfw": "true"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": WIKI_UA}), timeout=8) as resp:
            hit = (json.loads(resp.read()).get("data") or [None])[0]
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    if not hit:
        return {}
    return {"mal_id": hit.get("mal_id"), "image": ((hit.get("images") or {}).get("jpg") or {}).get("large_image_url"),
            "genres": [g["name"] for g in (hit.get("genres") or []) + (hit.get("themes") or [])][:6],
            "mal_score": hit.get("score")}


def _tmdb_search(title):
    if not TMDB_API_KEY:
        return None
    bearer = TMDB_API_KEY.startswith("eyJ")
    url = TMDB_BASE + "/search/multi?" + urlencode({"query": title, **({} if bearer else {"api_key": TMDB_API_KEY})})
    headers = {"User-Agent": WIKI_UA, "Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {TMDB_API_KEY}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=8) as resp:
            hit = next((r for r in json.loads(resp.read()).get("results", []) if r.get("poster_path")), None)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    return {"image": f"https://image.tmdb.org/t/p/w500{hit['poster_path']}"} if hit else {}


def enrich_library(limit=6, deadline=None):
    """Posters and genres for a few titles that have none (current first)."""
    order = {"current": 0, "waiting": 1, "queue": 2, "paused": 3, "done": 4, "dropped": 5}
    todo = sorted((x for x in library() if not x.get("looked_up")), key=lambda x: (order.get(x["status"], 9), x.get("rank") or 999))
    found = {}
    for it in todo[:limit]:
        if deadline and time.time() > deadline:
            break
        kind = it.get("kind")
        if kind in ("anime",):
            facts = _jikan("anime", it["title"])
        elif kind in ("manga", "manhwa", "web novel", "comic"):
            facts = _jikan("manga", it["title"])
        elif kind in ("movie", "show"):
            facts = _tmdb_search(it["title"])
        else:
            facts = None
        if facts is None and kind not in ("movie", "show", "anime", "manga", "manhwa", "web novel"):
            answered, img = wiki_image(it["title"] + (" video game" if kind == "game" else ""))
            facts = {"image": img} if answered else None
        if facts is not None:
            found[it["id"]] = facts
        time.sleep(0.4)  # Jikan allows about 3 a second
    if found:
        with _LIB_LOCK:
            lib = library()
            for x in lib:
                if x["id"] in found:
                    f = found[x["id"]]
                    x["looked_up"] = True
                    for k in ("image", "genres", "mal_id"):
                        if f.get(k) and not x.get(k):
                            x[k] = f[k]
                    if f.get("mal_score"):
                        x.setdefault("scores", {})["MAL"] = f["mal_score"]
            _save_library(lib)
    return len(found)


def _follow_keys(it):
    """Ways a headline might name this title: whole, before a colon, or a
    distinctive subtitle after it ("Hollow Knight: Silksong" -> "silksong")."""
    base = re.sub(r"\s+(?:S\d+|Season \d+|\d+(?:-\d+)?|Series|Trilogy|Movies)$", "", it["title"], flags=re.I)
    parts = re.split(r"[:(]| - ", base)
    keys = {_norm_title(base), _norm_title(parts[0])}
    sub = _norm_title(parts[1]) if len(parts) > 1 else ""
    if len(sub) >= 6 and not re.match(r"(part|season|chapter|volume|vol|book|episode|the movie|the series)\b", sub):
        keys.add(sub)
    return {k for k in keys if len(k) >= 5}


def followed_news(limit=12):
    """Anime, manga and game news that names something you follow
    (what you're on, waiting for, have paused, games up next, favorites)."""
    follows = [x for x in library() if x["status"] in ("current", "waiting", "paused")
               or (x["status"] == "queue" and x.get("kind") == "game") or x.get("beloved")]
    keyed = [(k, x) for x in follows for k in _follow_keys(x)]
    out, seen = [], set()
    for it in outlet_items(LENZ_NEWS_FEEDS):
        t = _norm_title(it["title"])
        hit = next((x for k, x in keyed if k in t), None)
        if hit and it["url"] not in seen:
            seen.add(it["url"])
            out.append(dict(it, about=hit["title"], waiting=hit["status"] == "waiting"))
    out.sort(key=lambda i: -(i.get("published") or 0))
    return out[:limit]


def lenz_week_report(today):
    """Sunday's taste report: what you finished, how you rated it, and how
    your taste file moved since last week. Facts only; no model call."""
    st = store()
    since = time.time() - 7 * 86400
    prof = taste_profile(since=since)
    last = json.loads(st.get_meta("lenz:taste:last") or "null")
    lines = [f"Your week in media (to {today:%b} {today.day}):"]
    if prof["recent"]:
        lines.append("Finished: " + ", ".join(f"{r['title']}" + (f" ({r['rating']}/10)" if r["rating"] else " (unrated)")
                                                for r in prof["recent"]) + ".")
    else:
        lines.append("Nothing marked finished this week. Tap \"Watched it\" on my page when you finish something.")
    for k, v in list(prof["kinds"].items())[:4]:
        was = (last or {}).get("kinds", {}).get(k, {})
        if v["avg"] is not None and was.get("avg") is not None and abs(v["avg"] - was["avg"]) >= 0.2:
            lines.append(f"{KIND_LABELS.get(k, k.title())} average {'up' if v['avg'] > was['avg'] else 'down'} "
                         f"to {v['avg']} (was {was['avg']}).")
    if prof["genres"] and last and prof["genres"][:3] != last.get("genres", [])[:3]:
        lines.append("Your top genres now: " + ", ".join(prof["genres"][:3]) + ".")
    unrated = prof["finished"] - prof["rated"]
    if unrated:
        lines.append(f"{unrated} finished title{'s' if unrated != 1 else ''} still unrated; every rating sharpens your taste file.")
    st.set_meta("lenz:taste:last", json.dumps(prof))
    return "\n".join(lines)


_WATCHED_RE = re.compile(r"\b(?:i )?(?:just )?(?:watched|finished|beat|read|completed)\s+(.+?)"
                         r"(?:[\s,:-]+(\d{1,2})\s*(?:/\s*10|out of 10)?)?\s*[.!]?$", re.I)


def lenz_quick_reply(text):
    """'@lenz I finished Frieren, 9/10' logs it, no model call."""
    m = _WATCHED_RE.search(re.sub(r"@\w+", "", text).strip())
    if not m:
        return None
    title, rating = m.group(1).strip(" ,.!"), m.group(2)
    rating = int(rating) if rating and 1 <= int(rating) <= 10 else None
    key = _norm_title(title)
    it = next((x for x in library() if _norm_title(x["title"]) == key), None) or next(
        (x for x in library() if key and key in _norm_title(x["title"])), None)
    if not it:
        it, _ = add_library_item(title, status="done")
    it = update_library_item(it["id"], "watched", rating)
    return lenz_logged_line(it)


def lenz_logged_line(it):
    """Lenz's note when you finish something: the facts, and a nudge to rate."""
    if not it.get("rating"):
        return (f"Logged {it['title']} as finished. What would you give it out of 10? "
                "Rating it teaches your taste file what you love.")
    same = [x for x in library() if x["status"] == "done" and x.get("rating") and x.get("kind") == it.get("kind")]
    better = sum(1 for x in same if x["rating"] < it["rating"])
    plural = {"game": "games", "show": "shows", "movie": "movies", "web novel": "web novels", "book": "books",
              "comic": "comics", "musical": "musicals"}.get(it.get("kind"), it.get("kind") or "titles")
    rank = (f" That's above {better} of the {len(same) - 1} other {plural} you've rated." if len(same) > 1 else "")
    return f"Logged {it['title']}: {it['rating']}/10.{rank}"
