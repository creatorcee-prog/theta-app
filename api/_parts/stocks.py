"""Glass's stocks (Finnhub).

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Glass, analyst: your holdings and watchlist from Finnhub (free key).
# Prices each round, big-move and earnings heads-ups, and a Sunday note
# comparing your holdings with the S&P 500. She reports; she never trades
# or tells you to buy or sell.
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
FINNHUB_BASE = "https://finnhub.io/api/v1"
GLASS_WATCHLIST = [s.strip().upper() for s in os.environ.get("GLASS_WATCHLIST", "").split(",") if s.strip()]
GLASS_BENCHMARK = os.environ.get("GLASS_BENCHMARK", "SPY").strip().upper()  # an S&P 500 fund
GLASS_MOVE_ALERT = float(os.environ.get("GLASS_MOVE_ALERT", "5"))  # % in a day


def _holdings():
    """GLASS_HOLDINGS like 'AAPL:10,VTI:25.5' -> {'AAPL': 10.0, 'VTI': 25.5}."""
    out = {}
    for part in os.environ.get("GLASS_HOLDINGS", "").split(","):
        sym, _, qty = part.partition(":")
        try:
            if sym.strip():
                out[sym.strip().upper()] = float(qty.split("@")[0])
        except ValueError:
            continue
    return out


GLASS_HOLDINGS = _holdings()


def stock_symbols():
    return list(dict.fromkeys(list(GLASS_HOLDINGS) + GLASS_WATCHLIST + [GLASS_BENCHMARK]))


def stocks_on():
    return bool(FINNHUB_API_KEY and (GLASS_HOLDINGS or GLASS_WATCHLIST))


def finnhub(path, **params):
    req = urllib.request.Request(FINNHUB_BASE + path + "?" + urlencode(params), headers={
        "X-Finnhub-Token": FINNHUB_API_KEY, "User-Agent": WIKI_UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise LLMError(f"Finnhub returned {e.code}" + (": check FINNHUB_API_KEY" if e.code in (401, 403) else ""))
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise LLMError(f"Finnhub unreachable: {e!r}")


def stock_quotes():
    return _meta_json("stocks:quotes", {})


def stock_history():
    """{date: {symbol: close}}, one entry per day, the latest price of that day."""
    return _meta_json("stocks:hist", {})


def refresh_stocks(today=None):
    """Prices for every symbol; saves today's into the history."""
    today = today or datetime.now(hub_tz()).date()
    syms = stock_symbols()
    with ThreadPoolExecutor(max_workers=min(8, len(syms))) as ex:
        got = dict(zip(syms, ex.map(lambda s: finnhub("/quote", symbol=s), syms)))
    quotes = {s: {"c": q.get("c"), "dp": q.get("dp"), "pc": q.get("pc"), "t": q.get("t")}
              for s, q in got.items() if q.get("c")}
    if not quotes:
        raise LLMError("Finnhub gave no prices (check the symbols in GLASS_HOLDINGS / GLASS_WATCHLIST).")
    hist = stock_history()
    hist[today.isoformat()] = {s: q["c"] for s, q in quotes.items()}
    store().set_meta("stocks:quotes", json.dumps(quotes))
    store().set_meta("stocks:hist", json.dumps(dict(sorted(hist.items())[-400:])))
    return quotes


def portfolio_value(prices):
    return sum(q * prices[s] for s, q in GLASS_HOLDINGS.items() if prices.get(s))


def _price_on(hist, day):
    """The latest saved prices on or before `day`."""
    keys = [k for k in sorted(hist) if k <= day.isoformat()]
    return hist[keys[-1]] if keys else None


def portfolio_series():
    """[(date, holdings index, benchmark index)], both 100 on the first day
    with prices for everything held (so they share one axis)."""
    out, base = [], None
    for day, prices in sorted(stock_history().items()):
        if not GLASS_HOLDINGS or not prices.get(GLASS_BENCHMARK) or any(s not in prices for s in GLASS_HOLDINGS):
            continue
        v = portfolio_value(prices)
        if base is None:
            base = (v, prices[GLASS_BENCHMARK])
        out.append((day, 100 * v / base[0], 100 * prices[GLASS_BENCHMARK] / base[1]))
    return out


