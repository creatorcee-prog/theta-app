"""Obsidian as the main memory (Stage 7.3). Part of api/index.py, loaded INTO
its namespace by _load_part() (see store.py).

With the vault linked, Theta/Memory.md is the one record of what Theta
knows about you: "remember" writes there, "forget" removes lines there,
and what Redis held moves there once. Redis keeps a copy only as the
fallback when GitHub can't be reached. Two rules from Hermes Agent:
- Bounded: Memory.md has a size budget (VAULT_MEMORY_MAX). When it's
  full, a new memory is refused with a request to tidy it, instead of the
  oldest line silently dropping off.
- Checked: text that reads like instructions planted for the model, or
  that hides invisible characters, is never saved (a web page an agent
  read could try to plant a "memory").
Playbooks (Theta/Playbooks/<name>.md) are saved how-tos with When to use,
Steps, Pitfalls and How to check. The one that fits a message is added to
Theta's prompt before it answers (agents get one pass, so it can't ask
for one)."""

_HIDDEN_CHARS = re.compile("[​-‏‪-‮⁠-⁤﻿]")
_PLANTED = re.compile(
    r"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier|system)\s+"
    r"(?:instructions?|messages?|prompts?|rules?)|\byou\s+are\s+now\b|\bnew\s+(?:system\s+)?instructions?\s*:|"
    r"\b(?:reveal|print|show)\s+(?:your|the)\s+(?:system\s+)?(?:prompt|instructions)\b|<\s*/?\s*system\s*>", re.I)
PLAYBOOKS_DIR = "Playbooks"
PLAYBOOK_MAX = 2500  # characters of a playbook added to a prompt


def memory_check(text):
    """ValueError when text shouldn't be saved as a memory."""
    if _HIDDEN_CHARS.search(text):
        raise ValueError("that text has hidden characters in it, so I won't save it as a memory")
    if _PLANTED.search(text):
        raise ValueError("that reads like instructions for me, not a fact about you, so I won't save it as a memory")


def vault_write(name, text, message, sha=None):
    """Write Theta/<name> whole (sha: the version it replaces; None for a new file)."""
    out = _vault_api("PUT", f"{VAULT_DIR}/{name}", {"message": message,
                                                     "content": base64.b64encode(text.encode()).decode(),
                                                     **({"sha": sha} if sha else {})})
    store().set_meta(f"vault:{name}", json.dumps({"at": time.time(), "text": text,
                                                  "sha": (out.get("content") or {}).get("sha")}))
    return text


def memory_lines(text):
    return [l[2:].strip() for l in text.splitlines() if l.startswith("- ")]


def vault_remember(text):
    """Add a line to Memory.md. Returns a note on how full it is (or "")."""
    current = vault_read("Memory.md", fresh=True)[0]
    if text.lower() in (l.lower() for l in memory_lines(current)):
        return ""
    used = len(current.strip()) + len(text) + 3
    if used > VAULT_MEMORY_MAX:
        raise ValueError(f"Memory.md is full ({len(current.strip())} of {VAULT_MEMORY_MAX} characters). Merge or delete "
                         "a few lines in Obsidian, then ask me again")
    vault_append("Memory.md", f"- {text}", "Theta: remembered")
    return (f" (Memory.md is {used * 100 // VAULT_MEMORY_MAX}% full: time to tidy it in Obsidian)"
            if used >= VAULT_MEMORY_MAX * 0.8 else "")


def vault_forget(words):
    """Remove Memory.md lines that have all these words; returns how many."""
    for attempt in (0, 1):
        text, sha = vault_read("Memory.md", fresh=True)
        lines = text.splitlines()
        keep = [l for l in lines if not (l.startswith("- ") and all(w in l.lower() for w in words))]
        if len(keep) == len(lines):
            return 0
        try:
            vault_write("Memory.md", "\n".join(keep).rstrip("\n") + "\n", "Theta: forgot", sha)
        except LLMError as e:
            if getattr(e, "status", None) in (409, 422) and attempt == 0:
                continue
            raise
        return len(lines) - len(keep)
    raise LLMError("the vault kept changing; try again")


def vault_migrated():
    return store().get_meta("vault:migrated") == "1"


