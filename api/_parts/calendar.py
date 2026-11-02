"""Remi's calendar (iCal).

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Remi's calendar: Google Calendar "secret address in iCal format"
# links (read-only), plus BIRTHDAYS. Times are shown in HUB_TIMEZONE.
HUB_TIMEZONE = os.environ.get("HUB_TIMEZONE", "America/Denver")
REMI_CALENDAR_URLS = [u.strip() for u in os.environ.get("REMI_CALENDAR_URLS", "").split(",") if u.strip()]
BIRTHDAYS = [p.split(":", 1) for p in os.environ.get("BIRTHDAYS", "").split(",") if ":" in p]
CALENDAR_CACHE_SECONDS = 600
_CAL_CACHE = {}  # url -> (fetched_at, events or None)
_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def hub_tz():
    try:
        return ZoneInfo(HUB_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def _ics_unescape(text):
    return (text.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\"))


def parse_ics(text):
    """VEVENTs as {NAME: (params, value)}; EXDATE collects every value."""
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]  # folded line
        else:
            lines.append(raw)
    events, cur = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = {"EXDATE": []}
        elif line == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, value = line.split(":", 1)
            name, *params = head.split(";")
            params = dict(x.split("=", 1) for x in params if "=" in x)
            if name == "EXDATE":
                cur["EXDATE"] += [(params, v) for v in value.split(",")]
            elif name not in cur:
                cur[name] = (params, value)
    return events


def _ics_time(params, value, tz):
    """(date or aware datetime in tz, all_day)."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or (len(value) == 8 and value.isdigit()):
        return date(int(value[:4]), int(value[4:6]), int(value[6:8])), True
    dt = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        zone = tz
        if params.get("TZID"):
            try:
                zone = ZoneInfo(params["TZID"].strip('"'))
            except (ZoneInfoNotFoundError, ValueError):
                pass  # e.g. a Windows zone name: assume the hub's
        dt = dt.replace(tzinfo=zone)
    return dt.astimezone(tz), False


def _nth_weekday(year, month, weekday, n):
    """The nth (1-based; negative counts from the end) weekday of a month, or None."""
    first = date(year, month, 1)
    days = [first + timedelta(d) for d in range(31)
            if (first + timedelta(d)).month == month and (first + timedelta(d)).weekday() == weekday]
    try:
        return days[n - 1] if n > 0 else days[n]
    except IndexError:
        return None


def _rrule_dates(first, rule, last_day):
    """Dates a recurring event starts on, from its first date up to last_day."""
    r = dict(x.split("=", 1) for x in rule.split(";") if "=" in x)
    freq, step = r.get("FREQ"), max(1, int(r.get("INTERVAL", "1") or 1))
    count = int(r["COUNT"]) if r.get("COUNT", "").isdigit() else None
    until = date(int(r["UNTIL"][:4]), int(r["UNTIL"][4:6]), int(r["UNTIL"][6:8])) if r.get("UNTIL") else None
    byday = [d.strip() for d in r.get("BYDAY", "").split(",") if d.strip()]
    stop = min(last_day, until) if until else last_day

    def candidates():
        if freq == "DAILY":
            d = first
            while True:
                yield d
                d += timedelta(days=step)
        elif freq == "WEEKLY":
            days = sorted({_WEEKDAYS[b[-2:]] for b in byday if b[-2:] in _WEEKDAYS} or {first.weekday()})
            week = first - timedelta(days=first.weekday())
            while True:
                for wd in days:
                    yield week + timedelta(days=wd)
                week += timedelta(weeks=step)
        elif freq == "MONTHLY":
            y, m = first.year, first.month
            while True:
                if byday and byday[0][-2:] in _WEEKDAYS and byday[0][:-2].lstrip("+-").isdigit():
                    d = _nth_weekday(y, m, _WEEKDAYS[byday[0][-2:]], int(byday[0][:-2]))
                else:
                    day = int(r.get("BYMONTHDAY", first.day))
                    try:
                        d = date(y, m, day)
                    except ValueError:
                        d = None
                if d:
                    yield d
                m += step
                y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
        elif freq == "YEARLY":
            y = first.year
            while True:
                try:
                    yield date(y, first.month, first.day)
                except ValueError:
                    pass  # Feb 29 in a non-leap year
                y += step
        else:
            yield first

    out, n = [], 0
    for d in candidates():
        if d < first:
            continue
        if d > stop or (count is not None and n >= count) or n > 3000:
            break
        n += 1
        out.append(d)
    return out


def _calendar_text(url):
    try:
        return _fetch_url(url, timeout=8).decode("utf-8", "replace")
    except Exception as e:  # a bad link shouldn't break the dashboard
        print(f"calendar fetch failed: {e!r}")
        return None


def _calendar_sources(urls):
    """Parsed events per calendar (None if it couldn't be read), from this
    process's cache, then the stored copy, then the calendar itself."""
    now, refreshing = time.time(), getattr(_REQ, "refreshing", False)
    hits = {u: _CAL_CACHE[u][1] for u in urls if u in _CAL_CACHE
            and now - _CAL_CACHE[u][0] < CALENDAR_CACHE_SECONDS and not refreshing}
    rest = [u for u in urls if u not in hits]
    for u, (text, at) in zip(rest, shared_fetch_many("cal:", rest, CALENDAR_CACHE_SECONDS, _calendar_text)):
        events = parse_ics(text) if text else None
        _CAL_CACHE[u] = (at, events)
        hits[u] = events
    return [hits[u] for u in urls]


