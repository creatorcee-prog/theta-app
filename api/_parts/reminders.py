"""Reminders.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Remi's reminders: one-off or repeating ("every day", "weekdays",
# "every friday"), pushed to your phone on time by /api/tick (Supabase Cron
# every few minutes). "until done" ones nag every REMINDER_NAG_MINUTES, up
# to REMINDER_NAG_MAX times, until you mark them done.
REMINDER_NAG_MINUTES = int(os.environ.get("REMINDER_NAG_MINUTES", "15"))
REMINDER_URL = "/agent/remi#reminders"
DIGEST_TIME = os.environ.get("DIGEST_TIME", "07:00")  # Mistral's morning digest, hub time


def digest_due(now=None):
    """True once today's digest time has passed and it hasn't gone out."""
    now = now or datetime.now(hub_tz())
    try:
        h, m = (int(x) for x in DIGEST_TIME.split(":"))
    except ValueError:
        h, m = 7, 0
    return ((now.hour, now.minute) >= (h, m)
            and store().get_meta("round:mistral:digest_day") != now.date().isoformat())
REMINDER_NAG_MAX = int(os.environ.get("REMINDER_NAG_MAX", "4"))
_REM_LOCK = threading.Lock()
_WEEKDAY = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_DAY_RE = r"(mon|tue|wed|thu|fri|sat|sun)(?:days?|sdays?|nesdays?|rsdays?|urdays?|s|t|r|rs|n)?"


_MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
_MON_RE = r"jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec"


def parse_reminder(text, now=None):
    """'8am every day take my meds until done' -> {what, at, repeat, weekday,
    hour, minute, nag}. Raises ValueError with a hint when it can't tell."""
    now = now or datetime.now(hub_tz())
    s = " " + " ".join(text.split()) + " "
    found = {}

    def take(key, pattern):
        nonlocal s
        m = re.search(pattern, s, re.I)
        if m:
            found[key] = m
            s = s[:m.start()] + " " + s[m.end():]
        return m
    nag = bool(take("nag", r"\buntil (?:i'?m |it'?s |i say it'?s )?(?:done|confirmed|i say so)\b"))
    repeat, weekday = None, None
    if take("rep", r"\b(?:every ?day|daily|each day|every night|nightly)\b"):
        repeat = "daily"
    elif take("rep", r"\b(?:every |on )?weekdays\b"):
        repeat = "weekdays"
    elif take("rep", r"\b(?:every|each) " + _DAY_RE + r"\b"):
        repeat, weekday = "weekly", _WEEKDAY[found["rep"].group(1).lower()]
    elif take("rep", r"\bweekly\b"):
        repeat = "weekly"
    rel = take("rel", r"\bin (\d{1,3}) ?(minutes?|mins?|m|hours?|hrs?|h)\b")
    dayword = take("day", r"\b(today|tonight|tomorrow)\b")
    on_date = None  # an explicit date: 1-22-2027, 1/22, 2027-01-22, Jan 22, 22 January 2027
    for pat, order in ((r"\b(?:on )?(\d{4})-(\d{1,2})-(\d{1,2})\b", "ymd"),
                       (r"\b(?:on )?(" + _MON_RE + r")[a-z]*\.? (\d{1,2})(?:st|nd|rd|th)?(?:,? (\d{4}))?\b", "mdy"),
                       (r"\b(?:on )?(\d{1,2})(?:st|nd|rd|th)? (?:of )?(" + _MON_RE + r")[a-z]*\.?(?:,? (\d{4}))?\b", "dmy"),
                       (r"\b(?:on )?(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}|\d{2}))?\b", "mdy")):
        m = re.search(pat, s, re.I)
        if not m:
            continue
        g = m.groups()
        y, mo, d = (g[0], g[1], g[2]) if order == "ymd" else (g[2], g[0], g[1]) if order == "mdy" else (g[2], g[1], g[0])
        mo = _MONTHS.get(mo[:3].lower()) if not mo.isdigit() else int(mo)
        year = int(y) + (2000 if len(y) == 2 else 0) if y else now.year
        try:
            on_date = date(year, mo, int(d))
        except (TypeError, ValueError):
            continue  # not a real date: leave the text alone
        if not y and on_date < now.date():
            on_date = on_date.replace(year=now.year + 1)  # "Jan 22" in October means next January
        s = s[:m.start()] + " " + s[m.end():]
        break
    if weekday is None and take("wd", r"\b(?:on |this |next )?" + _DAY_RE + r"\b"):
        weekday = _WEEKDAY[found["wd"].group(1).lower()]
    hour = minute = None
    if take("t", r"\b(?:at )?(\d{1,2})(?::(\d{2}))? ?([ap])\.?m?\.?(?=\W)"):
        m = found["t"]
        hour, minute = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0), int(m.group(2) or 0)
        if int(m.group(1)) > 12:
            raise ValueError("That time doesn't look right. Try '8am' or '20:30'.")
    elif take("t", r"\b(?:at )?([01]?\d|2[0-3]):([0-5]\d)\b"):
        hour, minute = int(found["t"].group(1)), int(found["t"].group(2))
    elif take("t", r"\b(noon|midday|midnight)\b"):
        hour, minute = (0 if found["t"].group(1).lower() == "midnight" else 12), 0
    elif take("t", r"\bat (\d{1,2})\b"):
        h = int(found["t"].group(1)) % 12  # "at 8": whichever 8 comes next
        hour, minute = (h if (now.hour, now.minute) < (h, 0) else h + 12), 0
    elif dayword and dayword.group(1).lower() == "tonight":
        hour, minute = 20, 0
    what = re.sub(r"^\W*(?:remind me|reminder|remind)\b\W*", "", s.strip(), flags=re.I)
    what = re.sub(r"^(?:to|that|about|at|on)\s+", "", what.strip(" ,.:;-"), flags=re.I)
    what = re.sub(r"\s+(?:at|on|to)$", "", what.strip(" ,.:;-"), flags=re.I).strip(" ,.:;-")
    if not what:
        raise ValueError("What should I remind you about?")
    if not (rel or hour is not None or dayword or weekday is not None or repeat or on_date):
        raise ValueError("When? Try '8am', 'in 20 min', 'tomorrow 9am' or 'every day at 8pm'.")
    if rel:
        n, unit = int(rel.group(1)), rel.group(2).lower()
        at = now + (timedelta(hours=n) if unit.startswith("h") else timedelta(minutes=n))
        return {"what": what[:200], "at": at.timestamp(), "repeat": None, "weekday": None,
                "hour": at.hour, "minute": at.minute, "nag": nag}
    if hour is None:
        hour, minute = 9, 0  # a day but no time: 9 in the morning
    r = {"what": what[:200], "repeat": repeat, "weekday": weekday, "hour": hour, "minute": minute, "nag": nag}
    if on_date and not repeat:
        weekday = r["weekday"] = None  # the date decides; a weekday named beside it is just a label
    day = on_date or now.date() + timedelta(days=1 if dayword and dayword.group(1).lower() == "tomorrow" else 0)
    first = _occurrence(r, day)
    if on_date and first <= now and not repeat:
        raise ValueError(f"{on_date:%b} {on_date.day}, {on_date.year} has already passed.")
    while (first <= now or (weekday is not None and first.weekday() != weekday)
           or (repeat == "weekdays" and first.weekday() >= 5)):
        day += timedelta(days=1)
        first = _occurrence(r, day)
    if repeat == "weekly" and weekday is None:
        r["weekday"] = first.weekday()
    r["at"] = first.timestamp()
    return r


