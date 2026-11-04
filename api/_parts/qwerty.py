"""QWERTY: watchdog, security, issues.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- QWERTY: the watchdog. He checks what's wired and what's failing,
# guards the dashboard (wrong-key lockouts, secrets pasted into chat,
# known holes in the installed libraries) and helps with code: answers in
# #dev-and-security and drafts GitHub issues with a suggested fix (filed
# when GITHUB_TOKEN is set). He never changes code himself.
SEC_MAX_FAILS = int(os.environ.get("SEC_MAX_FAILS", "10"))  # wrong keys per address...
SEC_WINDOW = 15 * 60  # ...in this many seconds...
SEC_LOCK = int(os.environ.get("SEC_LOCK_MINUTES", "30")) * 60  # ...locks it out this long
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "creatorcee-prog/theta-app")
_SEC_CACHE = {"at": 0.0, "data": None}
_SEC_LOCK = threading.Lock()
_PUBLIC_PATHS = ("/ui.css", "/ui.js", "/chat.js", "/sw.js", "/manifest.webmanifest", "/favicon.ico",
                 "/icon-192.png", "/icon-512.png", "/apple-touch-icon.png", "/api/push/health")
SECURITY_HEADERS = [
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    # Only the hub's own pages may frame it: the Theta page opens the others in a sheet (2026-11-04). Other
    # sites still can't (no clickjacking).
    ("X-Frame-Options", "SAMEORIGIN"),
    ("Content-Security-Policy", "frame-ancestors 'self'; base-uri 'self'; form-action 'self'; object-src 'none'"),
    ("Permissions-Policy", "camera=(), geolocation=(), payment=(), usb=()"),
]


def client_ip(environ):
    fwd = environ.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() if fwd else environ.get("HTTP_X_REAL_IP") or environ.get("REMOTE_ADDR") or "?")[:64]


def _sec_state(fresh=False):
    """{ip: {"fails": [times], "locked_until": t}}, cached 30 s per process."""
    if fresh or time.time() - _SEC_CACHE["at"] > 30 or _SEC_CACHE["data"] is None:
        try:
            _SEC_CACHE.update(at=time.time(), data=_meta_json("sec:fails", {}))
        except Exception:
            _SEC_CACHE.update(at=time.time(), data={})
    return _SEC_CACHE["data"]


def sec_locked(ip, path):
    if path in _PUBLIC_PATHS or path.startswith("/avatar/"):
        return False
    return _sec_state().get(ip, {}).get("locked_until", 0) > time.time()


def sec_record_fail(ip, path):
    """Count a wrong key from this address; lock it out at SEC_MAX_FAILS."""
    now = time.time()
    with _SEC_LOCK:
        state = _sec_state(fresh=True)
        rec = state.setdefault(ip, {"fails": [], "locked_until": 0})
        rec["fails"] = [t for t in rec["fails"] if now - t < SEC_WINDOW] + [now]
        newly = len(rec["fails"]) >= SEC_MAX_FAILS and rec.get("locked_until", 0) <= now
        if newly:
            rec["locked_until"] = now + SEC_LOCK
            rec["lockouts"] = rec.get("lockouts", 0) + 1
        for k in [k for k, v in state.items() if not v["fails"] and v.get("locked_until", 0) < now - 86400]:
            del state[k]
        store().set_meta("sec:fails", json.dumps(dict(list(state.items())[-200:])))
    if newly:
        msg = (f"{len(rec['fails'])} wrong keys from {ip} in {SEC_WINDOW // 60} minutes (last on {path}). "
               f"Locked out for {SEC_LOCK // 60} minutes. If you just changed DASHBOARD_KEY, this is likely one of "
               "your own devices still holding the old key; it's cleared now, so sign in again. If not, consider a new "
               "DASHBOARD_KEY.")
        store().add_chat("qwerty", f"Security: {msg}", channel="dev")
        notify("QWERTY", f"Someone's guessing your dashboard key: {msg}", "/diagnostics#security")


_SECRET_PATTERNS = [
    ("an Anthropic API key", r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    ("an OpenAI API key", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    ("a Groq API key", r"\bgsk_[A-Za-z0-9]{20,}"),
    ("a Google API key", r"\bAIza[0-9A-Za-z_-]{30,}"),
    ("a GitHub token", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}"),
    ("a Slack token", r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    ("an AWS access key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("a private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"),
    ("a token (JWT)", r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]


def redact_secrets(text):
    """Hide API keys and tokens pasted into chat before they're stored or
    sent to any model. Returns (text, [what was hidden])."""
    found = []
    own = [("your dashboard key", DASHBOARD_KEY), ("your cron secret", CRON_SECRET),
           ("your VAPID private key", VAPID_PRIVATE_KEY), ("your Garage Gym secret", GARAGE_GYM_SECRET)]
    for label, value in own:
        if value and len(value) >= 8 and value in text:
            text = text.replace(value, "[hidden by QWERTY]")
            found.append(label)
    for label, pattern in _SECRET_PATTERNS:
        text, n = re.subn(pattern, "[hidden by QWERTY]", text)
        if n:
            found.append(label)
    return text, found


def warn_secrets(found):
    if not found:
        return
    what = ", ".join(dict.fromkeys(found))
    store().add_chat("qwerty", f"You pasted {what} into chat. I hid it before it was saved or sent to any "
                     "model. If it was real, treat it as leaked and rotate it where it came from.", channel="dev")
    notify("QWERTY", f"Hid {what} you pasted into chat. Rotate it if it was real.", "/chat?ch=dev")


def installed_fingerprint():
    """A short hash of the installed packages and versions: changes when a
    deploy updates one, so the library check runs again at once."""
    import importlib.metadata as md
    pkgs = sorted({f"{d.metadata['Name'].lower()}=={d.version}" for d in md.distributions()
                   if d.metadata and d.metadata["Name"]})
    return hashlib.sha256("\n".join(pkgs).encode()).hexdigest()[:12]


def dependency_vulns():
    """Known vulnerabilities in the installed Python packages, from Google's
    OSV database. [(name, version, [ids])]; raises LLMError if unreachable."""
    import importlib.metadata as md
    pkgs = sorted({(d.metadata["Name"].lower(), d.version) for d in md.distributions()
                   if d.metadata and d.metadata["Name"]})[:300]
    body = json.dumps({"queries": [{"package": {"name": n, "ecosystem": "PyPI"}, "version": v} for n, v in pkgs]})
    req = urllib.request.Request("https://api.osv.dev/v1/querybatch", data=body.encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": WIKI_UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            results = json.loads(resp.read()).get("results", [])
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise LLMError(f"OSV unreachable: {e!r}")
    return [(n, v, [x["id"] for x in r.get("vulns", [])]) for (n, v), r in zip(pkgs, results) if r.get("vulns")]


def watchdog_findings():
    """What QWERTY sees: [(severity, text)], worst first. No model calls."""
    out = []
    if not DASHBOARD_KEY:
        out.append(("high", "DASHBOARD_KEY isn't set: anyone with the link can open the dashboard and use your keys."))
    elif len(DASHBOARD_KEY) < 20:
        out.append(("warn", f"DASHBOARD_KEY is only {len(DASHBOARD_KEY)} characters; use 32+ random ones."))
    if STORAGE_MODE.startswith("memory"):
        out.append(("high", "Storage is in memory: everything is lost between requests. Connect Upstash Redis."))
    if DASHBOARD_KEY and not passkeys():
        out.append(("info", "Add Face ID sign-in (Settings) so the key stays out of your links."))
    try:
        fresh = [d for d in sessions().values() if time.time() - d["made"] < 86400]
    except Exception:
        fresh = []
    if fresh:
        out.append(("warn", "New sign-in in the last day: " + "; ".join(
            f"{d['label']} near {d.get('place') or 'unknown'} ({d['how']})" for d in fresh[:4])
            + ". If one isn't yours, sign it out in Settings → Devices and change DASHBOARD_KEY."))
    for r in wiring():
        if r["state"] == "bad" or (r["state"] == "off" and r.get("testable", True)):
            out.append(("warn", f"{r['name']}: {r['note']}"))
    for t in ("low_brain", "manager", "miner"):
        fb = recent_fallback(t)
        if fb:
            out.append(("info", f"{TIER_LABELS[t]} model was busy {fb['ago']} ago; {fb['model']} answered instead."))
    failures = _meta_json("round:failures", {})
    for a, err in failures.items():
        out.append(("warn", f"{display_name(a)}'s last round job failed: {err}"))
    dead = [NEWS_SOURCE_NAMES.get(urlparse(u).netloc, urlparse(u).netloc) for u in NEWS_FEEDS + ENTERTAINMENT_FEEDS
            if u in _FEED_CACHE and not _FEED_CACHE[u][1]]
    if dead:
        out.append(("info", "Feeds giving nothing right now: " + ", ".join(dead)))
    if not CRON_SECRET:
        out.append(("info", "CRON_SECRET isn't set, so rounds and reminders can't run on a schedule."))
    now = time.time()
    sec = _sec_state(fresh=True)
    locked = [ip for ip, v in sec.items() if v.get("locked_until", 0) > now]
    recent = sum(1 for v in sec.values() for t in v["fails"] if now - t < 86400)
    if locked:
        out.append(("high", f"Locked out for guessing keys: {', '.join(locked)}."))
    elif recent >= 3:
        out.append(("warn", f"{recent} wrong-key attempts in the last day."))
    for name, ver, ids in json.loads(store().get_meta("sec:osv") or "[]"):
        out.append(("high", f"{name} {ver} has known vulnerabilities ({', '.join(ids[:3])}). Update requirements.txt."))
    order = {"high": 0, "warn": 1, "info": 2}
    return sorted(out, key=lambda f: order[f[0]])


def _round_qwerty(ctx):
    """The watchdog report (posted when what he sees changes; pushes for new
    high-severity findings) and a weekly check of the installed libraries."""
    st = store()
    did = []
    last_osv = float(st.get_meta("sec:osv_at") or 0)
    fp = installed_fingerprint()
    if time.time() - last_osv > 7 * 86400 or st.get_meta("sec:osv_fp") != fp:  # weekly, and after any update
        try:
            vulns = dependency_vulns()
            st.set_meta("sec:osv", json.dumps(vulns))
            st.set_meta("sec:osv_at", str(time.time()))
            st.set_meta("sec:osv_fp", fp)
            did.append(f"checked the libraries ({len(vulns)} with known holes)")
        except LLMError as e:
            did.append(f"couldn't check the libraries ({str(e)[:60]})")
    findings = watchdog_findings()
    sig = "|".join(f"{s}:{t}" for s, t in findings if not t.startswith(("Feeds giving", "Low Brain model", "Manager model", "Miner model")))
    before = st.get_meta("round:qwerty:sig")
    if sig == before:
        did.append("all quiet" if not findings else "nothing new")
    else:
        st.set_meta("round:qwerty:sig", sig)
        icon = {"high": "[!]", "warn": "[~]", "info": "[i]"}
        st.add_chat("qwerty", ("Watchdog: all clear. QWERTY's checks flagged nothing." if not findings else
                               "Watchdog report:\n" + "\n".join(f"{icon[s]} {t}" for s, t in findings)
                               + "\nAsk me in #dev-and-security, or /issue to write one up."), channel="dev")
        old_high = {t for t in (before or "").split("|") if t.startswith("high:")}
        new_high = [t for s, t in findings if s == "high" and f"high:{t}" not in old_high]
        if new_high:
            notify("QWERTY", " | ".join(new_high[:2]) + (f" (+{len(new_high) - 2} more)" if len(new_high) > 2 else ""),
                   "/diagnostics#security")
        did.append(f"posted a watchdog report ({len(findings)} finding{'s' if len(findings) != 1 else ''})")
    return ", ".join(did)


HUB_MAP = (
    "How the hub is built (for code questions): one Python file, api/index.py, deployed on Vercel as a "
    "WSGI app (app() -> handle(method, path, query, headers, body)); vercel.json sends every path to it, "
    "60 s max per request. Storage: Upstash Redis over REST (KVStore._cmd), with key/values in the hash "
    "hub:meta (get_meta/set_meta, _meta_json); MemoryStore when no KV vars. Models: llm_chat(tier, messages) "
    "over OpenAI-compatible APIs (Groq for miners/managers, Gemini for the low brain), with retry and a "
    "fallback model. Agents: the AGENTS dict, PERSONAS, ABILITIES, system_prompt(). Rounds: run_round() runs "
    "ROUND_JOBS in parallel (POST /api/round from Supabase Cron, 3x a day); reminders: run_tick() via POST "
    "/api/tick every 5 min. Chat: add_chat()/allchat_view() with channels (CHANNELS). Pages are server-rendered "
    "strings (page(), home_page(), chat_page(), lenz_page()...) with CSS in _BASE_CSS and themes in THEMES; "
    "scripts in _UI_JS_SRC, _CHAT_JS. Push: notify() with pywebpush and VAPID keys. Tests are standalone "
    "scripts that call app() with fake providers. Time: the server clock is UTC and nothing needs it changed; every "
    "time the hub shows or schedules uses HUB_TIMEZONE (an env var, default America/Denver = MDT/MST). To change "
    "it, set HUB_TIMEZONE in Vercel → Settings → Environment Variables and redeploy. Agents' tools (ACTION lines) "
    "are in TOOLS; shared memory and notes in hub:meta 'memory' and 'notes'.")


def qwerty_context():
    findings = watchdog_findings()
    try:
        devs = devices_text()
    except Exception as e:
        devs = f"(couldn't read the device list: {e!r})"
    settable = "\n".join(f"- {k} = {os.environ.get(k, '') or '(not set)'}" for k in sorted(SETTABLE))
    can = ("Settings changes apply on approval" + (" and redeploy automatically." if VERCEL_DEPLOY_HOOK else
                                                    "; the user redeploys (VERCEL_DEPLOY_HOOK isn't set).")
           if VERCEL_TOKEN and VERCEL_PROJECT else
           "Settings changes can't be applied yet: VERCEL_TOKEN and VERCEL_PROJECT aren't set (you can still "
           "propose; tell the user what to add).")
    return ("\n\n" + HUB_MAP + "\n\nSettings you can propose changing (current values, exact):\n" + settable
            + "\n" + can + "\n\nWhat you see right now (exact):\n"
            + ("\n".join(f"- [{s}] {t}" for s, t in findings) if findings else "- all clear")
            + "\n\nWhat's connected (exact; this is all the hub can know):\n" + devs
            + "\n\nServer speed, last 20 loads (usual ms / slowest ms / storage trips / loads, cold starts):\n"
            + ("\n".join(f"- {p}: {a} / {mx} / {c} / {n}, {cold} cold" for p, a, mx, c, n, cold in perf_rows()[0])
               or "- not measured yet"))


def file_issue(title, details=""):
    """QWERTY writes up an issue with a suggested fix; files it on GitHub
    when GITHUB_TOKEN is set. Returns (url or None, body)."""
    body = llm_chat("manager", [
        {"role": "system", "content": system_prompt("qwerty")},
        {"role": "user", "content": f"Write a GitHub issue for: {title}\n{details}\n\nUse these headings: "
         "## What's wrong, ## Where (functions in api/index.py, if you can tell), ## Suggested fix "
         "(concrete steps or a short code sketch), ## How to check it's fixed. Say plainly what you're unsure of. "
         "No secrets, keys or personal data."}], max_tokens=1400).strip()
    body, _ = redact_secrets(body)
    body += "\n\n_Written by QWERTY, the hub's watchdog._"
    if not GITHUB_TOKEN:
        return None, body
    req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/issues",
                                 data=json.dumps({"title": title[:200], "body": body}).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json",
                                          "User-Agent": WIKI_UA, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()).get("html_url"), body
    except urllib.error.HTTPError as e:
        raise LLMError(f"GitHub returned {e.code}: check GITHUB_TOKEN can write issues on {GITHUB_REPO}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise LLMError(f"GitHub unreachable: {e!r}")


def _cmd_issue(arg):
    if not arg.strip():
        raise CommandError("Try /issue Lenz's posters are missing - what you saw and where")
    title, _, details = arg.partition(" - ")
    url, body = file_issue(title.strip(), details.strip())
    if url:
        store().add_chat("qwerty", f"Filed it: {url}", channel="dev")
        return f"QWERTY filed the issue: {url}"
    store().add_chat("qwerty", f"Here's the write-up (set GITHUB_TOKEN and I'll file these for you):\n\n# {title.strip()}\n{body}",
                     channel="dev")
    return "QWERTY wrote it up in #dev-and-security."


def _cmd_security(arg):
    findings = watchdog_findings()
    store().add_chat("qwerty", "Security and health right now:\n" + (
        "\n".join(f"- [{s}] {t}" for s, t in findings) if findings else "- all clear"), channel="dev")
    return f"{len(findings)} finding{'s' if len(findings) != 1 else ''}."


ROUND_JOBS = {
    "theta": _round_theta, "remi": _round_remi, "glass": _round_glass, "charter": _round_charter, "mistral": _round_mistral, "james": _round_james,
    "lenz": _round_lenz, "red": _round_news("red"), "blue": _round_news("blue"),
    "gray": _round_news("gray"), "qwerty": _round_qwerty,
}
_NEWS_AGENTS = {"red", "blue", "gray"}


def round_summary(posts):
    """Mistral posts one update from what the crew reported this round, and
    keeps their reports in his facts for follow-up questions. Charts and
    pictures come along as his own posts."""
    reports = {}
    for p in posts:
        reports.setdefault(p["from"], []).append(p["text"])
    store().set_meta("round:reports", json.dumps({"at": time.time(), "reports": {a: "\n\n".join(t)[:3000] for a, t in reports.items()}}))
    who = sorted(reports, key=rank)
    listing = "\n\n".join(f"## {AGENTS[a]['name']}\n" + "\n\n".join(reports[a]) for a in who)
    _REQ.trail, _REQ.tok = [], [0, 0]
    poster = "theta" if head_on() else DESK  # the single head posts the round itself, in its own voice
    try:
        working(poster)
        msgs = [{"role": "system", "content": system_prompt(poster) + (
                    " You're posting your round update for the user: what your scheduled checks found. Use only the "
                    "notes below; never add facts, numbers or events. Lead with anything that needs the user, then a "
                    "few short lines. Say it as yourself; don't name the crew." if head_on() else
                    " You're posting the crew's round update for the user. Use only the reports below; never add facts, "
                    "numbers or events. Lead with anything that needs the user, then one short line (or a few bullets) "
                    "per agent with what they found. Name who each part is from.")},
                {"role": "user", "content": "The crew's reports from this round (exact):\n\n" + listing}]
        text = (head_chat(msgs, 900) if head_on() else
                desk_chat(msgs, 900, **desk_route("round"))).strip()  # migration #6
    except LLMError:
        text = "Round update from the crew:\n\n" + "\n\n".join(f"**{AGENTS[a]['name']}:** " + " ".join(reports[a])[:600] for a in who)
    _REQ.trail = who + [poster]
    store().add_chat(poster, text[:4000], extra=reply_extra())
    for p in posts:
        if p.get("image"):
            store().add_chat(poster, f"From {AGENTS[p['from']]['name']}: {_first_line(p['text'])}", image=p["image"])


# summary: the crew report to Mistral, who posts one update (and keeps their
# reports in his facts); agents: each agent posts its own round, as before.
ROUND_POSTS = os.environ.get("ROUND_POSTS", "summary").lower()

# Typing guard: while you're typing in the chat (the composer pings
# /api/typing), scheduled rounds hold their update and non-urgent pushes
# wait, so nothing lands mid-thought. Once you've been quiet this long,
# the next tick or round posts what was held, with one push. Reminders and
# security alerts always go out at once. 0 turns it off.
TYPING_GUARD_SECONDS = int(os.environ.get("TYPING_GUARD_SECONDS", "120") or 0)


def user_typing():
    if TYPING_GUARD_SECONDS <= 0:
        return False
    return time.time() - float(store().get_meta("user:typing") or 0) < TYPING_GUARD_SECONDS


def held():
    return _meta_json("guard:held", {"posts": [], "pushes": []})


_GUARD_LOCK = threading.Lock()


def _hold(posts=(), push=None):
    with _GUARD_LOCK:
        h = held()
        h["posts"] = (h["posts"] + list(posts))[-40:]
        if push:
            h["pushes"] = (h["pushes"] + [push])[-10:]
        store().set_meta("guard:held", json.dumps(h))


def release_held():
    """Post what the guard held, once you're not typing. Returns what went out."""
    if user_typing():
        return None
    with _GUARD_LOCK:
        h = held()
        if not (h["posts"] or h["pushes"]):
            return None
        store().set_meta("guard:held", json.dumps({"posts": [], "pushes": []}))
    if h["posts"]:
        try:
            round_summary(h["posts"])
        except Exception as e:  # same rule as a live round: the reports are kept
            print(f"held round summary failed: {e!r}")
    if h["pushes"]:
        first = h["pushes"][0]
        body = first["body"] if len(h["pushes"]) == 1 else "; ".join(
            f"{p['title']}: {p['body']}" for p in h["pushes"])[:240]
        notify(first["title"] if len(h["pushes"]) == 1 else "Theta", body,
               first["url"] if len(h["pushes"]) == 1 else "/chat")
    return {"posts": len(h["posts"]), "pushes": len(h["pushes"])}


