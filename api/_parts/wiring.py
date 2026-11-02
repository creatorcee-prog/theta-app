"""Wiring: is each model and service connected (Diagnostics).

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Wiring: is each agent's model actually reachable?
def recent_fallback(tier, within=86400):
    """The last time this tier's fallback model answered, if within a day."""
    try:
        fb = json.loads(store().get_meta("llm:fallback") or "null")
    except ValueError:
        return None
    if not fb or fb["tier"] != ("low_brain" if tier == "master" else tier) or time.time() - fb["at"] > within:
        return None
    mins = int((time.time() - fb["at"]) // 60)
    return dict(fb, ago=f"{mins // 60} h" if mins >= 60 else f"{mins} min")


ROUND_HOURS_UTC = (0, 12, 18)  # supabase/cron.sql.example's bot-hub-rounds schedule


def next_round_at(now=None):
    """The next scheduled round (from ROUND_HOURS_UTC), as a local datetime."""
    now = datetime.fromtimestamp(now or time.time(), timezone.utc)
    for days in (0, 1):
        for hr in ROUND_HOURS_UTC:
            at = (now + timedelta(days=days)).replace(hour=hr, minute=0, second=0, microsecond=0)
            if at > now:
                return at.astimezone(hub_tz())


def wiring(fresh=False):
    """Per agent: what answers for it and whether it's wired in. Checks the
    key and that the key can use the model; costs no tokens. fresh (the
    Recheck button) skips the cached model lists and saved statuses and
    checks calendars, Gmail and stock prices live (still no model tokens)."""
    if fresh:
        _MODELS_CACHE.clear()
    models = {p: list_models(p) for p in {p for p, _ in TIER_LLM.values()}}
    rows = []
    for aid, a in AGENTS.items():
        row = {"agent": aid, "name": a["name"], "tier": TIER_LABELS[a["tier"]],
               "model": agent_model(aid)}
        if a.get("home"):
            if not GARAGE_GYM_SECRET:
                row.update(state="off", note="Not linked: set GARAGE_GYM_SECRET")
            elif james_summary():
                row.update(state="ok", note="Garage Gym answered")
            else:
                row.update(state="bad", note="Garage Gym didn't answer: check GARAGE_GYM_URL "
                           "and that HUB_SECRET there matches GARAGE_GYM_SECRET here")
        else:
            provider, model = TIER_LLM["low_brain" if a["tier"] == "master" else a["tier"]]
            found = models[provider]
            if "error" in found:
                missing = found["error"].endswith("is not set")
                row.update(state="off" if missing else "bad", note=found["error"])
            elif model not in found["models"]:
                row.update(state="bad", note=f"{model} isn't available to this key; "
                           "pick one from /api/models")
            else:
                row.update(state="ok", note="Key set and model available"
                           + (f" ({MASTER_MODEL} not connected: set ANTHROPIC_API_KEY; standing in)"
                              if a["tier"] == "master" else ""))
            if a["tier"] == "master" and os.environ.get("ANTHROPIC_API_KEY"):
                spend, last = claude_spend(), _meta_json("claude:last_error", {})
                used = f"${spend['usd']:.2f} of ${MASTER_MONTHLY_CAP:.0f} this month ({spend['calls']} calls)"
                if spend["usd"] >= MASTER_MONTHLY_CAP:
                    row.update(state="bad", note=f"{MASTER_MODEL}: monthly cap reached, {used}; the low brain stands in "
                               "until the 1st (raise MASTER_MONTHLY_CAP_USD to lift it)")
                elif (check := claude_key_check())[0] is False:
                    when = _ago(_meta_json("claude:check", {}).get("at", time.time()))
                    row.update(state="bad", note=f"{MASTER_MODEL} isn't connected: {check[1]}. The low brain answers "
                               f"for Theta meanwhile (checked {'just now' if when == 'now' else when + ' ago'}). {used}")
                elif (last and time.time() - last["at"] < 86400 and last.get("fp") == _key_fp()
                      and last["at"] > float(store().get_meta("claude:last_ok") or 0)):
                    row.update(state="bad", note=f"{MASTER_MODEL} failed {_ago(last['at'])} ago ({last['error']}); "
                               f"the low brain answered. {used}")
                else:
                    ok_at = float(store().get_meta("claude:last_ok") or 0)
                    row.update(state="ok", note=f"{MASTER_MODEL} connected, effort {MASTER_EFFORT}"
                               + (f", last answered {'just now' if _ago(ok_at) == 'now' else _ago(ok_at) + ' ago'}"
                                  if ok_at else "") + f"; {used}")
            c = cooling(provider, model) if not (a["tier"] == "master" and master_ready()) else None
            if c:
                fb_p, fb_m = FALLBACK_LLM.get("low_brain" if a["tier"] == "master" else a["tier"], (None, "off"))
                row.update(state="bad", note=f"{model}'s free {'daily' if c['daily'] else 'per-minute'} quota is used up until "
                           f"{_clock(datetime.fromtimestamp(c['until'], hub_tz()))}"
                           + (f"; {fb_m} answers meanwhile" if fb_m != "off" else ""))
            fb = recent_fallback(a["tier"])
            if fb and row["state"] == "ok":
                row["note"] += (f". Busy {fb['ago']} ago, so {fb['model']} answered instead "
                                f"({fb['why']})")
        rows.append(row)
    if TMDB_API_KEY:
        try:
            n = len(tmdb_trending())
            rows.append({"agent": "lenz-tmdb", "name": "Lenz's TMDB", "tier": "", "model": "TMDB trending",
                         "testable": False, "state": "ok", "note": f"{n} trending titles"})
        except LLMError as e:
            rows.append({"agent": "lenz-tmdb", "name": "Lenz's TMDB", "tier": "", "model": "TMDB trending",
                         "testable": False, "state": "bad", "note": f"{e}: check TMDB_API_KEY"})
    else:
        rows.append({"agent": "lenz-tmdb", "name": "Lenz's TMDB", "tier": "", "model": "TMDB trending",
                     "testable": False, "state": "off", "note": "Not linked: set TMDB_API_KEY"})
    if os.environ.get("DEEPSEEK_API_KEY"):  # Stage 8.1: the head's model, checked without spending tokens
        found = list_models("deepseek")
        users = [r for r in ROUTE_CONFIG_VARS if os.environ.get(ROUTE_CONFIG_VARS[r][0], "").strip() == "deepseek"]
        if "error" in found:
            ds_row = {"state": "bad", "note": found["error"] + (": check DEEPSEEK_API_KEY" if " 401" in found["error"]
                                                                 or "returned 401" in found["error"] else "")}
        elif DEEPSEEK_MODEL in found["models"]:
            ds_row = {"state": "ok", "note": f"Key works, {DEEPSEEK_MODEL} available"
                      + (f"; answers for: {', '.join(users)}" if users else "; not answering for anyone yet")}
        else:
            ds_row = {"state": "bad", "note": f"Key works, but {DEEPSEEK_MODEL} isn't offered "
                      f"(it has: {', '.join(found['models'][:5]) or 'nothing'}); set DEEPSEEK_MODEL"}
        rows.append({"agent": "deepseek", "name": "DeepSeek", "tier": "", "model": DEEPSEEK_MODEL, "testable": False,
                     **ds_row})
    else:
        rows.append({"agent": "deepseek", "name": "DeepSeek", "tier": "", "model": DEEPSEEK_MODEL, "testable": False,
                     "state": "off", "note": "Not linked: set DEEPSEEK_API_KEY"})
    if vault_on():
        try:
            text, sha = vault_read("Memory.md", fresh=fresh)
            with ThreadPoolExecutor(max_workers=len(AGENTS)) as ex:  # cached; a cold read is one call each, at once
                agents_n = sum(1 for t, _ in ex.map(lambda a: vault_read(f"Agents/{AGENTS[a]['name']}.md"), AGENTS) if t.strip())
            vault_row = {"state": "ok", "note": (f"Memory.md: {len(text)} characters" if sha else
                                                 f"Readable, but there's no {VAULT_DIR}/Memory.md yet")
                         + f"; {agents_n} agent note(s)" + ("; checked just now" if fresh else "")}
        except LLMError as e:
            vault_row = {"state": "bad", "note": str(e)}
        rows.append({"agent": "vault", "name": "Obsidian vault", "tier": "", "model": OBSIDIAN_REPO, "testable": False,
                     **vault_row})
    else:
        rows.append({"agent": "vault", "name": "Obsidian vault", "tier": "", "model": "GitHub repo", "testable": False,
                     "state": "off", "note": "Not linked: set OBSIDIAN_REPO and OBSIDIAN_TOKEN"})
    if LOCAL_LLM_URL or os.environ.get("LOCAL_LLM_KEY"):
        up, why = local_status(fresh=fresh)
        users = [r for r in ROUTE_CONFIG_VARS if os.environ.get(ROUTE_CONFIG_VARS[r][0], "").strip() == "local"]
        rows.append({"agent": "local", "name": "Your PC", "tier": "", "model": LOCAL_LLM_MODEL or "(LOCAL_LLM_MODEL not set)",
                     "testable": False, "state": "ok" if up else "bad",
                     "note": why + (f"; answers for: {', '.join(users)}" if users else
                                    "; not answering for anyone yet (set ROUTE_<ROLE>_PROVIDER=local)")
                     + ("" if up or not users else "; Groq and Gemini stand in meanwhile")})
    else:
        rows.append({"agent": "local", "name": "Your PC", "tier": "", "model": "LM Studio / Ollama", "testable": False,
                     "state": "off", "note": "Not linked: set LOCAL_LLM_URL, LOCAL_LLM_KEY and LOCAL_LLM_MODEL"})
    subs = len(push_subs())
    problem = push_problem()
    if problem:
        push_row = {"state": "off" if problem[0] == "no_keys" else "bad", "note": problem[1]}
    elif not subs:
        push_row = {"state": "off", "note": "No device yet: tap Turn on in the Home Screen app"}
    elif store().get_meta("push:last_error"):
        push_row = {"state": "bad", "note": store().get_meta("push:last_error")}
    else:
        push_row = {"state": "ok", "note": f"{subs} device(s) subscribed"}
    rows.append({"agent": "push", "name": "Phone notifications", "tier": "", "model": "Web Push (Mistral)",
                 "testable": False, **push_row})
    if calendar_linked():
        bad = ([i + 1 for i, u in enumerate(REMI_CALENDAR_URLS) if _calendar_text(u) is None]  # live, one fetch each
               if fresh else calendar_problems())
        rows.append({"agent": "remi-calendar", "name": "Remi's calendar", "tier": "",
                     "model": f"{len(REMI_CALENDAR_URLS)} calendar link(s), {len(BIRTHDAYS)} birthdays",
                     "testable": False,
                     **({"state": "bad", "note": f"Couldn't read link(s) {', '.join(map(str, bad))}: "
                                                  "check REMI_CALENDAR_URLS"} if bad else
                        {"state": "ok", "note": "Calendar readable" + (" (checked just now)" if fresh else "")})})
    else:
        rows.append({"agent": "remi-calendar", "name": "Remi's calendar", "tier": "",
                     "model": "Google Calendar (iCal)", "testable": False, "state": "off",
                     "note": "Not linked: set REMI_CALENDAR_URLS"})
    now = time.time()
    ago = lambda t: "just now" if _ago(t) == "now" else f"{_ago(t)} ago"
    last_round = max(json.loads(store().get_meta("round:last") or "{}").values(), default=0)
    last_tick = float(store().get_meta("tick:last") or 0)
    cron_alive = last_tick and now - last_tick < 20 * 60
    nxt = next_round_at(now)
    rows.append({"agent": "rounds", "name": "Rounds", "tier": "", "model": "Supabase Cron → /api/round", "testable": False,
                 **({"state": "ok", "note": f"Scheduled: Supabase Cron is running (the tick checked in {ago(last_tick)}), "
                     f"so the first round should come at {_clock(nxt)} {nxt.tzname()}"}
                    if not last_round and cron_alive else
                    {"state": "off", "note": "No round has run yet: run the bot-hub-rounds job in supabase/cron.sql.example"}
                    if not last_round else
                    {"state": "ok", "note": f"Last round {ago(last_round)}"} if now - last_round < 13 * 3600 else
                    {"state": "bad", "note": f"Last round {ago(last_round)}: check the bot-hub-rounds job in Supabase"})})
    rows.append({"agent": "tick", "name": "Reminders and digest", "tier": "", "model": "Supabase Cron → /api/tick",
                 "testable": False,
                 **({"state": "off", "note": "Not running yet: run the bot-hub-tick job in supabase/cron.sql.example"}
                    if not last_tick else
                    {"state": "ok", "note": f"Last check {ago(last_tick)}"} if now - last_tick < 20 * 60 else
                    {"state": "bad", "note": f"Last check {ago(last_tick)}: check the bot-hub-tick job in Supabase"})})
    rows.append({"agent": "search", "name": "Web search (projects)", "tier": "", "model": f"Gemini + Google Search",
                 "testable": False, **({"state": "ok", "note": f"{searches_used()} of {SEARCH_MONTHLY_CAP} searches this month"
                                        + ("" if HOME_LOCATION else "; set HOME_LOCATION so \"here\" works")}
                                       if os.environ.get("GEMINI_API_KEY") else
                                       {"state": "off", "note": "Needs GEMINI_API_KEY"})})
    srcs = [f"{len(LENZ_YOUTUBE)} YouTube" if LENZ_YOUTUBE else "", f"{len(LENZ_SUBREDDITS)} subreddits" if LENZ_SUBREDDITS else "",
            (f"{len(LENZ_TWITCH)} Twitch" if TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET else "Twitch needs TWITCH_CLIENT_ID/SECRET")
            if LENZ_TWITCH else ""]
    last = float(store().get_meta("lenz:feeds:at") or 0)
    rows.append({"agent": "lenz-feeds", "name": "Lenz's channels", "tier": "", "model": "YouTube, Reddit, Twitch", "testable": False,
                 **({"state": "ok", "note": ", ".join(x for x in srcs if x)
                     + (f"; checked {_ago(last)} ago" if last else "; set up, first check comes with the 5-minute tick")}
                    if lenz_feeds_on() or any(srcs) else
                    {"state": "off", "note": "Not set: LENZ_YOUTUBE, LENZ_SUBREDDITS, LENZ_TWITCH (+ TWITCH_CLIENT_ID/SECRET)"})})
    boards = [n for n, on in (("Adzuna", ADZUNA_APP_ID and ADZUNA_APP_KEY), ("USAJOBS", USAJOBS_API_KEY and USAJOBS_EMAIL)) if on]
    rows.append({"agent": "jobs", "name": "Job boards (projects)", "tier": "", "model": "Adzuna, USAJOBS", "testable": False,
                 **({"state": "ok", "note": f"{' and '.join(boards)} linked; job projects use them before web search"} if boards else
                    {"state": "off", "note": "Not linked: ADZUNA_APP_ID + ADZUNA_APP_KEY, and/or USAJOBS_API_KEY + USAJOBS_EMAIL"})})
    gmail_live = None
    if fresh and gmail_connected():
        try:
            gmail_live = {"state": "ok", "note": f"Connected as {gmail_api('GET', '/profile').get('emailAddress') or 'you'} "
                                                 "(checked just now)"}
        except LLMError as e:
            gmail_live = {"state": "bad", "note": f"Connected, but Gmail didn't answer: {str(e)[:120]}"}
    rows.append({"agent": "gmail", "name": "Remi's Gmail", "tier": "", "model": "Gmail (OAuth)", "testable": False,
                 **(gmail_live or {"state": "ok", "note": f"Connected as {store().get_meta('gmail:me') or 'you'}"} if gmail_connected() else
                    {"state": "off", "note": "Ready: Settings → Gmail → Connect"} if gmail_configured() else
                    {"state": "off", "note": "Not linked: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET"})})
    if not FINNHUB_API_KEY or not stocks_on():
        rows.append({"agent": "stocks", "name": "Glass's stocks", "tier": "", "model": "Finnhub", "testable": False,
                     "state": "off", "note": "Not linked: set FINNHUB_API_KEY" if not FINNHUB_API_KEY else
                     "Set GLASS_HOLDINGS and/or GLASS_WATCHLIST"})
    elif fresh:
        sym = stock_symbols()[0]
        try:
            q = finnhub("/quote", symbol=sym)
            live = ({"state": "ok", "note": f"Finnhub answered: {sym} at ${q['c']:,.2f} (checked just now)"} if q.get("c") else
                    {"state": "bad", "note": f"Finnhub answered but had no price for {sym}: check the symbol"})
        except LLMError as e:
            live = {"state": "bad", "note": f"Finnhub didn't answer: {str(e)[:120]}"}
        rows.append({"agent": "stocks", "name": "Glass's stocks", "tier": "", "model": "Finnhub", "testable": False, **live})
    else:
        have = stock_quotes()
        rows.append({"agent": "stocks", "name": "Glass's stocks", "tier": "", "model": "Finnhub", "testable": False,
                     **({"state": "ok", "note": f"{len(have)} prices"} if have else
                        {"state": "ok", "note": "Set up; prices arrive with Glass's next round (Recheck tests Finnhub now)"})})
    return rows
