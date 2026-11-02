"""Slash commands and instant commands.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Slash commands: typed in either chat box ("/" opens the list, like
# Discord). Each one runs an agent's job on demand; outputs land in All
# Agents. Only you can run them (bots posting "/..." are just text).
class CommandError(Exception):
    """Unknown command or wrong usage; shown to you, not posted."""


def acknowledge_order(oid, request, agents):
    """Each agent says, in character, what it will do and what it can't."""
    def ack(a):
        try:
            if a == "james":
                return a, james_chat([{"role": "user", "content": f"Order from me: {request}. "
                                       "Acknowledge in 1-2 sentences: what will you do?"}]), None
            return a, llm_chat(AGENTS[a]["tier"], [
                {"role": "system", "content": system_prompt(a) + " You're in the All Agents group chat."},
                {"role": "user", "content": f"The user issued order #{oid}: \"{request}\". Acknowledge "
                 "it in 1-2 sentences: what you'll do to follow it, and plainly what part (if any) "
                 "is outside what you can do."}], max_tokens=400), None
        except LLMError as e:
            return a, None, str(e)
    acked, failed = [], []
    with ThreadPoolExecutor(max_workers=max(1, len(agents))) as ex:
        for a, text, err in ex.map(ack, agents):
            if text:
                store().add_chat(a, f"On order #{oid}: {text.strip()}")
                store().ack_order(oid, a)
                acked.append(AGENTS[a]["name"])
            else:
                failed.append(f"{AGENTS[a]['name']} ({err[:80]})")
    return acked, failed


def _cmd_commandeer(arg):
    if not arg:
        raise CommandError("Usage: /commandeer [@agent ...] <order>")
    if is_task(arg):  # "find me a job here": the crew works it as a project
        return start_project(arg)
    targets = mentioned_agents(arg)
    expires = time.time() + ORDER_DAYS * 86400
    oid = store().add_order(arg[:500], "you", targets=targets, expires_at=expires)
    who = ", ".join(AGENTS[a]["name"] for a in targets) or "the whole crew"
    post_event("you", f"You issued order #{oid} to {who}: {arg[:200]}")
    # Targeted agents acknowledge; for the whole crew, Theta answers as commander.
    acked, failed = acknowledge_order(oid, arg[:500], targets or ["theta"])
    until = datetime.fromtimestamp(expires, hub_tz())
    return (f"Order #{oid} to {who}, standing until {until:%b %d}."
            + (f" Acknowledged by {', '.join(acked)}." if acked else "")
            + (f" Couldn't acknowledge: {'; '.join(failed)}." if failed else ""))


def _order_line(o):
    to = ", ".join(display_name(t) for t in o.get("targets") or []) or "everyone"
    exp = o.get("expires_at")
    until = f", until {datetime.fromtimestamp(float(exp), hub_tz()):%b %d}" if exp else ""
    acks = f"; acknowledged by {', '.join(display_name(a) for a in o['acked_by'])}" if o.get("acked_by") else ""
    return f"#{o['id']} to {to} (from {display_name(o['issued_by'])}{until}{acks}): {o['request']}"


def _cmd_orders(arg):
    orders = store().list_active_orders()
    store().add_chat("hub", "Active orders:\n" + "\n".join(f"- {_order_line(o)}" for o in orders)
                     if orders else "No active orders.")
    return f"{len(orders)} active order(s)."


def _cmd_done(arg):
    try:
        oid = int(arg.strip().lstrip("#"))
    except ValueError:
        raise CommandError("Usage: /done <order number>, e.g. /done 12")
    order = store().close_order(oid)
    if not order:
        raise CommandError(f"No active order #{oid}. /orders lists them.")
    post_event("you", f"You closed order #{oid}: {order['request'][:200]}")
    return f"Closed order #{oid}."


def _cmd_round(arg):
    r = run_round(force=True)
    return f"Ran {len(r['ran'])} agents' jobs; the Round line says what each did."


def _cmd_digest(arg):
    post, _ = morning_digest()
    store().add_chat("mistral", post)
    return "Mistral posted the digest."