def migrate_memory_once():
    """Move what Redis remembers (and Theta's own notes) into Memory.md, once.
    Stops at the size budget, leaving the rest in Redis; never raises."""
    if not vault_on() or vault_migrated():
        return
    if time.time() - float(store().get_meta("vault:migrate_try") or 0) < 600:
        return  # it just failed: don't make every message wait on GitHub again
    store().set_meta("vault:migrate_try", str(time.time()))
    try:
        current = vault_read("Memory.md", fresh=True)[0]
        have = {l.lower() for l in memory_lines(current)}
        add = []
        for t in [m["text"] for m in memory()] + [n["text"] for n in seat_notes("theta")]:
            if t.lower() in have or _HIDDEN_CHARS.search(t) or _PLANTED.search(t):
                continue
            if len(current.strip()) + sum(len(x) + 3 for x in add) + len(t) + 3 > VAULT_MEMORY_MAX:
                break
            add.append(t); have.add(t.lower())
        if add:
            body = (current.rstrip("\n") + "\n" if current.strip() else "# What Theta knows about you\n\n")
            vault_write("Memory.md", body + "".join(f"- {t}\n" for t in add), "Theta: moved memory from the hub",
                        vault_read("Memory.md")[1])
        store().set_meta("vault:migrated", "1")
    except LLMError as e:
        print(f"moving memory to the vault failed (will retry): {e}")


# ---- Playbooks
def vault_list(folder):
    """[(name, path)] of the .md files in Theta/<folder>, cached like reads."""
    key = f"vault:dir:{folder}"
    hit = _meta_json(key, None)
    if hit and time.time() - hit["at"] < VAULT_CACHE_SECONDS:
        return [tuple(x) for x in hit["files"]]
    try:
        got = _vault_api("GET", f"{VAULT_DIR}/{folder}")
    except LLMError:
        return [tuple(x) for x in hit["files"]] if hit else []
    files = [(f["name"][:-3], f"{folder}/{f['name']}") for f in (got if isinstance(got, list) else [])
             if f.get("type", "file") == "file" and f.get("name", "").endswith(".md")][:30]
    store().set_meta(key, json.dumps({"at": time.time(), "files": files}))
    return files


_WORD = re.compile(r"[a-z][a-z']{3,}")
_COMMON = {"this", "that", "with", "what", "when", "have", "your", "from", "about", "would", "could", "should",
           "there", "their", "them", "then", "they", "just", "like", "want", "need", "help", "please", "theta"}


def playbook_for(message):
    """(name, text) of the playbook that fits this message best, or None.
    Fits: at least two of the message's words in its name or When to use."""
    if not vault_on() or not message.strip():
        return None
    words = {w for w in _WORD.findall(message.lower()) if w not in _COMMON}
    best, best_score = None, 1
    for name, path in vault_list(PLAYBOOKS_DIR):
        text = vault_read(path)[0]
        head = (name + " " + text.split("## Steps")[0][:400]).lower()
        score = sum(1 for w in words if w in head) + (2 if name.lower() in message.lower() else 0)
        if score > best_score:
            best, best_score = (name, text), score
    return best


def playbook_prompt(message):
    hit = playbook_for(message)
    if not hit:
        return ""
    name, text = hit
    return (f"\n\nOne of your playbooks fits this ({VAULT_DIR}/{PLAYBOOKS_DIR}/{name}.md, written with the user). Follow "
            f"it unless the message clearly asks for something else:\n{_vault_cut(text, PLAYBOOK_MAX, name + '.md')}")


