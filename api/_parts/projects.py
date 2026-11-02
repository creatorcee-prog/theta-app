"""Projects: the crew searches the web.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Projects: "/commandeer find me a job here" puts the crew on it. Theta
# splits the goal into parts, each agent searches the web for theirs
# (Gemini with Google Search), and only leads with a source the search
# actually returned are kept, so every link is real. The project stands
# for ORDER_DAYS; each day Theta's round reruns it and posts what's new.
GEMINI_SEARCH_MODEL = os.environ.get("GEMINI_SEARCH_MODEL", "gemini-3.8-flash")
HOME_LOCATION = os.environ.get("HOME_LOCATION", "").strip()
SEARCH_MONTHLY_CAP = int(os.environ.get("SEARCH_MONTHLY_CAP", "4000"))  # Gemini's free tier: 5,000 a month
PROJECT_AGENTS = 4  # agents per project (each runs one search call)
_TASK_RE = re.compile(r"^\s*(?:@\w+[\s,]+)*(?:please\s+|can you\s+|could you\s+)?(?:find|search|look\s+(?:for|up|into)|research|"
                      r"get\s+me|show\s+me|list|compare|track\s+down|hunt|scout|dig\s+up|gather|collect|round\s+up|"
                      r"source|shop\s+for|price\s+out)\b", re.I)
_HERE_RE = re.compile(r"\b(here|near me|nearby|around me|local(?:ly)?|in my area|in town|close to home)\b", re.I)
_PROJ_LOCK = threading.Lock()


def is_task(text):
    return bool(_TASK_RE.search(text or ""))


def _search_budget(n):
    """Count searches against this month's cap; False when it's used up."""
    month = datetime.now(hub_tz()).strftime("%Y-%m")
    with _PROJ_LOCK:
        used = _meta_json("search:used", {})
        if used.get(month, 0) + n > SEARCH_MONTHLY_CAP:
            return False
        store().set_meta("search:used", json.dumps({month: used.get(month, 0) + n}))
    return True


def searches_used():
    return _meta_json("search:used", {}).get(datetime.now(hub_tz()).strftime("%Y-%m"), 0)


def gemini_search(prompt, timeout=30):
    """(text, citations, queries): Gemini answers with Google Search;
    citations are (start, end, url, title) for spans of the text."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise LLMError("Web search needs GEMINI_API_KEY.")
    c = cooling("gemini", GEMINI_SEARCH_MODEL)
    if c:
        raise LLMError(f"Gemini search is out of free quota until {_clock(datetime.fromtimestamp(c['until'], hub_tz()))}")
    body = {"model": GEMINI_SEARCH_MODEL, "tools": [{"type": "google_search"}],
            "input": [{"type": "user_input", "content": [{"type": "text", "text": prompt}]}]}
    req = urllib.request.Request(GEMINI_NATIVE + "/interactions", data=json.dumps(body).encode(), headers={
        "x-goog-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raw = e.read()[:4000].decode("utf-8", "replace")
        if e.code == 429:
            cool_down("gemini", GEMINI_SEARCH_MODEL, raw)
        raise LLMError(f"Gemini search returned {e.code}: {_llm_error_text('gemini', e.code, raw).split(': ', 1)[-1]}")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise LLMError(f"Gemini search unreachable: {e!r}")
    text, cites, queries = "", [], 0
    for step in data.get("steps", []):
        if step.get("type") == "google_search_call":
            queries += len((step.get("arguments") or {}).get("queries") or [1])
        if step.get("type") != "model_output":
            continue
        for c in step.get("content", []):
            if c.get("type") != "text":
                continue
            base = len(text)
            for a in c.get("annotations") or []:
                if a.get("type") == "url_citation" and a.get("url"):
                    cites.append((base + int(a.get("start_index") or 0), base + int(a.get("end_index") or 0),
                                  a["url"], a.get("title") or ""))
            text += c.get("text") or ""
    return text, cites, queries


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _resolve(url):
    """Google's grounding links redirect to the source; show the source."""
    if "vertexaisearch.cloud.google.com" not in url and "/grounding-api-redirect/" not in url:
        return url
    try:
        urllib.request.build_opener(_NoRedirect).open(urllib.request.Request(url, method="HEAD"), timeout=4)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
        if loc and loc.startswith("http"):
            return loc
    except (urllib.error.URLError, TimeoutError, ValueError):
        pass
    return url


def cited_leads(text, cites, limit=6):
    """Each '- ' line that a search result backs, with its source link.
    Lines with no citation are dropped: no link we can't vouch for."""
    out, pos = [], 0
    for line in text.split("\n"):
        start, end = pos, pos + len(line)
        pos = end + 1
        body = line.strip()
        if not re.match(r"^([-*•]|\d+[.)])\s+", body):
            continue
        hit = next(((u, t) for s, e, u, t in cites if s < end and e > start), None)
        if not hit:
            continue
        clean = re.sub(r"^([-*•]|\d+[.)])\s+", "", body)
        clean = re.sub(r"\[\d+(?:,\s*\d+)*\]|\*\*", "", clean).strip()
        title, _, why = clean.partition(" — ")
        if not why:
            title, _, why = clean.partition(" - ")
        out.append({"title": title.strip()[:140], "why": why.strip()[:240], "url": hit[0], "source": hit[1][:80]})
        if len(out) >= limit:
            break
    return out


def plan_project(goal, loc, targets):
    """Theta splits the goal: [(agent, part)], at most PROJECT_AGENTS."""
    crew = [a for a in (targets or AGENTS) if a in AGENTS and a not in ("james", "theta")]
    roster = "\n".join(f"- {a}: {AGENTS[a]['name']}, {AGENTS[a]['role']}" for a in crew)
    try:
        reply = llm_chat(AGENTS["theta"]["tier"], [
            {"role": "system", "content": system_prompt("theta")},
            {"role": "user", "content": f"Project from the user: {goal}\n" + (f"Location: {loc}\n" if loc else "")
             + f"Crew:\n{roster}\n\nSplit the project into up to {PROJECT_AGENTS} different web searches and give each "
             "to the crew member it suits best (each member at most once; the parts must not overlap). One per line, "
             "exactly: <id> | <what to search for, specific>"}], max_tokens=500)
    except LLMError:
        reply = ""
    plan, used = [], set()
    for m in re.finditer(r"^\W*([a-z]+)\s*\|\s*(.+)$", reply, re.M | re.I):
        a = m.group(1).lower()
        if a in crew and a not in used:
            used.add(a)
            plan.append((a, m.group(2).strip()[:200]))
    return plan[:PROJECT_AGENTS] or [(crew[0] if targets else "mistral", goal)]


def _work(agent, goal, loc, part):
    prompt = (f"You are {AGENTS[agent]['name']}, {AGENTS[agent]['role']}, on a team project for the user: \"{goal}\""
              + (f" (location: {loc})" if loc else "") + f".\nYour part: {part}\n\nSearch the web and list up to 5 "
              "specific, current leads (actual postings, listings or pages, not search pages), one per line exactly:\n"
              "- <name or title> — <one line: what it is and why it fits>\nOnly list what the search results show. "
              "No intro or closing.")
    text, cites, queries = gemini_search(prompt)
    _search_budget(max(queries, 1) - 1)  # one was reserved before the call
    return cited_leads(text, cites)


# Job projects go to the job boards first (real listings with pay and
# dates, free keys), then every link is checked; Gemini's web search only
# fills in when the boards come up short, or for projects that aren't
# job hunts.
ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
ADZUNA_COUNTRY = os.environ.get("ADZUNA_COUNTRY", "us").lower()
ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs"
USAJOBS_API_KEY = os.environ.get("USAJOBS_API_KEY", "")
USAJOBS_EMAIL = os.environ.get("USAJOBS_EMAIL", "")
USAJOBS_BASE = "https://data.usajobs.gov/api/Search"
JOB_MIN_LEADS = int(os.environ.get("JOB_MIN_LEADS", "8"))  # fewer live board leads than this: search the web too
_JOB_RE = re.compile(r"\b(jobs?|positions?|roles?|careers?|hiring|employment|openings?|vacanc(?:y|ies)|gigs?|internships?|"
                     r"work as|part[- ]time|full[- ]time)\b", re.I)
_DEAD_RE = re.compile(r"no longer (?:accepting|available|active)|(?:job|posting|position|listing) (?:has )?(?:expired|closed|"
                      r"been filled|is no longer)|this job is closed|page not found", re.I)


def boards_on():
    return bool((ADZUNA_APP_ID and ADZUNA_APP_KEY) or (USAJOBS_API_KEY and USAJOBS_EMAIL))


def job_query(goal, loc):
    """(keywords, place) for the job boards, from the goal."""
    place = loc or (re.search(r"\b(?:in|near|around)\s+([A-Z][\w .'-]+?(?:,\s*[A-Z]{2})?)(?:[.!?]|$|\s+(?:that|which|with|for|paying))",
                              goal) or [None, ""])[1]
    try:
        reply = llm_chat("miner", [{"role": "user", "content": f"Job search request: \"{goal}\"\nReply with one line: "
                                    "<job keywords, 1-4 words, or 'any'> | <place, or 'none'>"}], max_tokens=200)
        m = re.search(r"^\W*([^|\n]+)\|([^|\n]+)", reply, re.M)
    except LLMError:
        m = None
    words = m.group(1).strip().strip('"') if m else ""
    words = "" if words.lower() in ("any", "none", "job", "jobs", "a job") else words[:60]
    if not place and m and m.group(2).strip().lower() not in ("none", "here", ""):
        place = m.group(2).strip()[:60]
    return words, place


def _money(lo, hi):
    if not lo and not hi:
        return ""
    lo, hi = lo or hi, hi or lo
    return f"${lo:,.0f}" if round(lo) == round(hi) else f"${lo:,.0f}–${hi:,.0f}"


def adzuna_jobs(words, place, limit=20):
    q = {"app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY, "results_per_page": str(limit), "max_days_old": "30",
         "sort_by": "date", "content-type": "application/json"}
    if words:
        q["what"] = words
    if place:
        q["where"] = place
    req = urllib.request.Request(f"{ADZUNA_BASE}/{ADZUNA_COUNTRY}/search/1?" + urlencode(q), headers={"User-Agent": WIKI_UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            rows = json.loads(resp.read()).get("results", [])
    except urllib.error.HTTPError as e:
        raise LLMError(f"Adzuna returned {e.code}" + (": check ADZUNA_APP_ID / ADZUNA_APP_KEY" if e.code in (401, 403) else ""))
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise LLMError(f"Adzuna unreachable: {e!r}")
    out = []
    for r in rows:
        bits = [(r.get("company") or {}).get("display_name"), (r.get("location") or {}).get("display_name"),
                _money(r.get("salary_min"), r.get("salary_max")), f"posted {str(r.get('created', ''))[:10]}"]
        out.append({"title": html.unescape(re.sub(r"<[^>]+>", "", r.get("title", ""))).strip()[:140],
                    "why": " · ".join(b for b in bits if b and b != "posted "), "url": r.get("redirect_url", ""),
                    "source": "Jobs by Adzuna", "agent": "mistral", "board": True})
    return [x for x in out if x["url"]]


def usajobs_jobs(words, place, limit=10):
    q = {"ResultsPerPage": str(limit), "DatePosted": "30"}
    if words:
        q["Keyword"] = words
    if place:
        q.update(LocationName=place, Radius="50")
    req = urllib.request.Request(USAJOBS_BASE + "?" + urlencode(q), headers={
        "Host": "data.usajobs.gov", "User-Agent": USAJOBS_EMAIL, "Authorization-Key": USAJOBS_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            items = json.loads(resp.read()).get("SearchResult", {}).get("SearchResultItems", [])
    except urllib.error.HTTPError as e:
        raise LLMError(f"USAJOBS returned {e.code}" + (": check USAJOBS_API_KEY / USAJOBS_EMAIL" if e.code in (401, 403) else ""))
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise LLMError(f"USAJOBS unreachable: {e!r}")
    out = []
    for it in items:
        d = it.get("MatchedObjectDescriptor", {})
        pay = (d.get("PositionRemuneration") or [{}])[0]
        try:
            money = _money(float(pay.get("MinimumRange") or 0), float(pay.get("MaximumRange") or 0))
        except ValueError:
            money = ""
        rate = {"PA": "/yr", "PH": "/hr"}.get(pay.get("RateIntervalCode"), "")
        bits = [d.get("OrganizationName"), d.get("PositionLocationDisplay"), money + rate if money else "",
                f"closes {str(d.get('ApplicationCloseDate', ''))[:10]}" if d.get("ApplicationCloseDate") else ""]
        out.append({"title": (d.get("PositionTitle") or "")[:140], "why": " · ".join(b for b in bits if b),
                    "url": d.get("PositionURI") or "", "source": "USAJOBS", "agent": "mistral", "board": True})
    return [x for x in out if x["url"]]


def link_alive(url):
    """False only when the page is clearly gone (404/410, no such site, or
    an 'expired / no longer accepting' notice). Sites that refuse robots
    (403/429) count as alive: we can't tell, so we don't drop them."""
    req = urllib.request.Request(url, headers={"User-Agent": ARTICLE_UA, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            page = resp.read(300_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code not in (404, 410)
    except urllib.error.URLError as e:
        return not isinstance(getattr(e, "reason", None), socket.gaierror)
    except (TimeoutError, ValueError):
        return True
    return not _DEAD_RE.search(_plain(page[:300_000], 20000))


def check_links(leads):
    if not leads:
        return leads
    with ThreadPoolExecutor(max_workers=min(12, len(leads))) as ex:
        alive = list(ex.map(lambda x: link_alive(x["url"]), leads))
    return [x for x, ok in zip(leads, alive) if ok]


def _search_web(p, deadline):
    """Each planned agent searches its part with Gemini; (leads, failed)."""
    if not os.environ.get("GEMINI_API_KEY", ""):
        return [], {}
    if not _search_budget(len(p["plan"])):
        return [], {"hub": f"this month's web searches are used up ({SEARCH_MONTHLY_CAP})"}
    results = {}
    with ThreadPoolExecutor(max_workers=len(p["plan"])) as ex:
        futs = {ex.submit(_work, a, p["goal"], p.get("loc"), part): a for a, part in p["plan"]}
        for f, a in futs.items():
            try:
                results[a] = f.result(timeout=max(1, deadline - time.time() - 12))
            except Exception as e:  # one agent failing doesn't sink the project
                results[a] = e
    leads = [dict(x, agent=a) for a, r in results.items() if isinstance(r, list) for x in r]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for x, u in zip(leads, ex.map(lambda x: _resolve(x["url"]), leads)):
            x["url"] = u
    return leads, {a: str(r)[:120] for a, r in results.items() if not isinstance(r, list)}


def run_project(p, deadline):
    """One pass. Job boards first (for job hunts), then the web search if
    the boards came up short; every link is checked; returns new leads."""
    seen = set(p.get("seen", []))
    key = lambda u: re.sub(r"[?#].*$", "", u).rstrip("/").lower()
    failed, leads = {}, []
    if p.get("jobs") and boards_on():
        words, place = p["jobs"]
        for name, fn, on in (("Adzuna", adzuna_jobs, ADZUNA_APP_ID and ADZUNA_APP_KEY),
                             ("USAJOBS", usajobs_jobs, USAJOBS_API_KEY and USAJOBS_EMAIL)):
            if on:
                try:
                    leads += fn(words, place)
                except LLMError as e:
                    failed[name] = str(e)[:120]
        leads = check_links([x for x in leads if key(x["url"]) not in seen])
    if not p.get("jobs") or len(leads) < JOB_MIN_LEADS:
        if not p.get("jobs") and not os.environ.get("GEMINI_API_KEY", ""):
            raise LLMError("Projects search the web with Gemini; set GEMINI_API_KEY first.")
        web, web_failed = _search_web(p, deadline)
        failed.update(web_failed)
        leads += check_links([x for x in web if key(x["url"]) not in seen])
    fresh, keys = [], set()
    for x in leads:
        k = key(x["url"])
        if k in seen or k in keys:
            continue
        keys.add(k)
        fresh.append(x)
    p["seen"] = (list(seen) + list(keys))[-600:]
    return fresh, failed


def _post_leads(p, fresh, failed, first):
    st = store()
    by = {}
    for x in fresh:
        by.setdefault(x["agent"], []).append(x)
    parts = dict(p["plan"])
    line = lambda x: f"- {x['title']}" + (f" — {x['why']}" if x["why"] else "") + f"\n  {x['url']}"
    boards = [x for x in fresh if x.get("board")]
    if boards:
        names = sorted({x["source"] for x in boards})
        st.add_chat("mistral", (f"Project #{p['id']}, from the job boards" if first else f"Project #{p['id']}, new on the job boards")
                    + f" ({', '.join(names)}; links checked):\n" + "\n".join(line(x) for x in boards), channel="command")
    for a, xs in by.items():
        xs = [x for x in xs if not x.get("board")]
        if xs:
            st.add_chat(a, (f"Project #{p['id']}, my part ({parts.get(a, '')}):\n" if first else
                            f"Project #{p['id']}, new today:\n") + "\n".join(line(x) for x in xs), channel="command")
    for a, err in failed.items():
        who = AGENTS[a]["name"] if a in AGENTS and a != "hub" else a if a != "hub" else "The web search"
        st.add_chat("hub", f"Project #{p['id']}: {who} couldn't search ({err}).", channel="command")
    if first:
        summary = ""
        if fresh:
            try:
                summary = llm_chat(AGENTS["theta"]["tier"], [
                    {"role": "system", "content": system_prompt("theta")},
                    {"role": "user", "content": f"The crew's leads for \"{p['goal']}\":\n" + "\n".join(
                        f"- ({AGENTS[x['agent']]['name']}) {x['title']}: {x['why']}" for x in fresh[:20])
                     + "\n\nIn 2 sentences: what they found overall and the best next step. Use only these leads; "
                     "no links, no new facts."}], max_tokens=300).strip()
            except LLMError:
                summary = ""
        st.add_chat("theta", f"Project #{p['id']}: {len(fresh)} lead{'s' if len(fresh) != 1 else ''} with links."
                    + (f"\n{summary}" if summary else "")
                    + (f"\nI'll rerun it daily until {datetime.fromtimestamp(p['until'], hub_tz()):%b %d} and post only new ones."
                       f" /stopproject {p['id']} ends it." if fresh else
                       "\nNothing with a source this time. Try making it more specific."), channel="command")
    if fresh:
        notify("Theta", f"Project #{p['id']}: {len(fresh)} {'new ' if not first else ''}lead{'s' if len(fresh) != 1 else ''} "
               f"for “{p['goal'][:60]}”", "/chat?ch=command")


def projects():
    return _meta_json("projects", [])


def _save_project(p):
    with _PROJ_LOCK:
        ps = [x for x in projects() if x["id"] != p["id"]] + [p]
        store().set_meta("projects", json.dumps(ps[-20:]))


def start_project(goal, deadline=None):
    deadline = deadline or time.time() + 50
    clean = re.sub(r"@\w+[\s,]*", "", goal).strip()
    jobs = bool(_JOB_RE.search(clean))
    if not os.environ.get("GEMINI_API_KEY", "") and not (jobs and boards_on()):
        raise CommandError("Projects need GEMINI_API_KEY (web search), or Adzuna/USAJOBS keys for job hunts.")
    loc = home_location() if _HERE_RE.search(goal) else ""
    if _HERE_RE.search(goal) and not loc:
        raise CommandError("Where's \u201chere\u201d? Say the place (\u201c\u2026in Denver\u201d), tell the crew "
                           "\u201cremember my home is ...\u201d, or set HOME_LOCATION in Vercel.")
    targets = mentioned_agents(goal)
    pid = max([x["id"] for x in projects()] + [0]) + 1
    p = {"id": pid, "goal": clean[:300], "loc": loc, "plan": plan_project(clean, loc, targets), "seen": [],
         "until": time.time() + ORDER_DAYS * 86400, "active": True, "runs": 0}
    if jobs and boards_on():
        p["jobs"] = list(job_query(clean, loc))
    fresh, failed = run_project(p, deadline)
    p.update(runs=1, last_run=time.time(), leads=len(fresh))
    _save_project(p)
    _post_leads(p, fresh, failed, first=True)
    who = sorted({AGENTS[x["agent"]]["name"] for x in fresh if not x.get("board")})
    srcs = (["the job boards"] if any(x.get("board") for x in fresh) else []) + who
    post_event("theta", f"Theta started project #{pid}: {clean[:120]}")
    return (f"Project #{pid}: {len(fresh)} lead{'s' if len(fresh) != 1 else ''}"
            + (f" from {', '.join(srcs)}" if srcs else "") + ". See #command.")


def rerun_projects(deadline):
    """Theta's round: each active project once a day, new leads only."""
    did = []
    for p in projects():
        if not p.get("active") or time.time() > p["until"]:
            continue
        if time.time() - p.get("last_run", 0) < 20 * 3600 or time.time() > deadline - 20:
            continue
        try:
            fresh, failed = run_project(p, deadline)
        except LLMError as e:
            did.append(f"project #{p['id']} failed ({str(e)[:60]})")
            continue
        p.update(runs=p.get("runs", 0) + 1, last_run=time.time())
        _save_project(p)
        if fresh or failed:
            _post_leads(p, fresh, failed, first=False)
        did.append(f"project #{p['id']}: {len(fresh)} new")
    return did


def _cmd_log(arg):
    if not arg:
        raise CommandError("Usage: /log bench 185 4x8")
    r = james_command("log", {"sets": arg})
    store().add_chat("james", r["text"][:4000], channel=home_channel("james"), buttons=r["buttons"])
    return f"James: {r['text'].splitlines()[0][:120]} (see #{CHANNEL_IDS[home_channel('james')]['name']})"


def _cmd_project(arg):
    if not arg:
        raise CommandError("Usage: /project <what you want found>, e.g. /project find me a job in Denver")
    return start_project(arg)


def _cmd_stopproject(arg):
    try:
        pid = int(arg.strip().lstrip("#"))
    except ValueError:
        raise CommandError("Usage: /stopproject <number>")
    p = next((x for x in projects() if x["id"] == pid), None)
    if not p:
        raise CommandError(f"No project #{pid}.")
    p["active"] = False
    _save_project(p)
    return f"Project #{pid} stopped."


def _cmd_devices(arg):
    text = devices_text()
    store().add_chat("qwerty", text[:4000], channel="dev")
    n = len(sessions())
    return f"QWERTY listed {n} signed-in device{'s' if n != 1 else ''} in #dev (also Settings → Devices)."


COMMANDS = [  # shown in the "/" menu in this order
    {"name": "commandeer", "args": "[@agent] <order or task>", "about": "A standing order, or a task (\"find me...\") the whole crew works on", "run": _cmd_commandeer},
    {"name": "project", "args": "<what to find>", "about": "The crew searches the web for it, with links", "run": _cmd_project},
    {"name": "stopproject", "args": "<number>", "about": "Stop a project's daily reruns", "run": _cmd_stopproject},
    {"name": "orders", "args": "", "about": "List active orders", "run": _cmd_orders},
    {"name": "done", "args": "<number>", "about": "Close an order", "run": _cmd_done},
    {"name": "round", "args": "", "about": "Run every agent's job now", "run": _cmd_round},
    {"name": "digest", "args": "", "about": "Mistral posts today's digest", "run": _cmd_digest},
    {"name": "agenda", "args": "[tomorrow]", "about": "Remi posts the agenda", "run": _cmd_agenda},
    {"name": "remind", "args": "<when> <what> [every day] [until done]", "about": "Remi reminds you on your phone", "run": _cmd_remind},
    {"name": "reminders", "args": "", "about": "Remi lists your reminders", "run": _cmd_reminders},
    {"name": "forget", "args": "<number>", "about": "Remove a reminder", "run": _cmd_forget},
    {"name": "log", "args": "<sets>, like bench 185 4x8", "about": "James logs it in Garage Gym", "run": _cmd_log},
    {"name": "spend", "args": "$42 groceries", "about": "Glass logs an expense", "run": _cmd_spend},
    {"name": "budget", "args": "", "about": "Glass posts this month's budget", "run": _cmd_budget},
    {"name": "chart", "args": "spending|daily|calendar|coverage|activity", "about": "Charter draws a chart", "run": _cmd_chart},
    {"name": "news", "args": "", "about": "Red, Blue and Gray take the top story", "run": _cmd_news},
    {"name": "trending", "args": "", "about": "Lenz pitches the next trending title", "run": _cmd_trending},
    {"name": "summary", "args": "", "about": "Theta summarizes new reports", "run": _cmd_summary},
    {"name": "status", "args": "", "about": "Mistral posts what's wired and what isn't", "run": _cmd_status},
    {"name": "checkup", "args": "", "about": "QWERTY checks everything that can break and posts what's wrong", "run": _cmd_checkup},
    {"name": "issue", "args": "<title> - <details>", "about": "QWERTY writes up a GitHub issue with a fix", "run": _cmd_issue},
    {"name": "security", "args": "", "about": "QWERTY posts what he sees right now", "run": _cmd_security},
    {"name": "devices", "args": "", "about": "QWERTY lists every device connected, with details", "run": _cmd_devices},
    {"name": "help", "args": "", "about": "List these commands", "run": _cmd_help},
]


def run_command(text):
    """Run '/name args'. Returns a one-line result; raises CommandError."""
    name, _, arg = text.strip()[1:].partition(" ")
    cmd = next((c for c in COMMANDS if c["name"] == name.lower()), None)
    if not cmd:
        raise CommandError(f"Unknown command /{name}. Type / to see the list.")
    post_event("you", f"You used /{cmd['name']}{' ' + arg.strip() if arg.strip() else ''}")
    try:
        return cmd["run"](arg.strip())
    except LLMError as e:
        raise CommandError(str(e))


# Instant commands: plain messages an agent acts on at once, no model call.
# The chat offers them as you start typing (or tap an empty box), so they
# don't have to be remembered. keys: how a message starting with one begins.
QUICK_COMMANDS = [
    {"agent": "glass", "show": "$42 groceries", "about": "Glass logs what you spent", "insert": "$",
     "keys": ["$", "spent", "paid", "bought"]},
    {"agent": "glass", "show": "@glass undo", "about": "Glass removes the last thing he logged", "insert": "@glass undo",
     "keys": ["undo", "@glass u"]},
    {"agent": "remi", "show": "remind me tomorrow at 9am to call the dentist", "about": "Remi sets a reminder",
     "insert": "remind me ", "keys": ["remind"]},
    {"agent": "lenz", "show": "I finished Frieren, 9/10", "about": "Lenz logs something you finished, with your rating",
     "insert": "I finished ", "keys": ["i finished", "finished"]},
    {"agent": "charter", "show": "@charter chart spending", "about": "Charter posts a chart (spending, daily, calendar…)",
     "insert": "@charter chart ", "keys": ["chart", "@charter"]},
    {"agent": "james", "show": "@james bench 185 4x8", "about": "James logs a workout in Garage Gym", "insert": "@james ",
     "keys": ["@james", "bench", "squat", "deadlift", "workout"]},
]


def menu_data():
    """What the "@", "/" and instant-command menus list."""
    online = {a["bot_id"]: a["online"] for a in agent_statuses()}
    return {"agents": [{"id": a, "name": v["name"], "tier": TIER_LABELS[v["tier"]], "online": online.get(a, False)}
                       for a, v in AGENTS.items()],
            "commands": [{k: c[k] for k in ("name", "args", "about")} for c in COMMANDS],
            "quick": [q for q in QUICK_COMMANDS if q["agent"] in AGENTS]}
