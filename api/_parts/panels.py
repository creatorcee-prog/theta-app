"""Jarvis-style panels (2026-11-03). Part of api/index.py, loaded INTO its
namespace by _load_part() (see store.py).

When Theta looks something up or changes something while answering, the
Head page (now the chat too) shows it as a panel above the conversation, the
way Jarvis throws up the schematic it's talking about: the calendar, the
budget, reminders, a map, the sources it read, the weather, a focus timer,
background jobs. The panels ride on Theta's message (extra "panels"), so the
spoken answer stays one line and the detail is on screen. Exact data only:
each panel is built from the hub's own data, never from the model's words."""

PANELS_MAX = 3
_URL = re.compile(r"https?://[^\s)>\]]+")


def _p_calendar(arg, result):
    if not calendar_linked():
        return None
    word = (arg or "").strip().lower()
    today = datetime.now(hub_tz()).date()
    first = today + timedelta(days=1) if word.startswith("tomorrow") else today
    days = 6 if word.startswith("week") else (max(0, min(int(word.split()[0]), 14) - 1) if word.split()[:1] and word.split()[0].isdigit() else 1)
    items = [{"when": (o["start"] if o["all_day"] else o["start"].date()).strftime("%a %b %d")
              + ("" if o["all_day"] else " " + _clock(o["start"])), "title": o["title"], "where": o["location"]}
             for o in calendar_events(first, first + timedelta(days=days))][:8]
    return {"kind": "calendar", "title": "Calendar", "items": items}


def _p_budget(arg, result):
    st = month_status()
    rows = [{"name": c, "spent": round(v["spent"], 2), "budget": v["budget"]} for c, v in st.items() if v["spent"] or v["budget"]]
    rows.sort(key=lambda r: -(r["spent"] / r["budget"] if r["budget"] else r["spent"] / 1000))
    return {"kind": "budget", "title": f"Money, {datetime.now(hub_tz()):%B}",
            "total": round(sum(v["spent"] for v in st.values()), 2), "rows": rows[:6]}


def _p_reminders(arg, result):
    now = time.time()
    rs = sorted((r for r in reminders() if r.get("pending") or r["at"] >= now - 3600), key=lambda r: r["at"])[:6]
    return {"kind": "reminders", "title": "Reminders",
            "items": [{"when": _clock(datetime.fromtimestamp(r["at"], hub_tz())) if r["at"] - now < 20 * 3600 else
                       datetime.fromtimestamp(r["at"], hub_tz()).strftime("%a %b %d"), "what": r["what"],
                       "pending": bool(r.get("pending"))} for r in rs]}


def _p_directions(arg, result):
    url = next(iter(_URL.findall(result or "")), "")
    if not url:
        return None
    place = re.sub(r"^Directions to ", "", (result or "").split(":", 1)[0]).strip()
    return {"kind": "map", "title": "Directions", "place": place, "url": url.rstrip(").,")}


def _p_sources(arg, result):
    urls = list(dict.fromkeys(u.rstrip(").,") for u in _URL.findall(result or "")))[:5]
    if not urls:
        return None
    return {"kind": "sources", "title": "Sources", "query": (arg or "")[:80],
            "items": [{"url": u, "host": urlparse(u).hostname.removeprefix("www.") if urlparse(u).hostname else u} for u in urls]}


def _p_focus(arg, result):
    f = focus_state()
    if not f:
        return None
    return {"kind": "focus", "title": "Focus", "task": f["task"], "until": f["until"], "minutes": f["minutes"]}


def _p_jobs(arg, result):
    js = jobs()[-4:]
    if not js:
        return None
    return {"kind": "jobs", "title": "Background jobs",
            "items": [{"id": j["id"], "task": j["task"][:80], "status": j["status"]} for j in reversed(js)]}


def _p_weather(arg, result):
    w = _meta_json("weather:today", {})
    if w.get("day") != datetime.now(hub_tz()).date().isoformat():
        try:
            w = weather_today() or {}
        except Exception:
            return None
    if not w:
        return None
    return {"kind": "weather", "title": f"Weather, {w['name']}", "hi": w["hi"], "lo": w["lo"], "rain": w["rain"],
            "rain_at": _clock(datetime.fromisoformat(w["rain_at"])) if w.get("rain_at") else ""}


def _p_library(arg, result):
    now = [x["title"] for x in library() if x["status"] == "current"][:8]
    return {"kind": "list", "title": "Watching, playing, reading", "items": now} if now else None


PANEL_FOR = {"calendar": _p_calendar, "budget": _p_budget, "spend": _p_budget, "reminders": _p_reminders,
             "remind": _p_reminders, "cancel": _p_reminders, "directions": _p_directions, "web_search": _p_sources,
             "fetch_page": _p_sources, "focus": _p_focus, "background": _p_jobs, "weather": _p_weather,
             "library": _p_library}


def note_panel(name, arg, ok, result):
    """After a tool runs in a reply: the panel it pulls up, kept for this reply."""
    fn = PANEL_FOR.get(name.lower())
    if not fn or not ok:
        return
    try:
        p = fn(arg, result)
    except Exception as e:  # a panel is a nice-to-have; never the reply's problem
        print(f"panel {name} failed: {e!r}")
        return
    if not p:
        return
    got = [x for x in (getattr(_REQ, "panels", None) or []) if x["kind"] != p["kind"]]
    _REQ.panels = (got + [p])[-PANELS_MAX:]


def _tool_weather(arg, agent):
    if not HOME_CITY:
        return "No home city set (HOME_CITY in Vercel), so I can't get the weather."
    w = weather_today()
    return weather_line(w) + (f" Rain most likely around {_clock(datetime.fromisoformat(w['rain_at']))}." if w.get("rain_at") else "")


TOOLS["weather"] = ("weather | today   (today's forecast at home: high, low, chance of rain)", _tool_weather, {"theta"})
HEAD_LOOKUPS.add("weather")