def _tool_playbook(arg, agent):
    """Save a new playbook: name :: when to use :: steps (:: pitfalls :: how to check)."""
    if not vault_on():
        raise ValueError("playbooks live in the Obsidian vault, and it isn't linked (OBSIDIAN_REPO / OBSIDIAN_TOKEN)")
    parts = [p.strip() for p in arg.split("::")]
    name = re.sub(r"[^\w\- ]", "", parts[0])[:60].strip()
    if not name or len(parts) < 3 or not parts[1] or not parts[2]:
        raise ValueError("a playbook needs a name, when to use it, and its steps: name :: when to use :: steps")
    for p in parts:
        memory_check(p)
    path = f"{PLAYBOOKS_DIR}/{name}.md"
    if vault_read(path, fresh=True)[1]:
        raise ValueError(f"there's already a playbook called {name}; edit it in Obsidian")
    steps = "\n".join(f"{i}. {s.strip()}" for i, s in enumerate(re.split(r"\s*;\s*", parts[2]), 1) if s.strip())
    body = (f"# {name}\n\n## When to use\n{parts[1]}\n\n## Steps\n{steps}\n\n## Pitfalls\n"
            f"{parts[3] if len(parts) > 3 and parts[3] else '-'}\n\n## How to check\n"
            f"{parts[4] if len(parts) > 4 and parts[4] else '-'}\n")
    vault_write(path, body, f"Theta: new playbook {name}")
    store().set_meta(f"vault:dir:{PLAYBOOKS_DIR}", "null")  # list it at once
    return f"Saved the playbook “{name}” ({VAULT_DIR}/{path}); edit it in Obsidian anytime"


TOOLS["playbook"] = ("playbook | <name> :: <when to use it> :: <steps, separated by ;> :: <pitfalls> :: <how to check>   "
                     "(save a how-to you'll follow next time)", _tool_playbook, None)


# ---- Use it or lose it (2026-11-02). Each Memory.md line keeps a use count
# and last-used time (in Redis, "mem:use", so Memory.md stays clean). A line
# counts as used when a reply draws on it: it shares the line's key words.
# Once a week, lines unused for MEMORY_FADE_DAYS move to Theta/Archive.md
# (never deleted); a line written "- ! ..." is pinned and never fades.
# Similar lines are offered as a merge you Approve, never merged on their own.
MEMORY_FADE_DAYS = int(os.environ.get("MEMORY_FADE_DAYS", "30") or 30)
MEMORY_REVIEW_MIN = 4  # new messages from you before the round review looks again


def _key_words(text):
    return {w for w in _WORD.findall(text.lower()) if w not in _COMMON}


def _mem_key(line):
    return line.strip().lower()[:200]


def memory_usage():
    return _meta_json("mem:use", {})


def memory_mark_used(reply):
    """Count the Memory.md lines this reply drew on; start the clock on new lines."""
    if getattr(_REQ, "hb_calls", None) is not None:  # the harness test leaves memory counts alone
        return
    if not vault_on() or not reply:
        return
    lines = memory_lines(vault_read("Memory.md")[0])
    if not lines:
        return
    words, now, use = _key_words(reply), time.time(), memory_usage()
    changed = False
    for line in lines:
        k = _mem_key(line)
        if k not in use:
            use[k] = {"n": 0, "first": now, "last": 0}
            changed = True
        lw = _key_words(line.lstrip("! "))
        if lw and len(lw & words) >= min(2, len(lw)):
            use[k]["n"] += 1
            use[k]["last"] = now
            changed = True
    if changed:
        keep = {_mem_key(l) for l in lines}
        store().set_meta("mem:use", json.dumps({k: v for k, v in use.items() if k in keep}))


def memory_fade(now=None):
    """Move lines unused for MEMORY_FADE_DAYS to Archive.md. Returns how many."""
    now = now or time.time()
    text, sha = vault_read("Memory.md", fresh=True)
    use, cutoff = memory_usage(), now - MEMORY_FADE_DAYS * 86400
    gone = []
    for line in memory_lines(text):
        u = use.get(_mem_key(line))
        if line.startswith("!") or not u:  # pinned, or not tracked yet: the clock hasn't started
            continue
        if u["first"] < cutoff and (u["last"] or u["first"]) < cutoff:
            gone.append((line, u["n"]))
    if not gone:
        return 0
    drop = {l for l, _ in gone}
    kept = [l for l in text.splitlines() if not (l.startswith("- ") and l[2:].strip() in drop)]
    vault_write("Memory.md", "\n".join(kept).rstrip("\n") + "\n", f"Theta: {len(gone)} unused memories to the archive", sha)
    day = datetime.now(hub_tz()).strftime("%Y-%m-%d")
    archive = vault_read("Archive.md", fresh=True)
    body = archive[0].rstrip("\n") + "\n" if archive[0].strip() else (
        "# Theta's archive\n\nMemories that went unused for a while. Move one back to Memory.md to keep it.\n\n")
    vault_write("Archive.md", body + "".join(f"- {l} (archived {day}, used {n} times)\n" for l, n in gone),
                "Theta: archived unused memories", archive[1])
    return len(gone)


