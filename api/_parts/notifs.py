"""More of Theta's notifications (Stage 9d). Part of api/index.py, loaded INTO
its namespace by _load_part() (see store.py). Each kind has an on/off switch
in Settings → Notifications (meta "notif:off"), and all of them run from the
5-minute tick except money, which runs as you log spending.

- weather: a morning heads-up for rain, heat or freezing (Open-Meteo: free,
  no key; needs HOME_CITY), and a weather line in the morning brief.
- money: a category passing 80% or 100% of its budget, and big purchases
  (BIG_SPEND, default $100).
- calendar: events added, moved or cancelled today or tomorrow.
- winddown: "time to wind down" at WIND_DOWN_TIME, with tomorrow's first event.
- water: water / stretch / eyes breaks every WATER_EVERY_HOURS (2) from 10 AM
  to 8 PM, skipped during a focus session.
- releases: the evening before something you follow comes out (Lenz already
  pushes on the day itself).
- missed: at MISSED_TIME, the reminders that didn't get done, with Approve to
  move them to tomorrow."""

NOTIF_KINDS = {
    "weather": "Weather heads-up (rain, heat, freezing)",
    "money": "Money (budget at 80% / 100%, big purchases)",
    "calendar": "Calendar changes today and tomorrow",
    "winddown": "Wind-down in the evening",
    "water": "Water and stretch breaks",
    "releases": "Shows and games you follow, the day before",
    "missed": "Reminders that didn't get done",
}
HOME_CITY = os.environ.get("HOME_CITY", "").strip()
WEATHER_TIME = os.environ.get("WEATHER_TIME", "06:45")
BIG_SPEND = float(os.environ.get("BIG_SPEND", "100") or 100)
WIND_DOWN_TIME = os.environ.get("WIND_DOWN_TIME", "21:30")
WATER_EVERY_HOURS = float(os.environ.get("WATER_EVERY_HOURS", "2") or 0)
RELEASES_EVE_TIME = os.environ.get("RELEASES_EVE_TIME", "19:00")
MISSED_TIME = os.environ.get("MISSED_TIME", "20:30")
_BREAKS = ["💧 Water break: have a glass.", "🧍 Stand up and stretch for a minute.",
           "👀 Eyes off the screen for 20 seconds: look at something far away.", "💧 Drink some water.",
           "🚶 Quick walk, even just to the kitchen and back."]


def notif_on(kind):
    return kind not in _meta_json("notif:off", [])


def notif_set(kind, on):
    if kind not in NOTIF_KINDS:
        raise ValueError("unknown notification kind")
    off = [k for k in _meta_json("notif:off", []) if k != kind] + ([] if on else [kind])
    store().set_meta("notif:off", json.dumps(off))


def _hm(text, default):
    try:
        h, m = (int(x) for x in text.split(":"))
        return h, m
    except ValueError:
        return default


def _once_after(key, local, at, default):
    """True once a day, at or after `at` (HH:MM, hub time). Claims the day."""
    if (local.hour, local.minute) < _hm(at, default):
        return False
    day = local.date().isoformat()
    if store().get_meta(key) == day:
        return False
    store().set_meta(key, day)
    return True