def stock_context():
    if not stocks_on():
        return ""
    q = stock_quotes()
    rows = [f"- {s}: ${q[s]['c']:,.2f} ({q[s]['dp']:+.2f}% today)" + (f", you hold {GLASS_HOLDINGS[s]:g}" if s in GLASS_HOLDINGS else "")
            for s in stock_symbols() if s in q and q[s].get("dp") is not None]
    if not rows:
        return ""
    total = portfolio_value({s: v["c"] for s, v in q.items()})
    return ("\n\nStocks (exact, from Finnhub; you analyse, you never advise buying or selling):\n" + "\n".join(rows)
            + (f"\nHoldings worth ${total:,.2f}." if total else ""))


def _week_change(hist, sym_or_none, today):
    now, then = _price_on(hist, today), _price_on(hist, today - timedelta(days=7))
    if not now or not then or now is then:
        return None
    if sym_or_none:
        return (now[sym_or_none] / then[sym_or_none] - 1) * 100 if now.get(sym_or_none) and then.get(sym_or_none) else None
    a, b = portfolio_value(now), portfolio_value(then)
    return (a / b - 1) * 100 if a and b else None


def _round_stocks(today):
    """Prices, big moves, earnings within a week, and Sunday's note."""
    st = store()
    did = []
    quotes = refresh_stocks(today)
    moved = _meta_json("stocks:moved", {})
    for s, q in quotes.items():
        if s == GLASS_BENCHMARK and s not in GLASS_HOLDINGS and s not in GLASS_WATCHLIST:
            continue
        if q.get("dp") is not None and abs(q["dp"]) >= GLASS_MOVE_ALERT and moved.get(s) != q.get("t"):
            moved[s] = q.get("t")  # once per trading day (weekends repeat Friday's quote)
            line = (f"{s} is {'up' if q['dp'] > 0 else 'down'} {abs(q['dp']):.1f}% today, at ${q['c']:,.2f}"
                    + (f" (your {GLASS_HOLDINGS[s]:g} shares: {'+' if q['dp'] > 0 else '-'}$"
                       f"{abs(GLASS_HOLDINGS[s] * (q['c'] - q['pc'])):,.2f})." if s in GLASS_HOLDINGS and q.get("pc") else "."))
            st.add_chat("glass", line, channel="money")
            notify("Glass", line, "/money#stocks")
            did.append(f"{s} moved {q['dp']:+.1f}%")
    st.set_meta("stocks:moved", json.dumps(moved))
    if st.get_meta("stocks:earn_day") != today.isoformat():  # once a day
        st.set_meta("stocks:earn_day", today.isoformat())
        told = set(_meta_json("stocks:earn_told", []))
        soon = []
        for s in [x for x in stock_symbols() if x != GLASS_BENCHMARK]:
            try:
                cal = finnhub("/calendar/earnings", symbol=s, **{"from": today.isoformat(),
                                                                   "to": (today + timedelta(days=7)).isoformat()})
            except LLMError:
                continue
            for e in cal.get("earningsCalendar", []):
                key = f"{s}:{e.get('date')}"
                if e.get("date") and key not in told:
                    told.add(key)
                    when = {"bmo": "before the open", "amc": "after the close"}.get(e.get("hour"), "")
                    d = date.fromisoformat(e["date"])
                    soon.append(f"{s} {d:%a %b} {d.day}" + (f" {when}" if when else ""))
        st.set_meta("stocks:earn_told", json.dumps(sorted(told)[-200:]))
        if soon:
            st.add_chat("glass", "Earnings this week: " + "; ".join(soon) + ". Expect bigger moves around them.",
                        channel="money")
            did.append("flagged earnings")
    if today.weekday() == 6 and st.get_meta("stocks:note_day") != today.isoformat():
        st.set_meta("stocks:note_day", today.isoformat())
        did.append(stock_week_note(today))
    return did