def _json_in(text):
    """The first JSON value in a model reply (it may wrap it in prose or a fence)."""
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def propose_to_user(prop, text, labels=("Approve", "Decline")):
    """A proposal you Approve or Decline (or labels) in the chat, posted by Theta."""
    pid = hashlib.sha1(f"{time.time_ns()}{text}".encode()).hexdigest()[:8]
    with _TOOL_LOCK:
        ps = proposals()
        ps[pid] = dict(prop, id=pid, by="theta", at=time.time(), status="open")
        store().set_meta("proposals", json.dumps(dict(list(ps.items())[-40:])))
    store().add_chat("theta", text, buttons=[{"id": f"qp:{pid}:yes", "label": labels[0], "style": "primary"},
                                             {"id": f"qp:{pid}:no", "label": labels[1]}])
    return pid


def memory_merge_offers(limit=2):
    """Ask the head's model which memory lines say the same thing; offer each merge."""
    lines = [l for l in memory_lines(vault_read("Memory.md")[0]) if not l.startswith("!")]
    if len(lines) < 6:
        return 0
    listing = "\n".join(f"{i}. {l}" for i, l in enumerate(lines))
    try:
        got = _json_in(head_chat([{"role": "user", "content": (
            "These are memory lines about a user. Find at most 2 groups of lines that overlap or repeat each other "
            "and could be one shorter line without losing a fact. Reply with JSON only: "
            '[{"lines": [numbers], "merged": "the one line"}], or [] if none.\n\n' + listing)}], 500))
    except LLMError:
        return 0
    made = 0
    for g in (got or [])[:limit]:
        try:
            idx = sorted({int(i) for i in g["lines"]})
            merged = " ".join(str(g["merged"]).split())[:200]
        except (KeyError, TypeError, ValueError):
            continue
        if len(idx) < 2 or any(i < 0 or i >= len(lines) for i in idx) or not merged:
            continue
        try:
            memory_check(merged)
        except ValueError:
            continue
        old = [lines[i] for i in idx]
        propose_to_user({"kind": "memory_merge", "remove": old, "add": merged,
                         "summary": f"Merge {len(old)} memories into: {merged}"},
                        "I could tidy my memory. Merge these:\n" + "\n".join(f"- {o}" for o in old)
                        + f"\ninto one line:\n- {merged}")
        made += 1
    return made


