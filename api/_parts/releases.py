"""Lenz's release calendar.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Lenz's release calendar: what's coming out (movies and shows from
# TMDB, anime from Jikan, games from RAWG with RAWG_API_KEY), soonest
# first, with anything you follow flagged. Refreshed once a day; on
# release day Lenz posts and pushes what you follow.
RAWG_API_KEY = os.environ.get("RAWG_API_KEY", "")
RAWG_BASE = "https://api.rawg.io/api"
JIKAN_BASE = "https://api.jikan.moe/v4"
TMDB_REGION = os.environ.get("TMDB_REGION", "US")
RELEASE_DAYS = 120  # how far ahead the calendar looks
RELEASE_KINDS = {"movie": "Movies", "tv": "TV", "anime": "Anime", "game": "Games"}


def _get_json(url, headers=None, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": WIKI_UA, "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _tmdb_get(path, **params):
    bearer = TMDB_API_KEY.startswith("eyJ")
    if not bearer:
        params["api_key"] = TMDB_API_KEY
    return _get_json(TMDB_BASE + path + "?" + urlencode(params),
                     {"Authorization": f"Bearer {TMDB_API_KEY}"} if bearer else None)


def _releases_tmdb(today):
    if not TMDB_API_KEY:
        return []
    end = today + timedelta(days=RELEASE_DAYS)
    out = []
    for path, kind, params in (
            ("/movie/upcoming", "movie", {"region": TMDB_REGION}),
            ("/discover/tv", "tv", {"first_air_date.gte": today.isoformat(), "first_air_date.lte": end.isoformat(),
                                    "sort_by": "popularity.desc", "with_type": "2|4"})):
        for page in (1, 2):
            for r in _tmdb_get(path, page=page, **params).get("results", []):
                d = r.get("release_date") or r.get("first_air_date") or ""
                if not r.get("poster_path") or not d or not (today.isoformat() <= d <= end.isoformat()):
                    continue
                out.append({"title": r.get("title") or r.get("name"), "kind": kind, "date": d,
                            "image": f"https://image.tmdb.org/t/p/w342{r['poster_path']}", "pop": r.get("popularity") or 0,
                            "url": f"https://www.themoviedb.org/{'movie' if kind == 'movie' else 'tv'}/{r['id']}"})
    return out


def _releases_anime(today):
    end = today + timedelta(days=RELEASE_DAYS)
    out = []
    for r in _get_json(JIKAN_BASE + "/seasons/upcoming?limit=25&sfw=true").get("data", []):
        d = str(((r.get("aired") or {}).get("from") or ""))[:10]
        if not d or not (today.isoformat() <= d <= end.isoformat()):
            continue
        out.append({"title": r.get("title_english") or r.get("title"), "kind": "anime", "date": d,
                    "image": ((r.get("images") or {}).get("jpg") or {}).get("large_image_url"), "pop": r.get("members") or 0,
                    "url": r.get("url") or ""})
    return out


def _releases_games(today):
    if not RAWG_API_KEY:
        return []
    end = today + timedelta(days=RELEASE_DAYS)
    data = _get_json(RAWG_BASE + "/games?" + urlencode({"key": RAWG_API_KEY, "dates": f"{today},{end}",
                                                         "ordering": "-added", "page_size": "40"}))
    out = []
    for r in data.get("results", []):
        if not r.get("released") or not r.get("background_image"):
            continue
        plats = sorted({p["platform"]["name"] for p in r.get("parent_platforms") or [] if p.get("platform")})
        out.append({"title": r.get("name"), "kind": "game", "date": r["released"], "image": r["background_image"],
                    "pop": r.get("added") or 0, "url": f"https://rawg.io/games/{r.get('slug', '')}", "platforms": plats})
    return out


def refresh_releases(today=None):
    """Fetch every source in parallel; a source that fails keeps its last list."""
    today = today or datetime.now(hub_tz()).date()
    old = _meta_json("releases", {}).get("by", {})
    by, errors = {}, {}
    srcs = {"tmdb": _releases_tmdb, "anime": _releases_anime, "games": _releases_games}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {name: ex.submit(fn, today) for name, fn in srcs.items()}
        for name, f in futs.items():
            try:
                by[name] = f.result(timeout=15)
            except Exception as e:
                errors[name] = str(e)[:120]
                by[name] = [x for x in old.get(name, []) if x["date"] >= today.isoformat()]
    store().set_meta("releases", json.dumps({"at": time.time(), "day": today.isoformat(), "by": by, "errors": errors}))
    return by, errors


def releases(today=None):
    """Upcoming releases, soonest first, with `followed` set for titles in
    your library you haven't finished (or marked beloved)."""
    today = today or datetime.now(hub_tz()).date()
    data = _meta_json("releases", {})
    items = [x for xs in (data.get("by") or {}).values() for x in xs if x["date"] >= today.isoformat()]
    follow = {}
    for it in library():
        if it["status"] != "done" or it.get("beloved"):
            for k in _follow_keys(it) | {_norm_title(it["title"])}:
                follow[k] = it["title"]
    for x in items:
        t = _norm_title(x["title"])
        x["followed"] = next((v for k, v in follow.items() if k and (k == t or (len(k) >= 6 and k in t))), None)
    seen, out = set(), []
    for x in sorted(items, key=lambda x: (x["date"], -(x.get("followed") is not None), -x.get("pop", 0))):
        key = (_norm_title(x["title"]), x["kind"])
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