def _occurrence(r, day):
    return datetime.combine(day, datetime.min.time().replace(hour=r["hour"], minute=r["minute"]), hub_tz())


def _next_after(r, after):
    """The repeat's next time after `after` (an aware datetime)."""
    d = after.astimezone(hub_tz()).date() + timedelta(days=1)
    while True:
        t = _occurrence(r, d)
        if (r["repeat"] == "daily" or (r["repeat"] == "weekdays" and t.weekday() < 5)
                or (r["repeat"] == "weekly" and t.weekday() == r["weekday"])):
            return t
        d += timedelta(days=1)


def reminders():
    return sorted(_meta_json("reminders", []), key=lambda r: r["at"])


def _save_reminders(rs):
    store().set_meta("reminders", json.dumps(rs))


def add_reminder(text, now=None):
    r = parse_reminder(text, now)
    with _REM_LOCK:
        rs = reminders()
        r.update(id=max([x["id"] for x in rs] + [0]) + 1, pending=False, nags=0, created=time.time())
        rs.append(r)
        _save_reminders(rs)
    post_event("remi", f"Remi set a reminder: {r['what']}")
    return r


def reminder_line(r):
    when = datetime.fromtimestamp(r["at"], hub_tz())
    clock = _clock(when)
    rep = {"daily": f"every day at {clock}", "weekdays": f"weekdays at {clock}",
           "weekly": f"every {_WEEKDAY_NAMES[r['weekday'] or 0]} at {clock}"}.get(r["repeat"])
    nxt = f"{when:%a %b} {when.day} at {clock}"
    return (f"#{r['id']} {r['what']}: " + (f"{rep} (next {nxt})" if rep else nxt)
            + (", until done" if r["nag"] else "") + (". Waiting for you to mark it done" if r.get("pending") else ""))