def stock_week_note(today):
    """Sunday: the week in numbers, a few headlines, one model call to put
    it in plain words (facts only, no advice)."""
    hist = stock_history()
    mine, bench = _week_change(hist, None, today), _week_change(hist, GLASS_BENCHMARK, today)
    facts = []
    if mine is not None and bench is not None:
        facts.append(f"Your holdings {mine:+.2f}% this week; the S&P 500 ({GLASS_BENCHMARK}) {bench:+.2f}%.")
    movers = sorted(((s, _week_change(hist, s, today)) for s in stock_symbols() if s != GLASS_BENCHMARK),
                    key=lambda x: -abs(x[1] or 0))
    facts += [f"{s}: {c:+.2f}% this week" + (" (held)" if s in GLASS_HOLDINGS else " (watching)")
              for s, c in movers[:5] if c is not None]
    heads = []
    for s in list(GLASS_HOLDINGS)[:5]:
        try:
            news = finnhub("/company-news", symbol=s, **{"from": (today - timedelta(days=7)).isoformat(), "to": today.isoformat()})
        except LLMError:
            continue
        if news:
            heads.append(f"{s}: {news[0].get('headline', '')} ({news[0].get('source', '')})")
    if not facts:
        return "not enough price history for a weekly note yet"
    try:
        take = llm_chat(AGENTS["glass"]["tier"], [
            {"role": "system", "content": system_prompt("glass")},
            {"role": "user", "content": "Facts:\n" + "\n".join(facts) + ("\nHeadlines:\n" + "\n".join(heads) if heads else "")
             + "\n\nWrite 2-3 plain sentences on what stood out this week, using only these facts. No predictions, "
             "no buy/sell/hold advice."}], max_tokens=400).strip()
    except LLMError:
        take = ""
    post = "Your stocks this week:\n" + "\n".join(f"- {f}" for f in facts) + (f"\n{take}" if take else "") + (
        "\nIn the news:\n" + "\n".join(f"- {h}" for h in heads) if heads else "")
    store().add_chat("glass", post, channel="money")
    save_card("glass", "Your stocks this week", post)
    return "posted the stock week"


_STOCK_CHART_JS = r"""
(() => {
  // Crosshair + tooltip for the holdings-vs-S&P chart.
  const box = document.getElementById("pf-chart"); if (!box) return;
  const pts = JSON.parse(box.dataset.pts), svg = box.querySelector("svg"), tip = box.querySelector(".pf-tip"),
    line = svg.querySelector(".pf-x"), W = +svg.viewBox.baseVal.width;
  const fmt = v => (v >= 100 ? "+" : "") + (v - 100).toFixed(1) + "%";
  function show(e) {
    const r = svg.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * W;
    let best = pts[0];
    for (const p of pts) if (Math.abs(p.x - x) < Math.abs(best.x - x)) best = p;
    line.setAttribute("x1", best.x); line.setAttribute("x2", best.x); line.style.opacity = 1;
    tip.innerHTML = "<b>" + best.d + "</b><br><i class=s1></i>Your holdings " + fmt(best.a) + "<br><i class=s2></i>S&amp;P 500 " + fmt(best.b);
    tip.style.opacity = 1;
    const left = (best.x / W) * r.width;
    tip.style.left = Math.min(Math.max(left - tip.offsetWidth / 2, 0), r.width - tip.offsetWidth) + "px";
  }
  svg.addEventListener("pointermove", show);
  svg.addEventListener("pointerdown", show);
  svg.addEventListener("pointerleave", () => { tip.style.opacity = 0; line.style.opacity = 0; });
})();
"""


