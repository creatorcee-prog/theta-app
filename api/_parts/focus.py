"""Help for an ADD brain (Stage 9). Part of api/index.py, loaded INTO its
namespace by _load_part() (see store.py).

- Sleep: once a night, while you've been quiet for a while, Theta tidies
  its memory (the same review, fade and merge offers as the rounds) and
  "dreams": it reads what it knows about you, the week's chat, your
  calendar and your budget, comes up with ideas, scores them, and keeps the
  best one or two as Keep / No cards. Your answers steer later dreams.
  This copies the shape of Google's sleep research (consolidate, then
  generate and keep what helps), not the method: that retrains the model,
  and the model here is rented.
- Leave nudges: a push before each timed calendar event, earlier when the
  event has a place to get to.
- Focus (body double): "/focus 25 taxes": Theta checks in every few
  minutes until the time's up.
- /break: a stuck task as 3 tiny steps, the first under 2 minutes.
- /dump: a messy brain dump sorted into reminders, spending, notes and
  memories (memories still wait for your Approve).
- The Sunday reset (the weekly review in rounds.py) gets the week's focus
  sessions and kept dreams as facts."""

SLEEP_HOUR = int(os.environ.get("SLEEP_HOUR", "3") or 3)  # hub time; Theta sleeps in the 3 hours from here
SLEEP_IDLE_HOURS = 2  # you've been quiet this long, or Theta skips the night
DREAM_KEEP = 2  # ideas kept a night, at most
DREAM_MIN_SCORE = 6  # out of 10, Theta's own score
EVENT_NUDGE_MINUTES = int(os.environ.get("EVENT_NUDGE_MINUTES", "15") or 15)
EVENT_TRAVEL_MINUTES = int(os.environ.get("EVENT_TRAVEL_MINUTES", "20") or 20)  # extra for an event with a place
FOCUS_DEFAULT = 25
FOCUS_CHECK_MINUTES = 10
NUDGE_URL = "/calendar#soon"
FOCUS_URL = "/head?play=latest&focus=1"
_FOCUS_LOCK = threading.Lock()


