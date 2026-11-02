"""Obsidian vault reads/writes, SOUL.md, vault and seat prompts.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Obsidian vault: a private GitHub repo the Obsidian Git plugin syncs, so
# the hub can read and write it with the PC off. OBSIDIAN_REPO is owner/name,
# OBSIDIAN_TOKEN a fine-grained token for that repo only (Contents: read and
# write). Layout: Theta/Memory.md (what every agent should know, written by
# you), Theta/Agents/<Name>.md (each agent's own notes; self_note appends
# there), Theta/Inbox/<date>.md (what agents were asked to remember, for you
# to keep, move or delete). Reads are cached VAULT_CACHE_SECONDS, so a chat
# message doesn't call GitHub and the prompt stays cacheable.
OBSIDIAN_REPO = os.environ.get("OBSIDIAN_REPO", "").strip().strip("/")
VAULT_DIR = os.environ.get("OBSIDIAN_DIR", "Theta").strip("/")
VAULT_CACHE_SECONDS = int(os.environ.get("VAULT_CACHE_SECONDS", "300") or 300)
VAULT_MEMORY_MAX, VAULT_AGENT_MAX = 4000, 2000  # characters read into a prompt
VAULT_API = "https://api.github.com"


def vault_on():
    return bool(OBSIDIAN_REPO and os.environ.get("OBSIDIAN_TOKEN"))


def _vault_api(method, path, body=None):
    """GitHub contents API on the vault repo; {} for a missing file."""
    url = f"{VAULT_API}/repos/{OBSIDIAN_REPO}/contents/{quote(path)}"
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None, headers={
        "Authorization": f"Bearer {os.environ.get('OBSIDIAN_TOKEN', '')}", "Accept": "application/vnd.github+json",
        "User-Agent": "Theta-hub", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 404 and method == "GET":
            return {}
        err = LLMError({401: "GitHub refused OBSIDIAN_TOKEN (expired or wrong)",
                        403: "OBSIDIAN_TOKEN can't do that: give it Contents read and write on the vault repo",
                        404: f"GitHub can't find {OBSIDIAN_REPO}: check OBSIDIAN_REPO and the token's repo access",
                        409: "the vault changed at the same moment", 422: "GitHub refused the change"}.get(
            e.code, f"GitHub returned {e.code}"))
        err.status = e.code
        raise err
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise LLMError(f"GitHub unreachable: {type(e).__name__}")


def vault_read(name, fresh=False):
    """(text, sha) of Theta/<name>, cached; ("", None) if it doesn't exist.
    On a GitHub error the last copy is used, else ("", None)."""
    key, path = f"vault:{name}", f"{VAULT_DIR}/{name}"
    hit = _meta_json(key, None)
    if hit and not fresh and time.time() - hit["at"] < VAULT_CACHE_SECONDS:
        return hit["text"], hit["sha"]
    try:
        got = _vault_api("GET", path)
    except LLMError:
        if fresh:
            raise
        return (hit["text"], hit["sha"]) if hit else ("", None)
    text = base64.b64decode(got["content"]).decode("utf-8", "replace") if got.get("content") else ""
    store().set_meta(key, json.dumps({"at": time.time(), "text": text, "sha": got.get("sha")}))
    return text, got.get("sha")


def vault_append(name, line, message):
    """Add a line to Theta/<name> (made if missing), re-reading and trying
    once more if Obsidian synced in between."""
    for attempt in (0, 1):
        text, sha = vault_read(name, fresh=True)
        new = (text.rstrip("\n") + "\n" if text.strip() else "") + line + "\n"
        body = {"message": message, "content": base64.b64encode(new.encode()).decode(), **({"sha": sha} if sha else {})}
        try:
            out = _vault_api("PUT", f"{VAULT_DIR}/{name}", body)
        except LLMError as e:
            if getattr(e, "status", None) in (409, 422) and attempt == 0:
                continue
            raise
        store().set_meta(f"vault:{name}", json.dumps({"at": time.time(), "text": new,
                                                      "sha": (out.get("content") or {}).get("sha")}))
        return new
    raise LLMError("the vault kept changing; try again")


def _vault_cut(text, limit, name):
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rsplit("\n", 1)[0] + f"\n(… cut: keep {name} under {limit} characters)"


SOUL_MAX = 4000  # characters of SOUL.md read into a prompt
_SOUL_DEFAULT = None


def soul_text():
    """Theta's personality: Theta/SOUL.md in your vault when it has one, else
    the copy that ships with the hub (api/_parts/SOUL.md). Edit the vault one
    to change who Theta is without a deploy."""
    global _SOUL_DEFAULT
    text = vault_read("SOUL.md")[0] if vault_on() else ""
    if not text.strip():
        if _SOUL_DEFAULT is None:
            try:
                with open(os.path.join(_PARTS_DIR, "SOUL.md"), encoding="utf-8") as fh:
                    _SOUL_DEFAULT = fh.read()
            except OSError:
                _SOUL_DEFAULT = ""
        text = _SOUL_DEFAULT
    return _vault_cut(text, SOUL_MAX, "SOUL.md")


def soul_prompt(agent):
    """The soul, right after the opening "You are ..." and before anything that
    changes often, so the prompt still caches. Theta is the soul; the rest of
    the crew takes its tone and values but keeps its own name and job."""
    soul = soul_text()
    if not soul:
        return ""
    if agent == "theta":
        return "\n\nYour soul (who you are; it outranks the personality words above):\n\n" + soul
    return ("\n\nThe crew's shared soul, written for Theta. Keep your own name and job above, and take its tone, "
            "warmth and values when you talk to the user:\n\n" + soul)


def vault_prompt(agent):
    """Memory.md and this agent's own note, for its prompt ("" when unlinked)."""
    if not vault_on():
        return ""
    migrate_memory_once()
    memory = _vault_cut(vault_read("Memory.md")[0], VAULT_MEMORY_MAX, "Memory.md")
    mine = _vault_cut(vault_read(f"Agents/{AGENTS[agent]['name']}.md")[0], VAULT_AGENT_MAX, f"Agents/{AGENTS[agent]['name']}.md")
    return ((f"\n\nFrom the user's notes (their Obsidian vault, Memory.md; true unless they say otherwise):\n{memory}"
             if memory else "")
            + (f"\n\nYour own notes (Agents/{AGENTS[agent]['name']}.md in their vault; follow them unless the user "
               f"says otherwise):\n{mine}" if mine else ""))


