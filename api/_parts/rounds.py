"""Rounds: each agent's scheduled job.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Rounds: each agent's own job, run on a schedule (Supabase Cron ->
# /api/round). Jobs post real results to All Agents; agents without a data
# source yet say so instead of inventing work.
def _seen(key):
    return json.loads(store().get_meta(key) or "[]")


def _mark_seen(key, url):
    store().set_meta(key, json.dumps(([url] + [u for u in _seen(key) if u != url])[:50]))


def _theta_decisions(did):
    """Decide escalations that reached the High Brain; an ORDER: reply also
    issues a commandeer order."""
    st = store()
    done = set(json.loads(st.get_meta("theta:decided") or "[]"))
    for e in [e for e in st.list_escalations(50, open_only=True)
              if e["to_role"] == "master" and e["id"] not in done][:3]:
        reply = llm_chat("master", [
            {"role": "system", "content": system_prompt("theta")},
            {"role": "user", "content": f"Escalation #{e['id']} from {display_name(e['from_bot'])}: "
             f"{e['issue']}\nContext: {json.dumps(e.get('context') or {})[:600]}\nDecide in 2-3 "
             "sentences. If the crew must act on it, start your reply with ORDER: and the order."}]).strip()
        if reply.upper().startswith("ORDER:"):
            order = reply[6:].strip()
            oid = st.add_order(order[:500], "theta", expires_at=time.time() + ORDER_DAYS * 86400)
            post_event("theta", f"Theta issued order #{oid}: {order[:200]}")
            st.add_chat("theta", f"On #{e['id']}: {order}")
            did.append(f"ordered on #{e['id']}")
        else:
            st.add_chat("theta", f"On #{e['id']}: {reply}")
            did.append(f"decided #{e['id']}")
        notify("Mistral", f"Theta decided #{e['id']}: {reply[:140]}")
        done.add(e["id"])
    st.set_meta("theta:decided", json.dumps(sorted(done)[-500:]))


def week_facts(today):
    """The week's real numbers for Theta's review."""
    st = store()
    since = datetime.combine(today - timedelta(days=6), datetime.min.time())
    recent = [m for m in st.list_chat(ALLCHAT_KEEP)
              if datetime.strptime(m["at"], "%Y-%m-%d %H:%M:%S") >= since]
    talk = {}
    for m in recent:
        if m.get("kind") != "event" and m["from"] in AGENTS:
            talk[AGENTS[m["from"]]["name"]] = talk.get(AGENTS[m["from"]]["name"], 0) + 1
    escs = st.list_escalations(50)
    facts = [f"All Agents posts this week: {sum(talk.values())} "
             f"({', '.join(f'{k} {v}' for k, v in sorted(talk.items(), key=lambda x: -x[1])) or 'none'})",
             f"Open escalations: {sum(1 for e in escs if e['status'] != 'resolved')}"]
    week_spend = sum(e["amount"] for mth in {today.strftime("%Y-%m"), (today - timedelta(days=6)).strftime("%Y-%m")}
                     for e in st.list_expenses(mth) if e["date"] >= (today - timedelta(days=6)).isoformat())
    if GLASS_BUDGETS or week_spend:
        over = [c for c, v in month_status().items() if v["budget"] and v["spent"] > v["budget"]]
        facts.append(f"Spending this week: ${week_spend:,.2f}; over budget this month: {', '.join(over) or 'none'}")
    if calendar_linked():
        nxt = [o for o in calendar_events(today + timedelta(days=1), today + timedelta(days=7)) if not o["birthday"]]
        bdays = [o["title"] for o in calendar_events(today + timedelta(days=1), today + timedelta(days=7)) if o["birthday"]]
        facts.append(f"Next 7 days: {len(nxt)} calendar events" + (f"; birthdays: {', '.join(bdays)}" if bdays else ""))
    last = st.get_meta("round:news:last")
    if last:
        facts.append(f"Latest story the news miners covered: {json.loads(last)['title']}")
    return facts


def _round_theta(ctx):
    """Summarize new reports, decide escalations that reached him, and post a
    weekly review on Sundays."""
    st = store()
    did = []
    unprocessed = st.unprocessed_reports(50)
    if unprocessed:
        r = summarize(unprocessed)
        if not r["ok"]:
            raise LLMError(r["error"])
        n = r["unprocessed_count"]
        did.append(f"summarized {n} report{'s' if n != 1 else ''}")
        save_card("theta", f"Summarized {n} new report{'s' if n != 1 else ''}", r["summary"])
    _theta_decisions(did)
    today = datetime.now(hub_tz()).date()
    if today.weekday() == 6 and st.get_meta("round:theta:week") != today.isoformat():
        facts = week_facts(today)
        review = llm_chat("master", [
            {"role": "system", "content": system_prompt("theta")},
            {"role": "user", "content": "Write this week's review for the crew in 4-6 sentences, then "
             "'Priorities for next week:' with 2-3 bullets. Use only these facts; don't invent "
             "numbers or events:\n" + "\n".join(f"- {f}" for f in facts)}], max_tokens=900)
        st.add_chat("theta", f"Weekly review ({today:%b %d}):\n{review.strip()}")
        save_card("theta", f"Weekly review, {today:%b} {today.day}", review.strip())
        st.set_meta("round:theta:week", today.isoformat())
        notify("Mistral", "Theta's weekly review is in.")
        did.append("posted the weekly review")
    if projects():
        did += rerun_projects(time.time() + 45)
    return ", ".join(did) or "nothing new to summarize"


def send_digest(opener=True, now=None):
    """Post and push today's digest once (the tick at DIGEST_TIME, or the
    first round after it). opener: a one-line model greeting on top."""
    st = store()
    today = (now or datetime.now(hub_tz())).date().isoformat()
    with _DIGEST_LOCK:
        if st.get_meta("round:mistral:digest_day") == today:
            return False
        st.set_meta("round:mistral:digest_day", today)  # claimed first: a slow model can't double-send
    post, brief = morning_digest(now.date() if now else None)
    if head_on():  # Stage 8.5: Theta's own short morning brief, made to be heard
        return send_head_brief(post, brief)
    if opener:
        try:
            # Migration #3: selection comes from route(), executed by
            # llm_chat. agent/entry_point are None: a bare tier call
            # that must never take the desk path (the legacy call is
            # llm_chat, not desk_chat). desk_up/master_up use the pure
            # _master_under_cap() predicate: the legacy digest never
            # made readiness calls, so no notify/meta side effects.
            # fallback_off translates the legacy FALLBACK_LLM "off"
            # with zero production env change. route()'s diag
            # (via="route") is kept alongside llm_chat's _note line,
            # deliberately. Option A: route() sits inside the try and
            # the except also catches RouteConfigError, so a routing
            # or config failure drops only the optional opener — never
            # the digest itself.
            decision = route("low_brain", agent=None, entry_point=None,
                             desk_up=DESK_MODEL.lower() != "off" and _master_under_cap(),
                             master_up=_master_under_cap(),
                             fallback_off=("low_brain",) if FALLBACK_LLM.get("low_brain", (None, "off"))[1] == "off" else ())
            digest_prim = (decision["primary"]["provider"], decision["primary"]["model"])
            digest_fb = decision["fallbacks"][0] if decision["fallbacks"] else "off"
            digest_fb = (digest_fb["provider"], digest_fb["model"]) if digest_fb != "off" else "off"
            line = llm_chat("low_brain", [
                {"role": "system", "content": system_prompt("mistral")},
                {"role": "user", "content": "Write one short sentence to open today's digest. "
                 "Don't mention any events, numbers or headlines."}], max_tokens=300,
                primary=digest_prim, fallback=digest_fb)
            post = f"{line.strip()}\n{post}"
        except (LLMError, RouteConfigError):
            pass
    item = st.add_chat("mistral", post)
    try:
        lead = next(iter(news_items()[1]), None)
    except Exception:
        lead = None
    save_card("mistral", "Morning digest", post, (lead or {}).get("image"))
    st.set_meta("round:mistral:digest_id", str(item["id"]))
    notify("Mistral", brief)
    return True


_DIGEST_LOCK = threading.Lock()


def _round_mistral(ctx):
    """Morning digest (once a day), breaking-news alerts and escalation
    triage. (QWERTY does the wiring check.)"""
    st = store()
    did = []
    if digest_due() and send_digest():
        did.append("posted the morning digest")
    try:
        breaking = news_items()[0]
    except Exception:
        breaking = []
    pushed = _seen("push:breaking")
    for b in [b for b in breaking if b["url"] not in pushed][:2]:
        st.add_chat("mistral", f"Breaking ({b['source']}): {b['title']}\n{b['url']}")
        save_card("mistral", b["title"], f"Breaking, from {b['source']}", b.get("image"), b["url"], b["source"])
        notify("Mistral", f"Breaking ({b['source']}): {b['title']}", b["url"])
        _mark_seen("push:breaking", b["url"])
        did.append("flagged breaking news")
    _triage_escalations(did)
    return ", ".join(did) or "nothing new"


def _round_news(agent):
    """Red, Blue and Gray take the same top story, each grounded in how their
    own outlets covered it (or noting that they haven't)."""
    def job(ctx):
        story = ctx.get("story")
        if not story:
            return "no new headlines"
        seen = side_coverage(agent, story["title"])
        if seen:
            coverage = "How your outlets covered it:\n" + "\n".join(
                f"- {it['source']}: {it['title']}" for it in seen)
        else:
            coverage = "None of your outlets have covered it yet; say so, that's worth knowing."
        brief = ctx.get("brief")
        grounded = (f"A neutral brief of the article ({brief['credit']}):\n{brief['summary']}\n"
                    f"Its framing: {brief['bias']}\n" if brief and brief.get("summary") else
                    "You only have the headline; say so instead of guessing details.\n")
        take = llm_chat(AGENTS[agent]["tier"], [
            {"role": "system", "content": system_prompt(agent) + " You're posting in the All "
             "Agents group chat."},
            {"role": "user", "content": f"Today's top story ({story['source']}): {story['title']}\n"
             f"{grounded}{coverage}\nGive your take in 2-3 sentences, from the brief and your outlets' "
             "coverage only. Don't put anything in quotation marks."}])
        links = [story["url"]] + [it["url"] for it in seen if it["url"] != story["url"]][:1]
        # Gray, the independent, posts the brief itself; Red and Blue argue from it.
        has_brief = bool(brief and brief.get("summary"))
        lead = f"Brief: {brief_text(brief)}\n\n" if has_brief and agent == "gray" else ""
        store().add_chat(agent, lead + take.strip() + "\n" + "\n".join(links))
        pic = story.get("image") or next((it.get("image") for it in seen if it.get("image")), None)
        save_card(agent, story["title"], take.strip() + (f"\n\n{brief_text(brief)}" if has_brief else ""),
                  pic, story["url"], story["source"])
        return (f"posted a take on \"{story['title'][:60]}\""
                + (f" ({len(seen)} of their outlets covered it)" if seen else " (their outlets haven't covered it)"))
    return job


def _round_lenz(ctx):
    """Keep your library current (doc and MyAnimeList syncs once a day,
    posters and genres), post news about what you follow, Sunday's taste
    report, then pitch one new trending title."""
    st = store()
    did = []
    today = datetime.now(hub_tz()).date()
    if st.get_meta("round:lenz:sync_day") != today.isoformat():
        for label, fn in (("your doc", sync_library_doc), ("MyAnimeList", sync_mal)):
            try:
                r = fn()
                if r:
                    did.append(f"synced {label} ({r['added']} new)")
            except LLMError as e:
                did.append(f"couldn't sync {label}: {str(e)[:80]}")
        st.set_meta("round:lenz:sync_day", today.isoformat())
    if st.get_meta("round:lenz:releases") != today.isoformat():
        by, errs = refresh_releases(today)
        st.set_meta("round:lenz:releases", today.isoformat())
        did.append(f"release calendar: {sum(len(v) for v in by.values())} upcoming"
                   + (f" ({', '.join(errs)} failed)" if errs else ""))
    if release_day_news(today):
        did.append("posted today's releases")
    try:
        r = subreddit_digest(today)
        if r:
            did.append(r)
    except Exception as e:
        did.append(f"subreddit digest failed ({str(e)[:60]})")
    try:
        n = enrich_library(deadline=time.time() + 12)
        if n:
            did.append(f"found posters for {n}")
    except Exception as e:  # cosmetic: never sink the round
        did.append(f"poster lookup failed ({str(e)[:60]})")
    seen = _seen("round:lenz:news")
    fresh = [n for n in followed_news() if n["url"] not in seen][:3]
    if fresh:
        def brief_for(n):
            try:
                return brief_text(story_brief(n["title"], n["url"], n["source"], n.get("summary", "")))
            except LLMError:
                return n["source"]
        with ThreadPoolExecutor(max_workers=len(fresh)) as ex:
            briefs = list(ex.map(brief_for, fresh))
        st.add_chat("lenz", "News on what you follow:\n\n" + "\n\n".join(
            f"{n['about']}: {n['title']}\n{b}\n{n['url']}" for n, b in zip(fresh, briefs)), channel="screen")
        for n in fresh:
            _mark_seen("round:lenz:news", n["url"])
            if n["waiting"]:
                notify("Lenz", f"{n['about']}: {n['title']}", n["url"])
        did.append(f"posted {len(fresh)} news item{'s' if len(fresh) != 1 else ''} on what you follow")
    if today.weekday() == 6 and st.get_meta("round:lenz:week") != today.isoformat() and library():
        st.add_chat("lenz", lenz_week_report(today), channel="screen")
        st.set_meta("round:lenz:week", today.isoformat())
        did.append("posted your weekly taste report")
    try:
        did.append(_lenz_pitch())
    except LLMError as e:
        if not did:
            raise
        did.append(f"no pitch ({str(e)[:60]})")
    return ", ".join(did)


def _lenz_pitch():
    """Pitch one new trending title (TMDB facts when linked, else the feeds)."""
    trending = tmdb_trending()
    item = next((i for i in trending if i["url"] not in _seen("round:lenz:seen")), None)
    if item:
        facts = (f"Trending this week on TMDB: {tmdb_fact_line(item)}\n"
                 f"Synopsis: {item['overview'] or 'none given'}\n"
                 "In 1-2 sentences, say why it might be worth a watch. Use only these facts.")
    else:
        item = next((i for i in widget_items(ENTERTAINMENT_FEEDS)
                     if i["url"] not in _seen("round:lenz:seen")), None)
        if not item:
            return "nothing new to pitch"
        facts = (f"New in the feeds ({item['source']}): {item['title']}\n"
                 "In 1-2 sentences, say why it might be worth a look. You only have the title: "
                 "don't invent details.")
    # Migration #5: primary/fallback selection comes from route(),
    # executed by llm_chat. agent/entry_point are None: a bare tier
    # call that must never take the desk path. desk_up/master_up use
    # the pure _master_under_cap() predicate: the legacy call never
    # made readiness calls, so no notify/meta side effects.
    # fallback_off translates the legacy FALLBACK_LLM "off" with zero
    # production env change. route()'s diag (via="route") is kept
    # alongside llm_chat's _note line, deliberately. The borrow chain
    # is NOT migrated: borrow_help still reads the legacy tier,
    # fallback and desk settings; under defaults it is identical.
    # Miner subtlety (as in #4): route()'s decision["fallbacks"] is
    # the whole downstream chain, deduped — so fallbacks[0] is the
    # tier fallback ONLY when one exists. A suppressed tier fallback
    # maps to fallback="off", and borrow runs untouched. An anthropic
    # fallbacks[0] (the desk pair, reachable only when dedup ate the
    # tier-fallback step) is likewise not a valid llm_chat fallback
    # leg (PROVIDERS has no anthropic entry — it would raise KeyError,
    # not LLMError), so it also maps to "off" and borrow tries the
    # desk model properly via claude_chat (see #85 review fix).
    # Caller note: _round_lenz catches LLMError only, so a
    # RouteConfigError escapes to run_round, which catches ValueError
    # (RouteConfigError's parent) and records a lenz job failure —
    # loud, not hidden behind a "no pitch" note. That is deliberate:
    # a malformed ROUTE_* config is an operator error.
    miner_off = (FALLBACK_LLM.get("miner", (None, "off"))[1] == "off"
                 or os.environ.get("ROUTE_MINER_FALLBACK_MODEL") == "off")
    decision = route("miner", agent=None, entry_point=None,
                     desk_up=DESK_MODEL.lower() != "off" and _master_under_cap(),
                     master_up=_master_under_cap(),
                     fallback_off=("miner",) if FALLBACK_LLM.get("miner", (None, "off"))[1] == "off" else ())
    miner_prim = (decision["primary"]["provider"], decision["primary"]["model"])
    if miner_off:
        miner_fb = "off"
    else:
        miner_fb = decision["fallbacks"][0]
        miner_fb = (miner_fb["provider"], miner_fb["model"])
        if miner_fb[0] == "anthropic":
            miner_fb = "off"
    pitch = llm_chat("miner", [
        {"role": "system", "content": system_prompt("lenz") + " You're posting in the All "
         "Agents group chat."},
        {"role": "user", "content": facts}], primary=miner_prim, fallback=miner_fb)
    store().add_chat("lenz", f"{pitch.strip()}\n{item['url']}")
    save_card("lenz", item["title"], pitch.strip(), item.get("image"), item["url"])
    _mark_seen("round:lenz:seen", item["url"])
    return f"pitched \"{item['title'][:60]}\""


def _round_james(ctx):
    if not GARAGE_GYM_SECRET:
        return "not linked to Garage Gym"
    _JAMES_CACHE.update(ttl=0)  # a round always asks for fresh numbers
    summary = james_summary()
    if not summary:
        raise LLMError("Garage Gym didn't answer")
    digest = hashlib.sha256((summary.get("summary") or "").encode()).hexdigest()
    if digest == store().get_meta("round:james:summary"):
        return "training unchanged"
    store().set_meta("round:james:summary", digest)
    post_event("james", "James checked your training: new numbers on the Fitness card.")
    return "updated your training summary"


def _round_remi(ctx):
    """Calendar (agenda, changes, birthdays), then Gmail when connected."""
    did, err = [], None
    try:
        did.append(_round_remi_calendar(ctx))
    except LLMError as e:
        err = str(e)
    if gmail_connected():
        try:
            did.append("mail: " + gmail_sync(deadline=time.time() + 40))
        except LLMError as e:
            err = f"{err}; {e}" if err else f"mail: {e}"
    if err and not did:
        raise LLMError(err)
    return "; ".join(did + ([f"failed: {err}"] if err else []))


def _round_remi_calendar(ctx):
    """Today's agenda once a day, an update when today's plans change, and
    birthdays 7 days, 1 day and 0 days ahead."""
    if not calendar_linked():
        return "no calendar linked"
    if REMI_CALENDAR_URLS and len(calendar_problems()) == len(REMI_CALENDAR_URLS) and not BIRTHDAYS:
        raise LLMError("couldn't read any calendar link")
    today = datetime.now(hub_tz()).date()
    todays = [o for o in calendar_events(today, today) if not o["birthday"]]
    agenda = "\n".join(f"- {occurrence_text(o)}" for o in todays) or "- Nothing on the calendar."
    digest = hashlib.sha256(agenda.encode()).hexdigest()
    st = store()
    if st.get_meta("round:remi:day") != today.isoformat():
        lines = [f"Today, {today:%A %B %d}:", agenda]
        for o in calendar_events(today, today + timedelta(days=7)):
            if not o["birthday"]:
                continue
            days = ((o["start"] if o["all_day"] else o["start"].date()) - today).days
            if days == 0:
                lines.append(f"Today: {o['title']}!")
                notify("Mistral", f"Remi: today is {o['title']}!", "/calendar")
            elif days in (1, 7):
                lines.append(f"Coming up: {o['title']} {'tomorrow' if days == 1 else 'in a week'}.")
                if days == 1:
                    notify("Mistral", f"Remi: {o['title']} is tomorrow.", "/calendar")
        try:
            opener = llm_chat("manager", [
                {"role": "system", "content": system_prompt("remi")},
                {"role": "user", "content": "Write one warm sentence to open today's family "
                 "agenda post. Don't list or mention any events or times."}], max_tokens=300)
            lines.insert(0, opener.strip())
        except LLMError:
            pass  # the agenda matters more than the greeting
        st.add_chat("remi", "\n".join(lines))
        st.set_meta("round:remi:day", today.isoformat())
        st.set_meta("round:remi:digest", digest)
        return "posted today's agenda"
    if digest != st.get_meta("round:remi:digest"):
        st.add_chat("remi", f"Today's plans changed:\n{agenda}")
        st.set_meta("round:remi:digest", digest)
        return "posted an agenda update"
    return "agenda unchanged"