def ack_reminder(rid):
    """Mark a reminder done: stops its nagging; a one-off is then removed."""
    with _REM_LOCK:
        rs = reminders()
        r = next((x for x in rs if x["id"] == rid), None)
        if not r:
            return None
        r.update(pending=False, nags=0)
        if not r["repeat"] and r["at"] <= time.time():
            rs.remove(r)
        _save_reminders(rs)
    post_event("remi", f"You marked done: {r['what']}")
    return r


def delete_reminder(rid):
    with _REM_LOCK:
        rs = reminders()
        r = next((x for x in rs if x["id"] == rid), None)
        if r:
            rs.remove(r)
            _save_reminders(rs)
    return r


def run_tick(now=None):
    """Send what's due: reminders whose time came, and nags for "until done"
    ones not marked done yet. Cheap; meant for every few minutes."""
    now = now or time.time()
    fired, nagged = [], []
    store().set_meta("tick:last", str(time.time()))
    with _REM_LOCK:
        keep = []
        for r in reminders():
            if r.get("pending") and r.get("nag_at", 0) <= now and r["nags"] < REMINDER_NAG_MAX:
                notify("Remi", f"Still to do: {r['what']}", REMINDER_URL)
                r["nags"] += 1
                r["nag_at"] = now + REMINDER_NAG_MINUTES * 60
                nagged.append(r["what"])
            if r["at"] <= now and not r.get("fired"):
                notify("Remi", f"Reminder: {r['what']}", REMINDER_URL)
                fired.append(r["what"])
                if r["nag"]:
                    r.update(pending=True, nags=0, nag_at=now + REMINDER_NAG_MINUTES * 60)
                if r["repeat"]:
                    r["at"] = _next_after(r, datetime.fromtimestamp(max(r["at"], now), hub_tz())).timestamp()
                elif not r["nag"]:
                    continue  # a plain one-off is finished once it's sent
                else:
                    r["fired"] = True  # a one-off, kept until it's marked done
            keep.append(r)
        if fired or nagged:
            _save_reminders(keep)
    for what in fired:
        post_event("remi", f"Remi reminded you: {what}")
    try:
        release_held()  # what the typing guard held, now that you've stopped
    except Exception as e:
        print(f"releasing held posts failed: {e!r}")
    for job in (event_nudges, focus_tick, run_sleep, convo_sweep, notifs_tick):  # Stage 9: none of them may stop reminders
        try:
            job(now)
        except Exception as e:
            print(f"{job.__name__} failed in tick: {e!r}")
    digest = False
    local = datetime.fromtimestamp(now, hub_tz())
    try:
        daily_nudge(local)
    except Exception as e:  # never let the checklist stop reminders
        print(f"daily nudge failed: {e!r}")
    try:
        lenz_feeds_check(now)
    except Exception as e:  # nor Lenz's channels
        print(f"lenz feeds failed: {e!r}")
    if digest_due(local):  # the tick runs every 5 minutes, so the digest goes out on time
        try:
            digest = send_digest(opener=False, now=local)
        except Exception as e:  # never let the digest stop reminders
            print(f"digest failed in tick: {e!r}")
    return {"fired": fired, "nagged": nagged, "digest": digest}


_ACK_RE = re.compile(r"\b(done|did it|took (?:it|them|my \w+)|taken|finished|handled|all set)\b", re.I)


def remi_quick_reply(text):
    """Remi handles reminders herself, with no model call: "remind me ..."
    sets one; "done" or "took them" marks the latest nagging one done."""
    if re.search(r"\bremind me\b", text, re.I):
        try:
            r = add_reminder(re.sub(r"@\w+", "", text))
        except ValueError as e:
            return f"Happy to, love. {e}"
        return f"Got it. I'll remind you: {reminder_line(r)}."
    pending = [r for r in reminders() if r.get("pending")]
    if pending and _ACK_RE.search(text):
        r = ack_reminder(pending[-1]["id"])
        return f"Thank you, sweetheart. Marked done: {r['what']}."
    return None
