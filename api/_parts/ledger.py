"""Glass's ledger: expenses and budgets.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Glass's ledger: expenses from chat ("@glass $42 groceries"), bots, or
# Rocket Money CSV exports, against monthly budgets (GLASS_BUDGETS
# "Groceries:600,Dining:200"). GLASS_CATEGORY_MAP renames categories
# ("Restaurants:Dining,Coffee:Dining"). Rocket Money has no public API.
def _pairs(env):
    return [(k.strip(), v.strip()) for k, v in (p.split(":", 1) for p in os.environ.get(env, "").split(",") if ":" in p)]


GLASS_BUDGETS = {}
for _k, _v in _pairs("GLASS_BUDGETS"):
    try:
        GLASS_BUDGETS[_k] = float(_v)
    except ValueError:
        pass
GLASS_CATEGORY_MAP = {k.lower(): v for k, v in _pairs("GLASS_CATEGORY_MAP")}
_SKIP_CATEGORIES = ("income", "paycheck", "transfer", "credit card payment", "loan payment", "refund")


def ledger_category(raw):
    """A budget category for a raw category name (map, then case-insensitive match)."""
    raw = (raw or "").strip()
    mapped = GLASS_CATEGORY_MAP.get(raw.lower(), raw)
    for name in GLASS_BUDGETS:
        if name.lower() == mapped.lower():
            return name
    return mapped or "Other"


def _expense(day, amount, category, note, source, salt=""):
    key = hashlib.sha1(f"{day}|{note.lower()}|{amount:.2f}|{source}|{salt}".encode()).hexdigest()[:16]
    return key, {"date": day.isoformat(), "amount": round(amount, 2), "category": ledger_category(category),
                 "note": note[:120], "source": source, "at": time.time()}


def add_expense(amount, category, note="", day=None, source="chat"):
    """Log one expense; returns the stored expense."""
    day = day or datetime.now(hub_tz()).date()
    # each entry gets its own id, so the same purchase logged twice counts twice
    key, exp = _expense(day, amount, category, note, source, salt=str(time.time_ns()))
    store().add_expenses(day.strftime("%Y-%m"), {key: exp})
    return exp


_AMOUNT = re.compile(r"\$\s?(\d{1,7}(?:,\d{3})*(?:\.\d{1,2})?)")


_GLASS_UNDO = re.compile(r"^(?:undo|undo (?:that|the last one|last)|delete (?:that|the last one)|remove (?:that|the last one))[.!]?$", re.I)
_NOT_SPENDING = re.compile(r"\b(?:deposit\w*|balance|refund\w*|paycheck|income|salary|earned|got paid|transfer\w*|"
                           r"set|reset|tried|attempted|meant|didn't|did not|happened|explain\w*)\b", re.I)


def looks_like_purchase(text):
    """Log it at once only if it plainly is one: '$42 groceries', 'spent $12 on lunch',
    'paid $80 for gas'. Anything else (deposits, balances, a story with a dollar sign
    in it, $0) goes to the desk instead, so it can't land as spending by mistake."""
    clean = re.sub(r"@\w+[\s,]*", "", text).strip()
    m = _AMOUNT.search(clean)
    if not m or float(m.group(1).replace(",", "")) <= 0 or _NOT_SPENDING.search(clean):
        return False
    return bool(re.match(r"^(?:\$|(?:i\s+)?(?:spent|paid|bought|got)\b)", clean, re.I)) and len(clean.split()) <= 12


def glass_undo():
    """Remove the last expense logged from chat this month."""
    month = datetime.now(hub_tz()).strftime("%Y-%m")
    items = [(k, e) for k, e in store().expense_items(month).items() if e.get("source") == "chat"]
    if not items:
        return "Nothing logged from chat this month to undo."
    k, e = max(items, key=lambda kv: (kv[1]["date"], kv[1].get("at", 0)))
    store().remove_expenses(month, [k])
    return f"Removed ${e['amount']:,.2f} for {e['category']} ({e['note']}) from {e['date']}."


def parse_expense(text):
    """'@glass $42.50 groceries at Costco' -> (42.5, 'Groceries', 'groceries at Costco'), or None."""
    m = _AMOUNT.search(text)
    if not m:
        return None
    amount = float(m.group(1).replace(",", ""))
    if amount <= 0:  # "$0" is never spending
        return None
    rest = re.sub(r"@\w+", "", (text[:m.start()] + text[m.end():])).strip(" ,.-:")
    words = rest.lower()
    names = list(GLASS_BUDGETS) + [v for v in GLASS_CATEGORY_MAP.values()]
    category = next((n for n in names if n.lower() in words), None)
    if not category:
        category = next((v for k, v in GLASS_CATEGORY_MAP.items() if k in words), "Other")
    return amount, category, rest or category