def seat_notes(agent):
    """An agent's own working notes (lessons, how you like things done),
    kept across chats and model changes and read back into its prompt.
    Unlike memory, only that agent sees them."""
    return _meta_json(f"seat:{agent}", [])


def seat_prompt(agent):
    mine = seat_notes(agent)
    return ("\n\nYour own notes from past chats (you wrote these; follow them unless the user says otherwise):\n"
            + "\n".join(f"- {n['text']}" for n in mine)) if mine else ""


def home_location():
    """HOME_LOCATION, or a remembered "home is ..." fact."""
    if HOME_LOCATION:
        return HOME_LOCATION
    for m in reversed(memory()):
        hit = re.search(r"\bhome\b[^:]{0,20}?(?:\bis\b|:|=)\s*(.+)", m["text"], re.I)
        if hit:
            return hit.group(1).strip(" .\"'")
    return ""


def _tool_remember(arg, agent):
    text = " ".join(arg.split())[:200]
    if not text:
        raise ValueError("nothing to remember")
    memory_check(text)
    if vault_on():  # Stage 7.3: Memory.md is the record; Redis only if GitHub can't be reached
        migrate_memory_once()
        try:
            full = vault_remember(text)
            return f"Remembered: {text} (in your vault's {VAULT_DIR}/Memory.md){full}"
        except LLMError as e:
            print(f"vault remember failed, kept in the hub instead: {e}")
    with _TOOL_LOCK:
        mem = [m for m in memory() if m["text"].lower() != text.lower()]
        mem.append({"id": f"m{int(time.time() * 1000) % 10**10}", "text": text, "by": agent, "at": time.time()})
        store().set_meta("memory", json.dumps(mem[-MEMORY_MAX:]))
    return f"Remembered for the whole crew: {text} (a saved note, not monitoring)"


