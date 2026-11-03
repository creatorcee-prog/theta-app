"""Background jobs (2026-11-03). Part of api/index.py, loaded INTO its namespace
by _load_part() (see store.py).

A reply has to finish in about 50 seconds (Vercel's limit), so a big job
(research and compare, plan the week, dig through something) doesn't fit in
one. Theta's background action saves the job and says so; the 5-minute tick
then works on it with the same tool loop as a reply, about 35 seconds a tick,
carrying the conversation over between ticks, until it's done. The result is
posted in the chat and pushed. /jobs lists them; /jobs cancel <n> stops one."""

JOB_MAX_ROUNDS = 24  # tool rounds over a job's whole life
JOB_MAX_TICKS = 12  # about an hour of ticks, then it answers with what it has
JOB_TICK_SECONDS = 35  # of the tick's time, per job chunk
JOBS_KEEP = 20
_JOB_LOCK = threading.Lock()
JOB_RULE = ("You're working on a background job the user handed you; they're not waiting on this screen. Work "
            "through it step by step with your tools (search, read pages, look things up) until it's really done. "
            "Then write the result for them: the answer first, short and scannable (they have ADD), with the "
            "sources you used as links. If something can't be done, say what you found and what's missing.")


def jobs():
    return _meta_json("jobs", [])


def _save_jobs(js):
    store().set_meta("jobs", json.dumps(js[-JOBS_KEEP:]))


def _tool_background(arg, agent):
    task = " ".join((arg or "").split())[:600]
    if not task:
        raise ValueError("what's the job?")
    with _JOB_LOCK:
        js = jobs()
        jid = max([j["id"] for j in js] + [0]) + 1
        js.append({"id": jid, "task": task, "status": "queued", "created": time.time(), "ticks": 0, "rounds": 0,
                   "msgs": [], "st": {"receipts": [], "buttons": [], "done": {}}})
        _save_jobs(js)
    post_event("theta", f"Theta started background job #{jid}: {task[:120]}")
    return f"Started background job #{jid}: {task[:120]}. I'll push you when it's done (it runs every few minutes)."


TOOLS["background"] = ("background | <the whole job, in plain words>   (for a job too big for one reply: research and "
                       "compare, plan something, go through a lot of pages. You'll work on it in the background and "
                       "push the user the result. Use it instead of a half answer.)", _tool_background, {"theta"})


def _job_messages(job):
    allowed = head_tools() - {"background"}
    msgs = job["msgs"] or [
        {"role": "system", "content": head_system(native=True)},
        {"role": "system", "content": now_line() + "\n\n" + JOB_RULE},
        {"role": "user", "content": f"The job (background job #{job['id']}): {job['task']}"}]
    return msgs, allowed


def _job_slim(msgs):
    """What's kept between ticks: tool results cut to 2500 characters."""
    return [dict(m, content=(m.get("content") or "")[:2500]) if m["role"] == "tool" else m for m in msgs]


def run_job_chunk(job, now=None, seconds=JOB_TICK_SECONDS):
    """Work on one job for up to `seconds`. Returns the job (updated)."""
    msgs, allowed = _job_messages(job)
    tools = tool_schemas(allowed)
    st = job.get("st") or {"receipts": [], "buttons": [], "done": {}}
    before = sum(1 for m in msgs if m["role"] == "assistant")
    last_tick = job["ticks"] + 1 >= JOB_MAX_TICKS
    steps = max(0, JOB_MAX_ROUNDS - job["rounds"])
    saved = getattr(_REQ, "deadline", None)
    _REQ.deadline = time.time() + seconds
    try:
        text = tool_rounds(msgs, tools, allowed, 900, steps, st, must_finish=last_tick or steps == 0, reserve=20)
    finally:
        _REQ.deadline = saved
    job.update(msgs=_job_slim(msgs), st=st, ticks=job["ticks"] + 1, status="running",
               rounds=job["rounds"] + sum(1 for m in msgs if m["role"] == "assistant") - before)
    if text is None:
        return job  # more next tick
    text = text.strip() or "I worked on it but couldn't pull a result together."
    out = f"Background job #{job['id']} is done: {job['task'][:120]}\n\n{text}"
    if st["receipts"]:
        out += "\n\n" + "\n".join(st["receipts"])
    store().add_chat("theta", out[:4000])
    notify("Theta", f"Done: {job['task'][:80]}", HEAD_PLAY_URL)
    job.update(status="done", result=text[:2000], finished=time.time(), msgs=[])
    return job


def jobs_tick(now=None, seconds=JOB_TICK_SECONDS):
    """From the tick: one chunk of the oldest unfinished job, in what's left of
    the tick's time (Vercel stops a request at 60 s)."""
    if seconds < 15:
        return None
    with _JOB_LOCK:
        js = jobs()
        job = next((j for j in js if j["status"] in ("queued", "running")), None)
        if not job:
            return None
        job["status"] = "running"
        job["claimed"] = time.time()
        _save_jobs(js)
    try:
        job = run_job_chunk(job, now, seconds)
    except LLMError as e:
        job["fails"] = job.get("fails", 0) + 1
        if job["fails"] >= 3:
            job.update(status="failed", result=str(e)[:300], msgs=[])
            store().add_chat("theta", f"Background job #{job['id']} didn't work out: {str(e)[:200]}")
            notify("Theta", f"Couldn't finish: {job['task'][:80]}", HEAD_PLAY_URL)
    with _JOB_LOCK:
        js = [job if j["id"] == job["id"] and j["status"] != "cancelled" else j for j in jobs()]
        _save_jobs(js)
    return job["status"]


def _cmd_jobs(arg):
    words = arg.split()
    if words[:1] == ["cancel"] and len(words) > 1 and words[1].lstrip("#").isdigit():
        jid = int(words[1].lstrip("#"))
        with _JOB_LOCK:
            js = jobs()
            hit = next((j for j in js if j["id"] == jid), None)
            if not hit:
                raise CommandError(f"There's no background job #{jid}.")
            hit.update(status="cancelled", msgs=[])
            _save_jobs(js)
        store().add_chat("theta", f"Cancelled background job #{jid}.")
        return f"Cancelled #{jid}."
    js = jobs()[-8:]
    if not js:
        text = "No background jobs. Ask me for something big (\"research and compare...\") and I'll run it in the background."
    else:
        label = {"queued": "waiting", "running": "working on it", "done": "done", "failed": "failed", "cancelled": "cancelled"}
        text = "Background jobs:\n" + "\n".join(f"- #{j['id']} {j['task'][:80]}: {label.get(j['status'], j['status'])}"
                                                for j in reversed(js))
    store().add_chat("theta", text)
    return text.split("\n")[0]


COMMANDS[-1:-1] = [{"name": "jobs", "args": "[cancel <number>]", "about": "Theta's background jobs, or stop one", "run": _cmd_jobs}]
