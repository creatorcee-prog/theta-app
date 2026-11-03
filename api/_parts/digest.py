"""The daily digest and escalation triage.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Mistral's daily digest and escalation triage
def morning_digest(today=None):
    """(post, phone one-liner) for today, from real data only."""
    today = today or datetime.now(hub_tz()).date()
    lines, brief = [f"Here's today, {today:%A %B %d}:"], []
    if calendar_linked():
        events = calendar_events(today, today)
        todays = [o for o in events if not o["birthday"]]
        lines.append("Calendar: " + ("; ".join(occurrence_text(o) for o in todays) or "nothing scheduled"))
        if todays:
            brief.append(f"{len(todays)} event{'s' if len(todays) != 1 else ''}")
        soon = [o for o in calendar_events(today, today + timedelta(days=1)) if o["birthday"]]
        for o in soon:
            lines.append(f"Birthday: {o['title']} {'today' if (o['start'] == today) else 'tomorrow'}.")
            brief.append(o["title"])
    end = datetime.combine(today + timedelta(days=1), datetime.min.time(), hub_tz()).timestamp()
    due = [r for r in reminders() if r["at"] < end or r.get("pending")]
    if due:
        lines.append("Reminders: " + "; ".join(
            (f"{r['what']} (still to do)" if r.get("pending") else
             f"{_clock(datetime.fromtimestamp(r['at'], hub_tz()))} {r['what']}") for r in due))
        brief.append(f"{len(due)} reminder{'s' if len(due) != 1 else ''}")
    try:
        breaking, top = news_items()
        heads = (breaking + top)[:3]
    except Exception:
        heads = []
    if heads:
        lines.append("Headlines:\n" + "\n".join(f"- {i['title']} ({i['source']})" for i in heads))
        brief.append(f"{len(heads)} headlines")
    if GLASS_BUDGETS:
        status = month_status()
        over = [f"{c} (${v['spent']:,.0f} of ${v['budget']:,.0f})" for c, v in status.items()
                if v["budget"] and v["spent"] > v["budget"]]
        near = [c for c, v in status.items() if v["budget"] and 0.9 <= v["spent"] / v["budget"] <= 1]
        if over or near:
            lines.append("Budget: " + "; ".join([f"over in {x}" for x in over] + [f"{c} near its limit" for c in near]))
            brief += [f"{c.split(' (')[0]} over budget" for c in over]
        else:
            lines.append("Budget: all categories on track.")
    lines += weather_facts(today)
    for line in sleep_facts(today):  # Theta's ideas from last night
        lines.append(line)
        brief.append("an idea from last night")
    since = store().get_meta("round:mistral:digest_id")
    recent = [m for m in store().list_chat(ALLCHAT_KEEP) if since and m["id"] > int(since)]
    if recent:
        lines.append(f"Since yesterday's digest: {len(recent)} posts in All Agents.")
    return "\n".join(lines), " · ".join(brief) or "Nothing pressing today"


def _triage_escalations(did):
    """Mistral answers what the Low Brain can; forwards the rest to Theta."""
    st = store()
    done = set(json.loads(st.get_meta("mistral:triaged") or "[]"))
    todo = [e for e in st.list_escalations(50, open_only=True)
            if e["to_role"] == "low_brain" and e["id"] not in done][:3]
    # Migration #1: selection comes from route(), executed by llm_chat.
    # One decision per run (legacy tier values are import-time frozen,
    # so a run never re-resolves mid-loop; a config error fails the
    # run before any escalation is touched, never half a run).
    # agent/entry_point are None: this is a bare tier call and must
    # never take the desk path (the legacy call is llm_chat, not
    # desk_chat; the Mistral system prompt here is a persona, not
    # desk routing). desk_up/master_up are the live readiness states
    # (required keywords; the low_brain branch does not use them, but
    # they are passed explicitly, never assumed). They are computed
    # with the pure _master_under_cap() predicate, NOT desk_on() /
    # master_ready(): those notify once a month when the cap is hit,
    # and legacy triage never triggered that side effect. route()
    # itself is untouched by this correction. fallback_off
    # translates the legacy FALLBACK_LLM "off" with zero production
    # env change. route()'s diag (via="route") is kept alongside
    # llm_chat's _note line, deliberately.
    decision = route("low_brain", agent=None, entry_point=None,
                     desk_up=DESK_MODEL.lower() != "off" and _master_under_cap(),
                     master_up=_master_under_cap(),
                     fallback_off=("low_brain",) if FALLBACK_LLM.get("low_brain", (None, "off"))[1] == "off" else ())
    triage_prim = (decision["primary"]["provider"], decision["primary"]["model"])
    triage_fb = decision["fallbacks"][0] if decision["fallbacks"] else "off"
    triage_fb = (triage_fb["provider"], triage_fb["model"]) if triage_fb != "off" else "off"
    for e in todo:
        reply = llm_chat("low_brain", [
            {"role": "system", "content": system_prompt("mistral")},
            {"role": "user", "content": f"Escalation #{e['id']} from {display_name(e['from_bot'])}: "
             f"{e['issue']}\nContext: {json.dumps(e.get('context') or {})[:600]}\nHandle it in 2-3 "
             "sentences. If it truly needs Theta's decision, start your reply with THETA:"}],
            primary=triage_prim, fallback=triage_fb)
        if reply.strip().upper().startswith("THETA:"):
            note = reply.strip()[6:].strip()
            new_id = st.add_escalation("mistral", "low_brain", "master", f"#{e['id']}: {e['issue']}",
                                       {"from_escalation": e["id"], "mistral": note}, "awaiting_master")
            st.add_chat("mistral", f"#{e['id']} needs Theta, so I passed it up as #{new_id}. {note}")
            notify("Mistral", f"Escalated to Theta: {e['issue'][:120]}")
            did.append(f"forwarded #{e['id']} to Theta")
        else:
            st.add_chat("mistral", f"On #{e['id']} from {display_name(e['from_bot'])}: {reply.strip()}")
            did.append(f"handled #{e['id']}")
        done.add(e["id"])
    st.set_meta("mistral:triaged", json.dumps(sorted(done)[-500:]))