def memory_review():
    """The round review: from the chat since the last review, propose up to 3
    memories and 1 playbook. Each waits for your Approve. Returns how many."""
    st = store()
    last = int(st.get_meta("mem:review_last_id") or 0)
    msgs = [m for m in st.list_chat(ALLCHAT_KEEP) if m["id"] > last and m.get("kind") != "event"]
    mine = [m for m in msgs if m["from"] == "you"]
    if len(mine) < MEMORY_REVIEW_MIN:
        return 0
    st.set_meta("mem:review_last_id", str(msgs[-1]["id"]))
    transcript = "\n".join(chat_line(m) for m in msgs[-40:])
    current = vault_read("Memory.md")[0]
    try:
        got = _json_in(head_chat([{"role": "user", "content": (
            "Read this chat between the user and Theta, their assistant. Propose what's worth keeping long-term:\n"
            "- memories: up to 3 short facts about the user, their preferences, or corrections they made to how "
            "Theta works, that aren't already in their memory file below. Only things they said or clearly showed; "
            "never guesses, never secrets.\n"
            "- playbook: at most 1, only if the user taught a repeatable way to do something.\n"
            'Reply with JSON only: {"memories": ["..."], "playbook": null or {"name": "...", "when": "...", '
            '"steps": ["..."]}}\n\nTheir memory file:\n' + (current or "(empty)") + "\n\nThe chat:\n" + transcript)}],
            600))
    except LLMError:
        return 0
    if not isinstance(got, dict):
        return 0
    have = {l.lower() for l in memory_lines(current)}
    made = 0
    for m in (got.get("memories") or [])[:3]:
        line = " ".join(str(m).split())[:200]
        try:
            memory_check(line)
        except ValueError:
            continue
        if not line or line.lower() in have:
            continue
        propose_to_user({"kind": "memory_add", "line": line, "summary": f"Remember: {line}"},
                        f"Worth remembering?\n- {line}")
        made += 1
    pb = got.get("playbook")
    if isinstance(pb, dict) and pb.get("name") and pb.get("when") and pb.get("steps"):
        steps = "; ".join(str(s) for s in pb["steps"])[:800]
        arg = f"{pb['name']} :: {pb['when']} :: {steps}"
        try:
            memory_check(arg)
            propose_to_user({"kind": "playbook_add", "arg": arg, "summary": f"Save the playbook {pb['name']}"},
                            f"You showed me a way to do something. Save it as a playbook?\n**{pb['name']}**: "
                            f"{pb['when']}\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(pb["steps"], 1)))
            made += 1
        except ValueError:
            pass
    return made


def apply_memory_proposal(p):
    """Carry out an approved memory_add / memory_merge / playbook_add."""
    if p["kind"] == "memory_add":
        full = vault_remember(p["line"])
        return f"✓ Remembered: {p['line']}{full}"
    if p["kind"] == "playbook_add":
        return "✓ " + _tool_playbook(p["arg"], "theta")
    remove = {r.lower() for r in p["remove"]}
    for attempt in (0, 1):
        text, sha = vault_read("Memory.md", fresh=True)
        kept = [l for l in text.splitlines() if not (l.startswith("- ") and l[2:].strip().lower() in remove)]
        new = "\n".join(kept).rstrip("\n") + f"\n- {p['add']}\n"
        try:
            vault_write("Memory.md", new, "Theta: merged memories", sha)
            return f"✓ Merged into: {p['add']}"
        except LLMError as e:
            if getattr(e, "status", None) in (409, 422) and attempt == 0:
                continue
            raise
    raise LLMError("the vault kept changing; try again")


def memory_upkeep(now=None):
    """Theta's round job for memory: the review each round, and once a week the
    fade and the merge offers. Returns what it did, for the round line."""
    if not vault_on():
        return []
    did, now = [], now or time.time()
    try:
        n = memory_review()
        if n:
            did.append(f"offered {n} thing{'s' if n != 1 else ''} to remember")
        if now - float(store().get_meta("mem:fade_at") or 0) >= 7 * 86400:
            store().set_meta("mem:fade_at", str(now))
            gone = memory_fade(now)
            if gone:
                did.append(f"moved {gone} unused memor{'ies' if gone != 1 else 'y'} to the archive")
            m = memory_merge_offers()
            if m:
                did.append(f"offered {m} memory merge{'s' if m != 1 else ''}")
    except LLMError as e:
        did.append(f"memory upkeep failed ({str(e)[:80]})")
    return did


# ---- /find <words>: search the chat the hub keeps and Memory.md, no model call.
FIND_SHOW = 8


def find_lines(arg):
    """Lines for /find: the newest matches first, chat then memory."""
    words = [w for w in arg.lower().split() if w]
    if not words:
        raise CommandError("Find what? Try /find dentist")
    hits = [m for m in store().list_chat(ALLCHAT_KEEP)
            if m.get("kind") != "event" and all(w in (m.get("text") or "").lower() for w in words)]
    out = []
    for m in reversed(hits[-FIND_SHOW:]):
        text = " ".join(m["text"].split())
        at = text.lower().find(words[0])
        snip = (("…" if at > 60 else "") + text[max(0, at - 60):at + 120] + ("…" if at + 120 < len(text) else ""))
        out.append(f"- {_chat_clock(m).strip()} {chat_name(m['from'])}: {snip}")
    mem = [l for l in memory_lines(vault_read("Memory.md")[0]) if all(w in l.lower() for w in words)] if vault_on() else []
    head = f"Found {len(hits)} message{'s' if len(hits) != 1 else ''} with “{arg.strip()}”"
    head += f" (newest {FIND_SHOW} shown)" if len(hits) > FIND_SHOW else ""
    lines = [head + ":" if hits else f"No messages with “{arg.strip()}” in the last {ALLCHAT_KEEP}."] + out
    if mem:
        lines += ["In your memory:"] + [f"- {l}" for l in mem[:5]]
    return lines


def _cmd_find(arg):
    lines = find_lines(arg)
    store().add_chat("theta" if head_on() else "hub", "\n".join(lines)[:4000])
    return lines[0]