def stock_chart_html(series):
    """Two lines on one axis: holdings and the S&P 500, both indexed to 100."""
    w, h, l, r, t, b = 360, 190, 34, 106, 10, 24  # drawn near phone size so its text stays readable
    vals = [v for _, a, c in series for v in (a, c)]
    lo, hi = min(vals + [100]), max(vals + [100])
    pad = max((hi - lo) * 0.12, 0.5)
    lo, hi = lo - pad, hi + pad
    X = lambda i: l + (w - l - r) * (i / max(1, len(series) - 1))
    Y = lambda v: t + (h - t - b) * (1 - (v - lo) / (hi - lo))
    path = lambda k: "M" + " L".join(f"{X(i):.1f} {Y(p[k]):.1f}" for i, p in enumerate(series))
    grid = "".join(f'<line x1="{l}" x2="{w - r}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="pf-g"/>'
                   f'<text x="{l - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{v - 100:+.0f}%</text>'
                   for v in sorted({round(lo + (hi - lo) * f) for f in (0.1, 0.5, 0.9)} | {100}) if lo <= v <= hi)
    first, last = series[0][0], series[-1][0]
    end_a, end_b = Y(series[-1][1]), Y(series[-1][2])
    if abs(end_a - end_b) < 14:  # keep the two end labels apart
        mid = (end_a + end_b) / 2
        end_a, end_b = (mid - 7, mid + 7) if end_a <= end_b else (mid + 7, mid - 7)
    pts = [{"x": round(X(i), 1), "d": d, "a": round(a, 2), "b": round(c, 2)} for i, (d, a, c) in enumerate(series)]
    svg = (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Your holdings against the S&amp;P 500 since {first}">'
           f'{grid}<path d="{path(2)}" class="pf-l s2"/><path d="{path(1)}" class="pf-l s1"/>'
           f'<line class="pf-x" y1="{t}" y2="{h - b}" x1="0" x2="0"/>'
           f'<text x="{X(len(series) - 1) + 8:.1f}" y="{end_a + 4:.1f}" class="pf-lab">Holdings {series[-1][1] - 100:+.1f}%</text>'
           f'<text x="{X(len(series) - 1) + 8:.1f}" y="{end_b + 4:.1f}" class="pf-lab">S&amp;P {series[-1][2] - 100:+.1f}%</text>'
           f'<text x="{l}" y="{h - 8}">{first}</text><text x="{w - r}" y="{h - 8}" text-anchor="end">{last}</text></svg>')
    rows = "".join(f"<tr><td>{d}</td><td>{a - 100:+.1f}%</td><td>{c - 100:+.1f}%</td></tr>" for d, a, c in series[-30:])
    return (f'<div class="pf"><div class="pf-legend"><span><i class="s1"></i>Your holdings</span>'
            f'<span><i class="s2"></i>S&amp;P 500 ({html.escape(GLASS_BENCHMARK)})</span></div>'
            f'<div id="pf-chart" data-pts="{html.escape(json.dumps(pts))}">{svg}<div class="pf-tip" role="status"></div></div>'
            f'<details><summary class="muted small">Table</summary><table class="pf-t"><tr><th>Day</th><th>Holdings</th>'
            f'<th>S&amp;P 500</th></tr>{rows}</table></details></div><script>{_STOCK_CHART_JS}</script>')


def stocks_card():
    if not FINNHUB_API_KEY:
        return ('<section class="card stack" id="stocks" style="margin-top:14px"><h2>Stocks</h2><p class="muted small">Glass can '
                'watch your stocks: get a free key at finnhub.io, then set <code>FINNHUB_API_KEY</code>, '
                '<code>GLASS_HOLDINGS</code> (like <code>AAPL:10,VTI:25</code>) and/or <code>GLASS_WATCHLIST</code> '
                '(like <code>NVDA,MSFT</code>) in Vercel.</p></section>')
    q = stock_quotes()
    rows = []
    for s in stock_symbols():
        v = q.get(s)
        if not v:
            continue
        held = GLASS_HOLDINGS.get(s)
        dp = v.get("dp") or 0
        value = f"${held * v['c']:,.2f}" if held else ""
        tag = f"{held:g} shares" if held else "benchmark" if s == GLASS_BENCHMARK else "watching"
        rows.append(f'<tr><td><b>{html.escape(s)}</b><div class="muted small">{tag}</div></td>'
                    f'<td>${v["c"]:,.2f}</td><td class="{"up" if dp > 0 else "down" if dp < 0 else ""}">{"▲" if dp > 0 else "▼" if dp < 0 else ""} {dp:+.2f}%</td>'
                    f'<td>{value}</td></tr>')
    total = portfolio_value({s: v["c"] for s, v in q.items()})
    series = portfolio_series()
    chart = (stock_chart_html(series) if len(series) >= 2 else
             '<p class="muted small">The chart against the S&amp;P 500 starts once Glass has two days of prices.</p>'
             if GLASS_HOLDINGS else "")
    note = next((m["text"] for m in reversed(store().list_chat(ALLCHAT_KEEP))
                 if m["from"] == "glass" and m["text"].startswith("Your stocks this week")), "")
    return ('<section class="card stack" id="stocks" style="margin-top:14px"><div class="brow"><h2>Stocks</h2>'
            + (f'<span class="muted small">Holdings ${total:,.2f}</span>' if total else "") + '</div>'
            + (f'<table class="pf-t"><tr><th>Symbol</th><th>Price</th><th>Today</th><th>Value</th></tr>{"".join(rows)}</table>'
               if rows else '<p class="muted small">Prices arrive with Glass\'s next round.</p>')
            + chart + (f'<div class="text small">{html.escape(note)}</div>' if note else "")
            + '<p class="muted small">From Finnhub. Glass reports and explains; she doesn\'t give buy or sell advice.</p></section>')