def _chat_ts(m):
    return datetime.strptime(m["at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


def last_you_at():
    """When you last sent a message (0 if never)."""
    for m in reversed(store().list_chat(ALLCHAT_KEEP)):
        if m["from"] == "you":
            return _chat_ts(m)
    return 0


# ---- Sleep and dreams
def sleep_due(now):
    local = datetime.fromtimestamp(now, hub_tz())
    if not SLEEP_HOUR <= local.hour < SLEEP_HOUR + 3:
        return False
    if store().get_meta("sleep:day") == local.date().isoformat():
        return False
    return now - last_you_at() >= SLEEP_IDLE_HOURS * 3600 and not user_typing()


def dream_taste():
    return _meta_json("dream:taste", [])


def _dream_context(now):
    st = store()
    parts = []
    if vault_on():
        mem = memory_lines(vault_read("Memory.md")[0])
        if mem:
            parts.append("What you know about the user:\n" + "\n".join(f"- {l}" for l in mem[:60]))
    since = now - 3 * 86400
    talk = [m for m in st.list_chat(ALLCHAT_KEEP)
            if m.get("kind") != "event" and m["from"] in ("you", "theta") and _chat_ts(m) >= since]
    if talk:
        parts.append("The last 3 days of chat:\n" + "\n".join(chat_line(m)[:300] for m in talk[-50:]))
    today = datetime.fromtimestamp(now, hub_tz()).date()
    if calendar_linked():
        ev = calendar_events(today, today + timedelta(days=6))
        if ev:
            parts.append("The next 7 days:\n" + "\n".join(f"- {occurrence_text(o, with_day=True)}" for o in ev[:25]))
    money = status_lines(today.strftime("%Y-%m"))
    if money:
        parts.append("Budgets this month:\n" + "\n".join(f"- {x}" for x in money))
    if not parts:
        return ""
    taste = dream_taste()[-10:]
    if taste:
        parts.append("Past ideas and what the user said (do more like the kept ones, none like the declined):\n"
                     + "\n".join(f"- {'kept' if t['kept'] else 'declined'}: {t['idea']}" for t in taste))
    return "\n\n".join(parts)


def dream(now=None):
    """Come up with ideas from what Theta knows, keep the best, post them as
    Keep / No cards. Returns the ideas kept."""
    now = now or time.time()
    ctx = _dream_context(now)
    if not ctx:
        return []
    try:
        got = _json_in(head_chat([{"role": "user", "content": (
            "It's night and the user is asleep. You're Theta, their assistant, and this is your dreaming time: "
            "mix what you know about them from different days and places into new ideas that would help them. "
            "Good ideas: a connection between two things they said on different days; one small step toward "
            "something they want; something to get ready for a coming event; a fix for something that keeps "
            "slipping. The user has ADD: each idea is 1 or 2 short, concrete sentences they could act on today. "
            "Use only the facts below; never invent events, people or numbers. Come up with 5, then score each "
            "1-10 for how useful and new it would be to them (be strict: most ideas are a 4 or 5).\n"
            'Reply with JSON only: [{"idea": "...", "from": "the facts it comes from, briefly", "score": 7}]\n\n'
            + ctx)}], 700))
    except LLMError:
        return []
    ideas = []
    for d in got if isinstance(got, list) else []:
        try:
            idea, score = " ".join(str(d["idea"]).split())[:300], float(d.get("score", 0))
        except (KeyError, TypeError, ValueError):
            continue
        try:
            memory_check(idea)
        except ValueError:
            continue
        if idea and score >= DREAM_MIN_SCORE:
            ideas.append((score, idea, " ".join(str(d.get("from") or "").split())[:200]))
    ideas.sort(key=lambda x: -x[0])
    kept = []
    for _score, idea, src in ideas[:DREAM_KEEP]:
        propose_to_user({"kind": "dream", "idea": idea, "summary": f"Dream: {idea}"},
                        f"💭 An idea from last night:\n{idea}" + (f"\n(From: {src})" if src else "") + "\nKeep it?",
                        labels=("Keep", "No"))
        kept.append(idea)
    return kept


def dream_feedback(p, kept):
    """Your Keep / No on a dream: remembered to steer later dreams; a kept one
    is saved to Theta/Dreams.md in the vault (or a note without it)."""
    with _TOOL_LOCK:
        taste = dream_taste() + [{"idea": p["idea"], "kept": kept, "at": time.time()}]
        store().set_meta("dream:taste", json.dumps(taste[-30:]))
    if not kept:
        return f"Okay, not that one. I'll dream less like it: {p['idea']}"
    day = datetime.now(hub_tz()).date().isoformat()
    if vault_on():
        vault_append("Dreams.md", f"- {day}: {p['idea']}", "Theta: kept a dream")
        return f"✓ Kept in Dreams.md: {p['idea']}"
    _tool_note(f"Idea {day} :: {p['idea']}", "theta")
    return f"✓ Kept as a note: {p['idea']}"


def run_sleep(now=None):
    """From the tick: Theta's night. Returns what it did, or None when it
    isn't time (or you're up)."""
    now = now or time.time()
    if not sleep_due(now):
        return None
    st = store()
    day = datetime.fromtimestamp(now, hub_tz()).date().isoformat()
    st.set_meta("sleep:day", day)  # claimed first: a slow model can't run the night twice
    did = list(memory_upkeep(now))
    ideas = dream(now)
    if ideas:
        did.append(f"dreamed up {len(ideas)} idea{'s' if len(ideas) != 1 else ''}")
    st.set_meta("sleep:last", json.dumps({"day": day, "did": did, "dreams": ideas}))
    if did:
        post_event("theta", "Theta slept: " + ", ".join(did))
    return did


def sleep_facts(today):
    """Last night's sleep, for the morning brief."""
    last = _meta_json("sleep:last", {})
    if last.get("day") != today.isoformat() or not last.get("dreams"):
        return []
    return ["Ideas Theta had overnight (waiting for Keep or No in the chat): " + " | ".join(last["dreams"])]


# ---- Leave nudges: a push before each timed event
def event_nudges(now=None):
    """From the tick. Returns the nudges sent."""
    if not REMI_CALENDAR_URLS:
        return []
    now = now or time.time()
    today = datetime.fromtimestamp(now, hub_tz()).date()
    sent = {k: v for k, v in _meta_json("nudge:events", {}).items() if v > now - 2 * 86400}
    out = []
    for o in calendar_events(today, today + timedelta(days=1)):
        if o["all_day"] or o["birthday"]:
            continue
        travel = EVENT_TRAVEL_MINUTES if o["location"] else 0
        mins = (o["start"].timestamp() - now) / 60
        key = f"{o['title']}|{o['start'].isoformat()}"
        if not 0 < mins <= EVENT_NUDGE_MINUTES + travel or key in sent:
            continue
        if travel:
            leave = max(0, round(mins - travel))
            text = (f"{o['title']} is at {_clock(o['start'])} ({o['location']}). "
                    + (f"Leave in about {leave} min." if leave else "Time to leave."))
        else:
            text = f"{o['title']} starts in {max(1, round(mins))} min, at {_clock(o['start'])}."
        notify("Remi", text, NUDGE_URL)
        sent[key] = now
        out.append(text)
    if out:
        store().set_meta("nudge:events", json.dumps(sent))
    return out


# ---- Focus: Theta as a body double
def focus_state():
    return _meta_json("focus", {})


def focus_start(arg, now=None):
    """/focus [minutes] <task>, or /focus stop. Returns Theta's line."""
    now = now or time.time()
    arg = " ".join((arg or "").split())
    if arg.lower() in ("stop", "done", "end", "off", "cancel"):
        return focus_stop(now)
    m = re.match(r"^(?:for\s+)?(\d{1,3})\s*(?:m|min|mins|minutes?)?\b\s*(?:on\s+|of\s+)?(.*)$", arg, re.I)
    minutes, task = (int(m.group(1)), m.group(2).strip()) if m else (FOCUS_DEFAULT, arg)
    minutes = max(5, min(minutes, 120))
    task = task[:120] or "your task"
    every = FOCUS_CHECK_MINUTES if minutes > 15 else max(2, minutes // 2)
    with _FOCUS_LOCK:
        store().set_meta("focus", json.dumps({"task": task, "start": now, "until": now + minutes * 60,
                                              "every": every, "next": now + every * 60, "minutes": minutes}))
    return (f"Okay, {minutes} minutes on {task}. I'm right here with you. I'll check in every {every} minutes. "
            "Start with the smallest piece.")


def focus_stop(now=None, finished=False):
    now = now or time.time()
    with _FOCUS_LOCK:
        f = focus_state()
        if not f:
            return "There's no focus session going. Start one with /focus 25 and what you're working on."
        store().set_meta("focus", "{}")
        done = round((min(now, f["until"]) - f["start"]) / 60)
        log = [x for x in _meta_json("focus:log", []) if x["at"] > now - 30 * 86400]
        store().set_meta("focus:log", json.dumps(log + [{"task": f["task"], "minutes": done, "at": now}]))
    if finished:
        return f"Time's up on {f['task']}: {done} minutes done. Nice. Take a 5 minute break. How did it go?"
    return f"Stopped: {done} minutes on {f['task']}. That still counts."


def focus_tick(now=None):
    """From the tick: the check-ins and the end. Returns what was said, or None."""
    now = now or time.time()
    f = focus_state()
    if not f:
        return None
    if now >= f["until"]:
        text = focus_stop(now, finished=True)
    elif now >= f["next"]:
        left = max(1, round((f["until"] - now) / 60))
        text = f"Still on {f['task']}? {left} minute{'s' if left != 1 else ''} to go. You've got this."
        with _FOCUS_LOCK:
            cur = focus_state()
            if cur.get("start") != f["start"]:
                return None
            cur["next"] = now + cur["every"] * 60
            store().set_meta("focus", json.dumps(cur))
    else:
        return None
    store().add_chat("theta", text)
    notify("Theta", text, FOCUS_URL)
    return text


def focus_week(today):
    """The week's focus sessions, for the Sunday reset."""
    since = datetime.combine(today - timedelta(days=6), datetime.min.time(), hub_tz()).timestamp()
    log = [x for x in _meta_json("focus:log", []) if x["at"] >= since]
    if not log:
        return []
    return [f"Focus sessions this week: {len(log)}, {sum(x['minutes'] for x in log)} minutes "
            f"({', '.join(sorted({x['task'] for x in log}))[:200]})"]


def _tool_focus(arg, agent):
    return focus_start(arg)


TOOLS["focus"] = ("focus | <minutes> <task>, or stop   (sit with the user while they work: you check in every few "
                  "minutes until the time's up)", _tool_focus, {"theta"})


def _cmd_focus(arg):
    text = focus_start(arg)
    store().add_chat("theta", text)
    return text


# ---- /break: 3 tiny steps
def break_steps(task):
    task = " ".join((task or "").split())[:300]
    if not task:
        raise CommandError("Break down what? Try /break do my taxes")
    try:
        got = _json_in(head_chat([{"role": "user", "content": (
            "The user has ADD and is stuck starting this: " + task + "\nBreak it into exactly 3 tiny steps. Step 1 "
            "must take under 2 minutes and need no decisions (like: open the folder, put the form on the table). "
            'Each step under 12 words. Reply with JSON only: ["step 1", "step 2", "step 3"]')}], 300))
    except LLMError as e:
        raise CommandError(str(e))
    steps = [" ".join(str(s).split())[:120] for s in got if str(s).strip()][:3] if isinstance(got, list) else []
    if not steps:
        raise CommandError("I couldn't break that down just now. Try again in a minute?")
    return task, steps


def _cmd_break(arg):
    task, steps = break_steps(arg)
    text = (f"Let's start on {task}:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
            + f"\nJust do step 1 now. Want company? /focus 25 {task}")
    store().add_chat("theta", text)
    return f"Step 1: {steps[0]}"


# ---- /dump: a brain dump, sorted
def brain_dump(text):
    """Sort a brain dump; returns the lines saying what went where."""
    text = " ".join((text or "").split())[:3000]
    if not text:
        raise CommandError("Dump what? Type or say everything on your mind after /dump")
    now = datetime.now(hub_tz())
    try:
        got = _json_in(head_chat([{"role": "user", "content": (
            f"It's {now:%A %B %d, %I:%M %p}. Sort the user's brain dump into JSON only:\n"
            '{"reminders": ["when and what, like tomorrow 9am call the dentist"], "spend": ["$42 groceries"], '
            '"todo": ["things to do with no time given"], "remember": ["lasting facts about the user"], '
            '"ideas": ["ideas and anything else"]}\n'
            "Only what they said; a reminder needs a time they gave (otherwise it's a todo); never secrets.\n\n"
            "The dump:\n" + text)}], 700))
    except LLMError as e:
        raise CommandError(str(e))
    if not isinstance(got, dict):
        raise CommandError("I couldn't sort that just now. Try again in a minute?")
    pick = lambda k: [" ".join(str(x).split())[:200] for x in (got.get(k) or []) if str(x).strip()][:10]
    out, todo = [], pick("todo")
    for r in pick("reminders"):
        try:
            out.append("⏰ " + _tool_remind(r, "theta"))
        except ValueError:
            todo.append(r)
    for s in pick("spend"):
        try:
            out.append("💵 " + _tool_spend(s, "theta"))
        except ValueError:
            todo.append(s)
    if todo:
        _tool_note(f"To do ({now:%b} {now.day}) :: " + "\n".join(f"- {t}" for t in todo), "theta")
        out.append("📝 To do, saved as a note:\n" + "\n".join(f"- {t}" for t in todo))
    ideas = pick("ideas")
    if ideas:
        _tool_note(f"Ideas ({now:%b} {now.day}) :: " + "\n".join(f"- {t}" for t in ideas), "theta")
        out.append("💡 Ideas, saved as a note:\n" + "\n".join(f"- {t}" for t in ideas))
    for line in pick("remember")[:3]:
        try:
            memory_check(line)
        except ValueError:
            continue
        propose_to_user({"kind": "memory_add", "line": line, "summary": f"Remember: {line}"},
                        f"From your dump, worth remembering?\n- {line}")
        out.append(f"🧠 Asked to remember: {line}")
    return out


def _cmd_dump(arg):
    out = brain_dump(arg)
    text = ("Got it all. Here's where it went:\n" + "\n".join(out)) if out else "I didn't find anything to sort in that."
    store().add_chat("theta", text[:4000])
    return f"Sorted your dump into {len(out)} thing{'s' if len(out) != 1 else ''}."


COMMANDS[-1:-1] = [  # before /help
    {"name": "focus", "args": "[minutes] <task> | stop", "about": "Theta works alongside you and checks in", "run": _cmd_focus},
    {"name": "break", "args": "<task>", "about": "Theta splits a stuck task into 3 tiny steps", "run": _cmd_break},
    {"name": "dump", "args": "<everything on your mind>", "about": "Theta sorts it into reminders, spending, notes and memory", "run": _cmd_dump},
]