def _cmd_agenda(arg):
    if not calendar_linked():
        raise CommandError("Remi has no calendar yet: set REMI_CALENDAR_URLS in Vercel.")
    today = datetime.now(hub_tz()).date()
    day = today + timedelta(days=1) if arg.strip().lower() == "tomorrow" else today
    items = calendar_events(day, day)
    lines = [f"{'Tomorrow' if day != today else 'Today'}, {day:%A %B %d}:"] + (
        [f"- {occurrence_text(o)}" for o in items] or ["- Nothing on the calendar."])
    store().add_chat("remi", "\n".join(lines))
    return "Remi posted the agenda."


def _cmd_remind(arg):
    if not arg:
        raise CommandError("Try /remind 8am every day take my meds until done")
    try:
        r = add_reminder(arg)
    except ValueError as e:
        raise CommandError(str(e))
    store().add_chat("remi", f"I'll remind you: {reminder_line(r)}.", channel="family")
    return f"Reminder set: {reminder_line(r)}"


def _cmd_reminders(arg):
    rs = reminders()
    store().add_chat("remi", "Your reminders:\n" + "\n".join(f"- {reminder_line(r)}" for r in rs)
                     if rs else "No reminders set. Try /remind 8am every day take my meds.", channel="family")
    return f"{len(rs)} reminder{'s' if len(rs) != 1 else ''}."


def _cmd_forget(arg):
    r = delete_reminder(int(arg.strip().lstrip("#"))) if arg.strip().lstrip("#").isdigit() else None
    if not r:
        raise CommandError("Which one? /reminders shows the numbers, e.g. /forget 3")
    post_event("remi", f"You removed the reminder: {r['what']}")
    return f"Removed: {r['what']}"


def _cmd_spend(arg):
    parsed = parse_expense(arg if "$" in arg else "$" + arg.strip())
    if not parsed:
        raise CommandError("Usage: /spend $42 groceries at Costco")
    store().add_chat("glass", glass_log_reply(parsed))
    return "Glass logged it."


def _cmd_budget(arg):
    lines = status_lines()
    store().add_chat("glass", f"Budget for {datetime.now(hub_tz()):%B}:\n" + (
        "\n".join(f"- {x}" for x in lines) if lines else "- Nothing logged and no budgets set."))
    return "Glass posted the budget."


def _cmd_chart(arg):
    name = arg.strip().lower() if arg.strip().lower() in CHARTS else pick_chart(arg)
    if not name:
        raise CommandError("Usage: /chart " + next(c["args"] for c in COMMANDS if c["name"] == "chart"))
    caption, svg = CHARTS[name][1]()
    store().add_chat("charter", caption, image=save_chart(svg))
    return "Charter posted the chart."


def _cmd_news(arg):
    r = run_round(force=True, only=_NEWS_AGENTS)
    return "Red, Blue and Gray: " + "; ".join(f"{AGENTS[a]['name']} {v['did']}" for a, v in r["ran"].items())


def _cmd_trending(arg):
    r = run_round(force=True, only={"lenz"})
    return f"Lenz {r['ran']['lenz']['did']}."


def _cmd_summary(arg):
    unprocessed = store().unprocessed_reports(50)
    if not unprocessed:
        return "No new reports to summarize."
    r = summarize(unprocessed)
    if not r["ok"]:
        raise CommandError(r["error"])
    return f"Theta summarized {r['unprocessed_count']} report(s)."


def _cmd_status(arg):
    rows = [r for r in wiring() if r["state"] != "ok"]
    store().add_chat("mistral", "Everyone is wired." if not rows else "Status:\n" + "\n".join(
        f"- {r['name']}: {'not set up' if r['state'] == 'off' else 'not wired'} ({r['note']})" for r in rows))
    return "Mistral posted the status."


def _cmd_checkup(arg):
    checks = doctor_checks()
    problems = [c for c in checks if c["state"] != "ok"]
    store().add_chat("qwerty", "Checkup: " + doctor_line(checks) + "".join(
        f"\n- {'✗' if c['state'] == 'bad' else '!'} **{c['name']}**: {c['detail']}" for c in problems)
        + ("\n\nDetails and fixes: Diagnostics → Checkup." if problems else ""), channel="dev")
    return "QWERTY posted the checkup in #dev-and-security."


def _cmd_help(arg):
    store().add_chat("hub", "Commands:\n" + "\n".join(
        f"/{c['name']}{' ' + c['args'] if c['args'] else ''}: {c['about']}" for c in COMMANDS))
    return "Posted the command list."