def _calendar_source(url):
    return _calendar_sources([url])[0]


def calendar_events(first_day, last_day):
    """Every occurrence overlapping first_day..last_day (local dates), sorted:
    {title, location, start, end, all_day, birthday}. Timed starts/ends are
    aware datetimes in hub_tz(); all-day ones are dates (end exclusive)."""
    tz = hub_tz()
    occ = []
    sources = _calendar_sources(REMI_CALENDAR_URLS)
    for events in sources:
        if not events:
            continue
        overridden = set()
        for ev in events:
            if "RECURRENCE-ID" in ev and "UID" in ev:
                overridden.add((ev["UID"][1], _ics_time(*ev["RECURRENCE-ID"], tz)[0]))
        for ev in events:
            if "DTSTART" not in ev or ev.get("STATUS", ({}, ""))[1].upper() == "CANCELLED":
                continue
            start, all_day = _ics_time(*ev["DTSTART"], tz)
            if "DTEND" in ev:
                end = _ics_time(*ev["DTEND"], tz)[0]
            elif "DURATION" in ev and not all_day:
                dur = ev["DURATION"][1]
                h = int(dur.split("T")[1].split("H")[0]) if "H" in dur else 0
                mins = int(dur.split("H")[-1].split("M")[0].lstrip("PT")) if "M" in dur.split("T")[-1] else 0
                end = start + timedelta(hours=h, minutes=mins)
            else:
                end = start + timedelta(days=1) if all_day else start
            length = end - start
            title = _ics_unescape(ev.get("SUMMARY", ({}, "(no title)"))[1]).strip() or "(no title)"
            where = _ics_unescape(ev.get("LOCATION", ({}, ""))[1]).strip()
            first = start if all_day else start.date()
            if "RRULE" in ev and "RECURRENCE-ID" not in ev:
                skip = {_ics_time(p, v, tz)[0] for p, v in ev["EXDATE"]}
                starts = []
                for d in _rrule_dates(first, ev["RRULE"][1], last_day):
                    st = d if all_day else datetime.combine(d, start.time(), tzinfo=tz)
                    if st in skip or (ev.get("UID", ({}, ""))[1], st) in overridden:
                        continue
                    starts.append(st)
            else:
                starts = [start]
            for st in starts:
                en = st + length
                s_day = st if all_day else st.date()
                e_day = en if all_day else (en - timedelta(microseconds=1)).date() + timedelta(days=1)
                if s_day <= last_day and max(e_day, s_day + timedelta(days=1)) > first_day:
                    occ.append({"title": title, "location": where, "start": st, "end": en,
                                "all_day": all_day, "birthday": "birthday" in title.lower()})
    for name, md in BIRTHDAYS:
        try:
            month, day = (int(x) for x in md.strip().split("-"))
        except ValueError:
            continue
        for year in range(first_day.year, last_day.year + 1):
            try:
                d = date(year, month, day)
            except ValueError:
                continue
            if first_day <= d <= last_day:
                occ.append({"title": f"{name.strip()}'s birthday", "location": "", "start": d,
                            "end": d + timedelta(days=1), "all_day": True, "birthday": True})
    occ.sort(key=lambda o: (o["start"] if o["all_day"] else o["start"].date(),
                            0 if o["all_day"] else 1,
                            "" if o["all_day"] else o["start"].strftime("%H%M"), o["title"]))
    return occ


def calendar_linked():
    return bool(REMI_CALENDAR_URLS or BIRTHDAYS)


def calendar_problems():
    """Calendar links that couldn't be read last time (for wiring)."""
    return [i + 1 for i, u in enumerate(REMI_CALENDAR_URLS)
            if _calendar_source(u) is None or snapshot_failing("cal:", u)]


def _clock(dt):
    return dt.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")


def occurrence_text(o, with_day=False):
    day = (o["start"] if o["all_day"] else o["start"].date()).strftime("%a %b %d ") if with_day else ""
    when = "All day" if o["all_day"] else f"{_clock(o['start'])}–{_clock(o['end'])}"
    return f"{day}{when}: {o['title']}" + (f" ({o['location']})" if o["location"] else "")


def remi_context():
    """The next 14 days and the reminders set, for Remi's prompt, so she
    answers from the real calendar."""
    rs = reminders()
    rem = ("\nReminders set for the user (exact):\n" + "\n".join(f"- {reminder_line(r)}" for r in rs)) if rs else ""
    mail = remi_mail_context()
    rem += f"\n{mail}" if mail else ""
    if not calendar_linked():
        return f"\n{rem}" if rem else ""
    today = datetime.now(hub_tz()).date()
    items = calendar_events(today, today + timedelta(days=13))
    listing = "\n".join(f"- {occurrence_text(o, with_day=True)}" for o in items[:60]) or "- nothing scheduled"
    return (f"\n\nToday is {today:%A %B %d}. The family calendar for the next 14 days "
            f"(exact; never change times or add events):\n{listing}{rem}")