# ---- weather (Open-Meteo: free, no key)
def _get(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "Theta-hub"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def weather_place():
    """(lat, lon, name) for HOME_CITY, looked up once."""
    if not HOME_CITY:
        return None
    hit = _meta_json("weather:place", {})
    if hit.get("city") == HOME_CITY:
        return hit["lat"], hit["lon"], hit["name"]
    city, _, region = HOME_CITY.partition(",")
    got = _get("https://geocoding-api.open-meteo.com/v1/search?" + urlencode({"name": city.strip(), "count": 10}))
    res = got.get("results") or []
    region = region.strip().lower()
    pick = next((r for r in res if region and region in " ".join(str(r.get(k, "")) for k in
                                                                ("admin1", "country", "country_code")).lower()), None)
    pick = pick or next((r for r in res if r.get("country_code") == "US"), None) or (res[0] if res else None)
    if not pick:
        raise ValueError(f"couldn't find {HOME_CITY}")
    name = ", ".join(x for x in (pick.get("name"), pick.get("admin1")) if x)
    store().set_meta("weather:place", json.dumps({"city": HOME_CITY, "lat": pick["latitude"], "lon": pick["longitude"], "name": name}))
    return pick["latitude"], pick["longitude"], name


def weather_today():
    """{hi, lo, rain, rain_at, name} for today, or None without HOME_CITY."""
    place = weather_place()
    if not place:
        return None
    lat, lon, name = place
    got = _get("https://api.open-meteo.com/v1/forecast?" + urlencode({
        "latitude": lat, "longitude": lon, "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "hourly": "precipitation_probability", "temperature_unit": "fahrenheit", "timezone": HUB_TIMEZONE,
        "forecast_days": 1}))
    d = got["daily"]
    hours = got.get("hourly") or {}
    rain_at = next((t for t, p in zip(hours.get("time", []), hours.get("precipitation_probability", []))
                    if (p or 0) >= 50 and int(t[11:13]) >= 6), None)
    return {"hi": round(d["temperature_2m_max"][0]), "lo": round(d["temperature_2m_min"][0]),
            "rain": d["precipitation_probability_max"][0] or 0, "rain_at": rain_at, "name": name}


def weather_line(w):
    return f"Weather in {w['name']}: high {w['hi']}°, low {w['lo']}°, {w['rain']}% chance of rain."


def weather_tick(local):
    if not (HOME_CITY and notif_on("weather")) or not _once_after("notif:weather_day", local, WEATHER_TIME, (6, 45)):
        return None
    w = weather_today()
    store().set_meta("weather:today", json.dumps({"day": local.date().isoformat(), **w}))
    bits = []
    if w["rain_at"]:
        bits.append(f"Rain likely around {_clock(datetime.fromisoformat(w['rain_at']))} ({w['rain']}%): take a jacket")
    if w["hi"] >= 95:
        bits.append(f"Hot today, up to {w['hi']}°: take water")
    if w["lo"] <= 32:
        bits.append(f"Freezing tonight, down to {w['lo']}°")
    if bits:
        notify("Theta", ". ".join(bits) + ".", "/")
    return bits


def weather_facts(today):
    """The morning brief's weather line (from the morning check, or fetched)."""
    if not HOME_CITY:
        return []
    w = _meta_json("weather:today", {})
    if w.get("day") != today.isoformat():
        try:
            w = weather_today()
        except Exception:
            return []
    return [weather_line(w)] if w else []


# ---- money
def money_alert(amount, category):
    """After you log spending: big purchase, or the category passing 80% / 100%."""
    if not notif_on("money"):
        return None
    v = month_status()[category]
    out = []
    if amount >= BIG_SPEND:
        out.append(f"Big purchase: ${amount:,.2f} on {category}")
    if v["budget"]:
        before, after = (v["spent"] - amount) / v["budget"], v["spent"] / v["budget"]
        if before < 1 <= after:
            out.append(f"{category} is over budget: ${v['spent']:,.0f} of ${v['budget']:,.0f}")
        elif before < 0.8 <= after:
            out.append(f"{category} is at {after:.0%} of its budget (${v['spent']:,.0f} of ${v['budget']:,.0f})")
    if out:
        notify("Glass", ". ".join(out) + ".", "/money")
    return out


# ---- calendar changes
def calendar_changes(local):
    if not (REMI_CALENDAR_URLS and notif_on("calendar")):
        return None
    if calendar_problems():  # a link that didn't load would look like everything was cancelled
        return None
    today = local.date()
    now = local.timestamp()
    items = {}
    for o in calendar_events(today, today + timedelta(days=1)):
        if o["birthday"] or (not o["all_day"] and o["end"].timestamp() < now):
            continue
        items[f"{o['title']}|{o['start'].isoformat()}"] = occurrence_text(o, with_day=True)
    old = _meta_json("notif:cal", {})
    store().set_meta("notif:cal", json.dumps({"day": today.isoformat(), "items": items}))
    if old.get("day") != today.isoformat():
        return None  # a new day (or the first look): nothing to compare yet
    before = old.get("items") or {}

    def upcoming(k):  # an event that just ended isn't "cancelled"
        when = k.split("|", 1)[1]
        return "T" not in when or datetime.fromisoformat(when).timestamp() > now

    added = [k for k in items if k not in before]
    gone = [k for k in before if k not in items and upcoming(k)]
    gone_titles = {g.split("|")[0] for g in gone}
    moved = [k for k in added if k.split("|")[0] in gone_titles]
    moved_titles = {k.split("|")[0] for k in moved}
    lines = [f"Moved: {items[k]}" for k in moved]
    lines += [f"New: {items[k]}" for k in added if k not in moved]
    lines += [f"Cancelled: {before[k]}" for k in gone if k.split("|")[0] not in moved_titles]
    if lines:
        notify("Remi", "Calendar change: " + "; ".join(lines)[:230], "/calendar")
    return lines


# ---- wind-down
def wind_down(local):
    if not notif_on("winddown") or not _once_after("notif:winddown_day", local, WIND_DOWN_TIME, (21, 30)):
        return None
    since = local.replace(hour=17, minute=0).timestamp()
    if any(m["text"].startswith("📱 Phone: going to bed") and _chat_ts(m) >= since
           for m in store().list_chat(ALLCHAT_KEEP)[-60:] if m.get("kind") == "event"):
        return None  # already in bed
    text = "Time to start winding down."
    tomorrow = local.date() + timedelta(days=1)
    if calendar_linked():
        first = next((o for o in calendar_events(tomorrow, tomorrow) if not o["all_day"] and not o["birthday"]), None)
        if first:
            text += f" Tomorrow starts with {first['title']} at {_clock(first['start'])}."
    notify("Theta", text, "/")
    return text


# ---- water and stretch breaks
def water_break(local):
    if WATER_EVERY_HOURS <= 0 or not notif_on("water") or not 10 <= local.hour < 20:
        return None
    if focus_state():  # focus check-ins are already coming
        return None
    now = local.timestamp()
    last = float(store().get_meta("notif:water_at") or 0)
    if now - last < WATER_EVERY_HOURS * 3600:
        return None
    store().set_meta("notif:water_at", str(now))
    if not last or now - last > 20 * 3600:  # the first of the day waits a full interval
        return None
    n = int(store().get_meta("notif:water_n") or 0)
    store().set_meta("notif:water_n", str(n + 1))
    text = _BREAKS[n % len(_BREAKS)]
    notify("Theta", text, "/")
    return text


# ---- releases, the evening before
def releases_eve(local):
    if not notif_on("releases") or not _once_after("notif:releases_day", local, RELEASES_EVE_TIME, (19, 0)):
        return None
    tomorrow = (local.date() + timedelta(days=1)).isoformat()
    try:
        due = [x for x in releases(local.date()) if x["date"] == tomorrow and x.get("followed")]
    except Exception:
        return None
    if due:
        notify("Lenz", "Tomorrow: " + ", ".join(x["title"] for x in due[:3])
               + (" come out." if len(due) > 1 else " comes out."), "/lenz#releases")
    return [x["title"] for x in due]


# ---- missed reminders
def missed_reminders(local):
    if not notif_on("missed") or not _once_after("notif:missed_day", local, MISSED_TIME, (20, 30)):
        return None
    start = local.replace(hour=0, minute=0, second=0).timestamp()
    left = [r for r in reminders() if r.get("pending") and (r.get("fired") or r["at"] >= start or r.get("repeat"))]
    if not left:
        return None
    names = ", ".join(r["what"] for r in left[:4]) + ("…" if len(left) > 4 else "")
    propose_to_user({"kind": "remind_move", "ids": [r["id"] for r in left], "summary": f"Move to tomorrow: {names}"},
                    "These didn't get done today:\n" + "\n".join(f"- {r['what']}" for r in left)
                    + "\nMove them to tomorrow, same time?", labels=("Move to tomorrow", "Leave them"))
    notify("Theta", f"Didn't get done today: {names}. Move to tomorrow?", "/")
    return [r["what"] for r in left]


def move_to_tomorrow(ids, now=None):
    """Approve on a missed-reminders card: each one again tomorrow, same time."""
    now = now or time.time()
    tz = hub_tz()
    tomorrow = datetime.fromtimestamp(now, tz).date() + timedelta(days=1)
    moved = []
    with _REM_LOCK:
        rs = reminders()
        for r in rs:
            if r["id"] not in ids:
                continue
            r.update(pending=False, nags=0)
            if not r.get("repeat"):
                at = datetime.fromtimestamp(r["at"], tz)
                r["at"] = datetime.combine(tomorrow, at.time(), tzinfo=tz).timestamp()
                r["fired"] = False
            moved.append(r["what"])
        _save_reminders(rs)
    return f"✓ Moved to tomorrow: {', '.join(moved)}" if moved else "Those reminders are gone already."


def notifs_tick(now=None):
    """From the tick: every kind that runs on a clock. Returns what went out."""
    local = datetime.fromtimestamp(now or time.time(), hub_tz())
    out = {}
    for job in (weather_tick, calendar_changes, wind_down, water_break, releases_eve, missed_reminders):
        try:
            got = job(local)
            if got:
                out[job.__name__] = got
        except Exception as e:  # one kind failing never stops the others
            print(f"{job.__name__} failed: {e!r}")
    return out


# ---- Settings → Notifications
def notifs_card():
    rows = "".join(
        f'<div class="nrow"><span>{html.escape(label)}</span><div class="seg" role="group" aria-label="{html.escape(label)}">'
        f'<button type="button" data-notif="{k}" data-on="1" class="{"on" if notif_on(k) else ""}">On</button>'
        f'<button type="button" data-notif="{k}" data-on="0" class="{"" if notif_on(k) else "on"}">Off</button></div></div>'
        for k, label in NOTIF_KINDS.items())
    city = (f"Weather for <b>{html.escape(HOME_CITY)}</b>." if HOME_CITY else
            "Weather needs <code>HOME_CITY</code> in Vercel (like <code>St George, UT</code>).")
    return ('<section class="card stack" id="notifs"><h2>Notifications</h2>'
            # the switch for this phone: moved here from Home's collapsed Mistral section (2026-11-04)
            '<p class="muted small">Turn them on for this phone first. On iPhone, open Theta from its Home Screen icon.</p>'
            '<p><button class="btn" id="push-on" type="button">Turn on</button> <button class="btn ghost" id="push-test" '
            'type="button">Send a test</button></p><p class="note" id="push-status" style="white-space:pre-line"></p>'
            f'<script>{_PUSH_JS}</script>'
            '<p class="muted small">Theta’s extra heads-ups. '
            f'{city} Times are set in Vercel: <code>WEATHER_TIME</code> ({html.escape(WEATHER_TIME)}), '
            f'<code>WIND_DOWN_TIME</code> ({html.escape(WIND_DOWN_TIME)}), <code>MISSED_TIME</code> ({html.escape(MISSED_TIME)}), '
            f'<code>WATER_EVERY_HOURS</code> ({WATER_EVERY_HOURS:g}), <code>BIG_SPEND</code> (${BIG_SPEND:,.0f}).</p>'
            f'<style>#notifs .nrow{{display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:14px}}</style>{rows}'
            '<script>document.querySelectorAll("[data-notif]").forEach(b=>b.onclick=async()=>{'
            'const r=await fetch("/api/settings/notifs",{method:"POST",headers:window.THETA_H,body:JSON.stringify({kind:b.dataset.notif,on:b.dataset.on==="1"})});'
            'if((await r.json()).ok)document.querySelectorAll(`[data-notif="${b.dataset.notif}"]`).forEach(x=>x.classList.toggle("on",x===b));});</script></section>')