def release_day_news(today):
    """Lenz posts and pushes followed titles that come out today, once each."""
    told = _seen("lenz:released")
    due = [x for x in releases(today) if x["date"] == today.isoformat() and x["followed"] and x["url"] not in told]
    if due:
        store().add_chat("lenz", "Out today, from your list:\n" + "\n".join(
            f"- **{x['title']}** ({RELEASE_KINDS[x['kind']].rstrip('s')})\n  {x['url']}" for x in due), channel="screen")
        notify("Lenz", "Out today: " + ", ".join(x["title"] for x in due[:3]), "/lenz#releases")
        for x in due:
            _mark_seen("lenz:released", x["url"])
    return due


_RELEASE_JS = r"""
(() => {
  const box = document.getElementById("releases"); if (!box) return;
  const strip = box.querySelector(".rstrip");
  box.addEventListener("click", e => {
    const b = e.target.closest("[data-rkind]"); if (!b) return;
    box.querySelectorAll("[data-rkind]").forEach(x => x.classList.toggle("on", x === b));
    strip.querySelectorAll(".rel").forEach(t => { t.hidden = b.dataset.rkind !== "all" && t.dataset.kind !== b.dataset.rkind; });
    const first = strip.querySelector(".rel:not([hidden])"); if (first) strip.scrollTo({left: first.offsetLeft - 8, behavior: "smooth"});
  });
})();
"""


def release_strip():
    rel = releases()[:60]
    data = _meta_json("releases", {})
    if not rel:
        why = ("Lenz needs <code>TMDB_API_KEY</code> for movies and TV; anime comes from Jikan, games need "
               "<code>RAWG_API_KEY</code> (free at rawg.io/apidocs).") if not TMDB_API_KEY else "The calendar fills in on Lenz's next round."
        return (f'<section class="card stack rcal" id="releases"><h2>Release calendar</h2><p class="muted small">{why}</p></section>')
    kinds = [k for k in RELEASE_KINDS if any(x["kind"] == k for x in rel)]
    tiles = "".join(
        f'<a class="rel{" next" if i == 0 else ""}{" mine" if x.get("followed") else ""}" data-kind="{x["kind"]}" href="{html.escape(x["url"])}" '
        f'target="_blank" rel="noopener" title="{html.escape(x["title"])}"><div class="rpic">'
        f'<img src="{html.escape(x["image"] or "")}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">'
        + ('<span class="rtag">Following</span>' if x.get("followed") else "")
        + f'</div><div class="rdate"><b>{x["date"][8:10]}</b><span>{datetime.strptime(x["date"], "%Y-%m-%d"):%b}</span></div>'
        f'<div class="rname">{html.escape(x["title"])}</div>'
        + (f'<div class="rplat">{html.escape(", ".join(x["platforms"][:3]))}</div>' if x.get("platforms") else "")
        + "</a>" for i, x in enumerate(rel))
    chips = '<button type="button" class="chip on" data-rkind="all">All</button>' + "".join(
        f'<button type="button" class="chip" data-rkind="{k}">{RELEASE_KINDS[k]}</button>' for k in kinds)
    missing = [] if RAWG_API_KEY else ["games: set <code>RAWG_API_KEY</code>"]
    return (f'<section class="card stack rcal" id="releases"><div class="brow"><h2>Release calendar</h2>'
            f'<span class="muted small">next {RELEASE_DAYS} days</span></div><div class="chips">{chips}</div>'
            f'<div class="rstrip">{tiles}</div>'
            + (f'<p class="muted small">{"; ".join(missing)}. ' if missing else '<p class="muted small">')
            + 'From TMDB, Jikan (MyAnimeList) and RAWG. "Following" means it\'s on your list.</p>'
            f'<script>{_RELEASE_JS}</script></section>')