def _round_glass(ctx):
    """Budget alerts at 90% and 100% (once each per category per month), and a
    week-in-review on the first round of each Sunday."""
    st = store()
    today = datetime.now(hub_tz()).date()
    month = today.strftime("%Y-%m")
    did = []
    alerted = set(json.loads(st.get_meta(f"round:glass:alerts:{month}") or "[]"))
    for cat, v in month_status(month).items():
        if not v["budget"]:
            continue
        share = v["spent"] / v["budget"]
        level = "100" if share >= 1 else "90" if share >= 0.9 else None
        if level and f"{cat}:{level}" not in alerted:
            alerted.add(f"{cat}:{level}")
            alert = (f"{cat} is over budget: ${v['spent']:,.2f} of ${v['budget']:,.0f}."
                     if level == "100" else
                     f"Heads up: {cat} is at {share:.0%} of its budget "
                     f"(${v['spent']:,.2f} of ${v['budget']:,.0f}).")
            st.add_chat("glass", alert)
            notify("Mistral", f"Glass: {alert}")
            did.append(f"{cat} alert")
    st.set_meta(f"round:glass:alerts:{month}", json.dumps(sorted(alerted)))
    if today.weekday() == 6 and st.get_meta("round:glass:week") != today.isoformat():
        week = [e for m in {month, (today - timedelta(days=6)).strftime("%Y-%m")}
                for e in st.list_expenses(m) if (today - timedelta(days=6)).isoformat() <= e["date"] <= today.isoformat()]
        by_cat = {}
        for e in week:
            by_cat[e["category"]] = by_cat.get(e["category"], 0) + e["amount"]
        lines = [f"Week in review (through {today:%b %d}): ${sum(by_cat.values()):,.2f} spent."]
        lines += [f"- {c}: ${a:,.2f}" for c, a in sorted(by_cat.items(), key=lambda x: -x[1])]
        lines += ["Month so far:"] + [f"- {x}" for x in status_lines(month)]
        st.add_chat("glass", "\n".join(lines))
        st.set_meta("round:glass:week", today.isoformat())
        did.append("posted the week in review")
    if stocks_on():
        try:
            did += _round_stocks(today)
        except LLMError as e:
            did.append(f"stocks failed ({str(e)[:80]})")
    if not GLASS_BUDGETS and not st.list_expenses(month) and not stocks_on():
        return "no budgets or expenses yet"
    return ", ".join(did) or ("budgets on track" + (", stocks quiet" if stocks_on() else ""))


def _round_charter(ctx):
    """Sundays: this month's spending chart next to Glass's week in review."""
    st = store()
    today = datetime.now(hub_tz()).date()
    if today.weekday() != 6 or st.get_meta("round:charter:week") == today.isoformat():
        return "no chart due"
    if not st.list_expenses(today.strftime("%Y-%m")):
        return "no spending to chart"
    caption, svg = _chart_spending()
    st.add_chat("charter", caption, image=save_chart(svg))
    st.set_meta("round:charter:week", today.isoformat())
    return "posted the spending chart"
