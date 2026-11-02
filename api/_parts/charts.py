"""Charter's charts.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Charter's charts: SVG drawn here from data the hub already has (no
# library, no tokens). Stored in meta as chart:<id>, served at /chart/<id>.svg;
# the newest CHART_KEEP are kept.
CHART_KEEP = 30


def _x(text):
    return html.escape(str(text), quote=True)


def bar_chart_svg(title, rows, money=False, limits=None):
    """Horizontal bars. rows: [(label, value)]; limits: {label: budget} draws
    a budget tick per row. Scale: 0 to the largest value or limit."""
    limits = limits or {}
    w, left, right, top, row_h = 640, 150, 90, 46, 30
    h = top + row_h * max(1, len(rows)) + 20
    biggest = max([v for _, v in rows] + [l for l in limits.values() if l] + [1])
    fmt = (lambda v: f"${v:,.0f}") if money else (lambda v: f"{v:,.0f}")
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
           f'font-family="system-ui,sans-serif" font-size="13">',
           f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
           f'<text x="16" y="28" font-size="16" font-weight="bold" fill="#17202b">{_x(title)}</text>']
    span = w - left - right
    for i, (label, value) in enumerate(rows):
        y = top + i * row_h
        bw = span * value / biggest
        limit = limits.get(label)
        color = "#b3261e" if limit and value > limit else "#2f5bd3"  # red only means over budget
        out.append(f'<text x="{left - 8}" y="{y + 18}" text-anchor="end" fill="#17202b">{_x(label)[:22]}</text>')
        if limit:  # light track up to the budget, so the bar and its label read as one row
            out.append(f'<rect x="{left}" y="{y + 5}" width="{span * limit / biggest:.1f}" height="18" fill="#e4e8ee"/>')
        out.append(f'<rect x="{left}" y="{y + 5}" width="{max(bw, 1):.1f}" height="18" fill="{color}"/>')
        if limit:
            lx = left + span * limit / biggest
            out.append(f'<line x1="{lx:.1f}" x2="{lx:.1f}" y1="{y + 1}" y2="{y + 27}" stroke="#17202b" stroke-width="2"/>')
        tail = fmt(value) + (f" of {fmt(limit)}" if limit else "")
        label_x = left + max(bw, span * limit / biggest if limit else 0, 1) + 6  # clear of the tick
        out.append(f'<text x="{label_x:.1f}" y="{y + 18}" fill="#5a6573">{_x(tail)}</text>')
    if not rows:
        out.append(f'<text x="{left}" y="{top + 18}" fill="#5a6573">No data yet</text>')
    out.append("</svg>")
    return "".join(out)


def column_chart_svg(title, cols, money=False):
    """Vertical bars over time. cols: [(label, value)], labels thinned to fit."""
    w, h, left, bottom, top = 640, 300, 56, 40, 46
    span_w, span_h = w - left - 16, h - top - bottom
    biggest = max([v for _, v in cols] + [1])
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
           f'font-family="system-ui,sans-serif" font-size="12">',
           f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
           f'<text x="16" y="28" font-size="16" font-weight="bold" fill="#17202b">{_x(title)}</text>']
    for frac in (0, 0.5, 1):
        y = top + span_h * (1 - frac)
        val = biggest * frac
        out.append(f'<line x1="{left}" x2="{w - 16}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e4e8ee"/>')
        out.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end" fill="#5a6573">'
                   f'{_x(f"${val:,.0f}" if money else f"{val:,.0f}")}</text>')
    n = max(1, len(cols))
    slot = span_w / n
    every = max(1, round(n / 10))
    for i, (label, value) in enumerate(cols):
        bh = span_h * value / biggest
        x = left + i * slot
        out.append(f'<rect x="{x + slot * 0.15:.1f}" y="{top + span_h - bh:.1f}" width="{slot * 0.7:.1f}" '
                   f'height="{bh:.1f}" fill="#2f5bd3"/>')
        if i % every == 0:
            out.append(f'<text x="{x + slot / 2:.1f}" y="{h - bottom + 16}" text-anchor="middle" fill="#5a6573">{_x(label)}</text>')
    out.append("</svg>")
    return "".join(out)


def _chart_spending(month=None):
    month = month or datetime.now(hub_tz()).strftime("%Y-%m")
    st = month_status(month)
    rows = sorted(((c, v["spent"]) for c, v in st.items() if v["spent"] or v["budget"]), key=lambda r: -r[1])
    over = [c for c, v in st.items() if v["budget"] and v["spent"] > v["budget"]]
    top_cat = rows[0] if rows and rows[0][1] else None
    caption = (f"Spending by category for {month}"
               + (f": {top_cat[0]} leads at ${top_cat[1]:,.2f}" if top_cat else ": nothing logged yet")
               + (f"; over budget: {', '.join(over)}" if over else "") + ".")
    return caption, bar_chart_svg(f"Spending by category, {month}", rows, money=True,
                                  limits={c: v["budget"] for c, v in st.items() if v["budget"]})


def _chart_daily(month=None):
    today = datetime.now(hub_tz()).date()
    month = month or today.strftime("%Y-%m")
    per = {}
    for e in store().list_expenses(month):
        per[e["date"]] = per.get(e["date"], 0) + e["amount"]
    first = date.fromisoformat(month + "-01")
    days = [(first + timedelta(d)) for d in range(31) if (first + timedelta(d)).month == first.month
            and (first + timedelta(d)) <= today]
    cols = [(str(d.day), per.get(d.isoformat(), 0)) for d in days]
    total = sum(v for _, v in cols)
    return (f"Daily spending for {month}: ${total:,.2f} so far.",
            column_chart_svg(f"Daily spending, {month}", cols, money=True))


def _chart_calendar():
    today = datetime.now(hub_tz()).date()
    days = [today + timedelta(d) for d in range(14)]
    counts = {d: 0 for d in days}
    for o in calendar_events(days[0], days[-1]) if calendar_linked() else []:
        d = o["start"] if o["all_day"] else o["start"].date()
        if d in counts and not o["birthday"]:
            counts[d] += 1
    busiest = max(days, key=lambda d: counts[d])
    caption = ("Events per day for the next two weeks"
               + (f"; busiest is {busiest:%a %b %d} with {counts[busiest]}." if counts[busiest] else ": nothing scheduled."))
    return caption, column_chart_svg("Events per day, next 14 days",
                                     [(f"{d:%m/%d}", counts[d]) for d in days])


def _chart_coverage():
    raw = store().get_meta("round:news:last")
    if not raw:
        return "No story has been covered in a round yet.", bar_chart_svg("Coverage", [])
    last = json.loads(raw)
    rows = [(f"{AGENTS[a]['name']}'s outlets", last["coverage"].get(a, 0)) for a in ("red", "blue", "gray")]
    return (f"How many of each side's outlets covered \"{last['title'][:80]}\".",
            bar_chart_svg("Outlets covering the latest story", rows))


def _chart_activity():
    counts = {}
    for m in store().list_chat(ALLCHAT_KEEP):
        if m.get("kind") != "event" and m["from"] in AGENTS:
            counts[AGENTS[m["from"]]["name"]] = counts.get(AGENTS[m["from"]]["name"], 0) + 1
    rows = sorted(counts.items(), key=lambda r: -r[1])
    return ("Messages per agent in the recent All Agents thread"
            + (f"; {rows[0][0]} has said the most." if rows else ": nobody has posted yet."),
            bar_chart_svg("Who's been talking (All Agents)", rows))


CHARTS = {  # name: (words that ask for it, builder)
    "daily": (("daily", "per day", "each day", "by day"), _chart_daily),
    "spending": (("spend", "budget", "money", "expense", "category"), _chart_spending),
    "calendar": (("calendar", "schedule", "busy", "events", "week ahead"), _chart_calendar),
    "coverage": (("coverage", "covered", "outlets", "news", "story"), _chart_coverage),
    "activity": (("activity", "talking", "messages", "posted"), _chart_activity),
}


def pick_chart(text):
    words = text.lower()
    return next((name for name, (keys, _) in CHARTS.items() if any(k in words for k in keys)), None)


def save_chart(svg):
    """Store an SVG; returns its URL."""
    st = store()
    cid = hashlib.sha1(f"{time.time_ns()}".encode()).hexdigest()[:12]
    st.set_meta(f"chart:{cid}", svg)
    ids = json.loads(st.get_meta("charts") or "[]")
    ids.append(cid)
    for old in ids[:-CHART_KEEP]:
        st.set_meta(f"chart:{old}", "")
    st.set_meta("charts", json.dumps(ids[-CHART_KEEP:]))
    return f"/chart/{cid}.svg"


def charter_reply(text):
    """(caption, image_url) when the text asks for a chart Charter can draw, else None."""
    name = pick_chart(text)
    if not name:
        return None
    caption, svg = CHARTS[name][1]()
    return caption, save_chart(svg)


def charter_context():
    return ("\n\nYou can draw these charts from real hub data when asked: spending by category, "
            "daily spending, calendar busyness, news coverage by side, and All Agents activity. "
            "You can't chart anything else yet (e.g. workouts); say so instead of making up numbers.")