def run_round(force=False, now=None, only=None):
    """Run every agent's job that is due (or all, with force; or just `only`),
    in parallel, and post one Hub line saying what each did."""
    started = time.time()
    now = now or started
    st = store()
    guard = not force and user_typing()  # you asked for a forced round: it posts now
    if not guard:
        release_held()
    last = json.loads(st.get_meta("round:last") or "{}")
    due = [a for a in ROUND_JOBS if (only is None or a in only)
           and (force or now - last.get(a, 0) >= ROUND_MIN_GAP)]
    ctx = {}
    if _NEWS_AGENTS & set(due):  # the news miners all take the same new story
        breaking, top = news_items()
        ctx["story"] = next((i for i in breaking + top if i["url"] not in _seen("round:news:seen")), None)
        if ctx["story"]:
            try:  # one neutral brief, read from the article itself, for all three
                ctx["brief"] = story_brief(ctx["story"]["title"], ctx["story"]["url"], ctx["story"]["source"],
                                           ctx["story"].get("summary", ""))
            except LLMError:
                ctx["brief"] = None

    posts = []  # what the crew would have posted: Mistral sums it up

    def run(a):
        _RT.capture = [] if ROUND_POSTS != "agents" else None
        try:
            return a, ROUND_JOBS[a](ctx), None
        except (LLMError, ValueError, KeyError) as e:
            return a, None, str(e)[:160]
        finally:
            posts.extend(_RT.capture or [])
            _RT.capture = None
    results = {}
    with ThreadPoolExecutor(max_workers=max(1, len(due))) as ex:
        for a, done, err in ex.map(run, due):
            results[a] = {"ok": err is None, "did": done or err}
            if err is None:
                last[a] = now
                st.touch(a, done[:80])
    st.set_meta("round:last", json.dumps(last))
    failures = _meta_json("round:failures", {})
    for a, r in results.items():
        if r["ok"]:
            failures.pop(a, None)
        else:
            failures[a] = r["did"]
    st.set_meta("round:failures", json.dumps(failures))
    if ctx.get("story") and any(results.get(a, {}).get("ok") for a in _NEWS_AGENTS):
        _mark_seen("round:news:seen", ctx["story"]["url"])
        st.set_meta("round:news:last", json.dumps({"title": ctx["story"]["title"], "coverage": {
            a: len(side_coverage(a, ctx["story"]["title"])) for a in _NEWS_AGENTS}}))
    parts = [f"{AGENTS[a]['name']}: {r['did']}" if r["ok"] else f"{AGENTS[a]['name']}: failed ({r['did']})"
             for a, r in results.items()]
    idle = [AGENTS[a]["name"] for a in AGENTS if a not in ROUND_JOBS] if only is None else []
    if idle:
        parts.append(f"{', '.join(idle)}: no job yet")
    if results:
        try:
            note = refresh_windows(deadline=started + 55)  # vercel.json allows 60 s
        except Exception as e:  # windows are cosmetic: never fail a round over them
            note = f"couldn't refresh ({str(e)[:80]})"
        if note:
            parts.append(f"Windows: {note}")
    if posts and guard:
        _hold(posts)
    elif posts:
        try:
            round_summary(posts)
        except Exception as e:  # the reports are kept even if the summary fails
            print(f"round summary failed: {e!r}")
    if results:
        post_event("hub", "Round: " + "; ".join(parts) + ".")
        try:
            round_push(results)
        except Exception as e:  # a notification never sinks a round
            print(f"round push failed: {e!r}")
    return {"ok": True, "ran": results,
            "skipped": [a for a in ROUND_JOBS if a not in due], "no_job": idle}