def month_status(month=None):
    """{category: {"spent", "budget"}} for a month ("YYYY-MM"), budgets first."""
    month = month or datetime.now(hub_tz()).strftime("%Y-%m")
    out = {c: {"spent": 0.0, "budget": b} for c, b in GLASS_BUDGETS.items()}
    for e in store().list_expenses(month):
        out.setdefault(e["category"], {"spent": 0.0, "budget": None})["spent"] += e["amount"]
    return out


def status_lines(month=None):
    lines = []
    for cat, v in month_status(month).items():
        if v["budget"]:
            lines.append(f"{cat}: ${v['spent']:,.2f} of ${v['budget']:,.0f} ({v['spent'] / v['budget']:.0%})")
        elif v["spent"]:
            lines.append(f"{cat}: ${v['spent']:,.2f} (no budget)")
    return lines


def glass_log_reply(parsed):
    """Log a chat expense; Glass confirms with exact numbers (no model call)."""
    amount, category, note = parsed
    exp = add_expense(amount, category, note)
    try:
        money_alert(amount, exp["category"])  # big purchase, or the budget passing 80% / 100%
    except Exception as e:
        print(f"money alert failed: {e!r}")
    v = month_status()[exp["category"]]
    tail = (f" {exp['category']} this month: ${v['spent']:,.2f} of ${v['budget']:,.0f}."
            if v["budget"] else f" {exp['category']} this month: ${v['spent']:,.2f} (no budget set).")
    return f"Logged ${amount:,.2f} for {exp['category']} ({note}).{tail}"


def _parse_day(text):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass
    return None


def import_csv(text):
    """Import a Rocket Money (or similar) transactions CSV. Columns are found
    by header; whether expenses are positive or negative is read from the
    file (most rows are spending). Income, transfers, card payments and
    rows marked ignored are skipped; re-importing is safe (deduped)."""
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    if not rows:
        return {"ok": False, "error": "no rows found"}
    cols = {c.strip().lower(): c for c in rows[0].keys() if c}

    def col(*names):
        return next((cols[n] for n in names if n in cols), None)
    c_date, c_amount = col("date", "transaction date", "original date"), col("amount")
    c_name, c_custom = col("name", "description", "merchant", "payee"), col("custom name")
    c_cat, c_ignored = col("category"), col("ignored from")
    if not (c_date and c_amount):
        return {"ok": False, "error": f"need Date and Amount columns; found {', '.join(cols.values())}"}
    parsed, skipped = [], {"income/transfers": 0, "ignored": 0, "unreadable": 0}
    for r in rows:
        day = _parse_day(r.get(c_date) or "")
        try:
            amount = float((r.get(c_amount) or "").replace("$", "").replace(",", ""))
        except ValueError:
            amount = None
        if day is None or amount is None:
            skipped["unreadable"] += 1
            continue
        cat = (r.get(c_cat) or "").strip() if c_cat else ""
        if c_ignored and (r.get(c_ignored) or "").strip():
            skipped["ignored"] += 1
            continue
        if any(k in cat.lower() for k in _SKIP_CATEGORIES):
            skipped["income/transfers"] += 1
            continue
        note = ((r.get(c_custom) or "").strip() if c_custom else "") or ((r.get(c_name) or "").strip() if c_name else "")
        parsed.append((day, amount, cat, note))
    positive = sum(1 for p in parsed if p[1] > 0)
    sign = 1 if positive >= len(parsed) - positive else -1  # spending is the majority
    by_month = {}
    for day, amount, cat, note in parsed:
        if amount * sign <= 0:
            skipped["income/transfers"] += 1  # money in, e.g. refunds
            continue
        key, exp = _expense(day, amount * sign, cat, note, "csv")
        by_month.setdefault(day.strftime("%Y-%m"), {})[key] = exp
    added = sum(store().add_expenses(m, rows_) for m, rows_ in by_month.items())
    total = sum(len(v) for v in by_month.values())
    return {"ok": True, "added": added, "duplicates": total - added, "skipped": skipped,
            "expenses_were": "positive" if sign > 0 else "negative",
            "columns": {k: v for k, v in {"date": c_date, "amount": c_amount, "name": c_custom or c_name,
                                          "category": c_cat}.items() if v},
            "months": sorted(by_month)}


def glass_context():
    month = datetime.now(hub_tz()).strftime("%Y-%m")
    lines = status_lines(month)
    recent = sorted(store().list_expenses(month), key=lambda e: e["date"])[-8:]
    if not (lines or recent):
        return ("\n\nNo expenses logged this month yet. People log them with '@glass $42 groceries'."
                + stock_context())
    return (f"\n\nThis month ({month}) so far (exact; never invent numbers):\n"
            + "\n".join(f"- {x}" for x in lines)
            + ("\nRecent expenses:\n" + "\n".join(f"- {e['date']} ${e['amount']:,.2f} {e['category']}: {e['note']}"
                                                  for e in recent) if recent else "") + stock_context())