def _tool_self_note(arg, agent):
    text = " ".join(arg.split())[:200]
    if not text:
        raise ValueError("nothing to note")
    memory_check(text)
    if vault_on():  # your vault is the record; Redis only if GitHub fails
        name = AGENTS[agent]["name"]
        try:
            if text.lower() not in vault_read(f"Agents/{name}.md", fresh=True)[0].lower():
                vault_append(f"Agents/{name}.md", f"- {text}", f"{name}: note to self")
            return f"Noted for myself: {text} (in your vault: {VAULT_DIR}/Agents/{name}.md)"
        except LLMError as e:
            print(f"vault self_note failed, kept in the hub instead: {e}")
    with _TOOL_LOCK:
        mine = [n for n in seat_notes(agent) if n["text"].lower() != text.lower()]
        mine.append({"id": f"s{int(time.time() * 1000) % 10**10}", "text": text, "by": agent, "at": time.time()})
        store().set_meta(f"seat:{agent}", json.dumps(mine[-SEAT_NOTES_MAX:]))
    return f"Noted for myself: {text} (Settings → Memory and notes)"


def _tool_forget(arg, agent):
    """Drop remembered facts, notes whose title has these words, and the
    agent's own notes that have them."""
    words = arg.lower().split()
    if not words:
        raise ValueError("forget what?")
    with _TOOL_LOCK:
        mem, ns, mine = memory(), notes(), seat_notes(agent)
        keep = [m for m in mem if not all(w in m["text"].lower() for w in words)]
        keep_n = [n for n in ns if not all(w in n["title"].lower() for w in words)]
        keep_s = [n for n in mine if not all(w in n["text"].lower() for w in words)]
        store().set_meta("memory", json.dumps(keep))
        store().set_meta("notes", json.dumps(keep_n))
        if len(keep_s) != len(mine):
            store().set_meta(f"seat:{agent}", json.dumps(keep_s))
    facts, gone_n, gone_s = len(mem) - len(keep), len(ns) - len(keep_n), len(mine) - len(keep_s)
    if vault_on():  # and the lines in Memory.md, the record since Stage 7.3
        try:
            facts = max(facts, vault_forget(words))
        except LLMError as e:
            print(f"vault forget failed: {e}")
    if not facts and not gone_n and not gone_s:
        raise ValueError(f"nothing remembered and no note matches “{arg}”")
    bits = ([f"{facts} remembered fact{'s' if facts != 1 else ''}"] if facts else []) + \
           ([f"{gone_n} note{'s' if gone_n != 1 else ''}"] if gone_n else []) + \
           ([f"{gone_s} of my own note{'s' if gone_s != 1 else ''}"] if gone_s else [])
    return "Forgot " + " and ".join(bits)


def _tool_remind(arg, agent):
    r = add_reminder(arg)
    return f"Reminder set: {reminder_line(r).split(' ', 1)[1]}"


def _tool_cancel(arg, agent):
    """Remove a reminder by #number, or by its words when only one matches."""
    num = arg.strip().lstrip("#")
    if num.isdigit():
        r = delete_reminder(int(num))
        if not r:
            raise ValueError(f"there's no reminder #{num}")
    else:
        words = arg.lower().split()
        hits = [r for r in reminders() if words and all(w in r["what"].lower() for w in words)]
        if not hits:
            raise ValueError(f"no reminder matches “{arg}”")
        if len(hits) > 1:
            raise ValueError("more than one matches (" + ", ".join(f"#{r['id']} {r['what']}" for r in hits)
                             + "); cancel one by its number")
        r = delete_reminder(hits[0]["id"])
    post_event("remi", f"Remi removed the reminder: {r['what']}")
    return f"Removed the reminder: {r['what']}"


def _tool_check(arg, agent):
    it = daily_add(arg)
    return f"Added to Today's check: {it['text']}"


def _tool_note(arg, agent):
    title, _, body = arg.partition("::")
    title, body = title.strip()[:80], body.strip()[:2000]
    if not title:
        raise ValueError("a note needs a title")
    with _TOOL_LOCK:
        ns = notes()
        ns.append({"id": f"n{int(time.time() * 1000) % 10**10}", "title": title, "text": body, "by": agent, "at": time.time()})
        store().set_meta("notes", json.dumps(ns[-NOTES_MAX:]))
    return f"Saved note: {title} (Settings → Memory and notes)"


def _tool_spend(arg, agent):
    parsed = parse_expense(arg if "$" in arg else "$" + arg)
    if not parsed:
        raise ValueError("couldn't read an amount (like $42 groceries)")
    return glass_log_reply(parsed)


def _tool_watched(arg, agent):
    title, _, rating = arg.partition(",")
    line = lenz_quick_reply(f"finished {title.strip()}" + (f", {rating.strip()}" if rating.strip() else ""))
    if not line:
        raise ValueError("couldn't read a title")
    return line


def _tool_project(arg, agent):
    return start_project(arg)
