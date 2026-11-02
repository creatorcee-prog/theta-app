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
