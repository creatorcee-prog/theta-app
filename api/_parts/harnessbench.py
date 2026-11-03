"""Harness test (Diagnostics): the same messages through Theta's old harness
(ACTION lines, 3 actions, no writing rule) and the new one (native tool
calling, 6 rounds, the writing rule), on the real model with the real keys.
Part of api/index.py, loaded INTO its namespace by _load_part() (see store.py).

Nothing real changes: while it runs, tools that change things (remind, spend,
note, ...) only record what they were asked to do, and the web lookups return
a fixed page, so the test measures the harness, not the search engine. Read-
only lookups (calendar, budget, tasks) run for real. Each run is one message
one way (Vercel's 60 s), so the Diagnostics page asks for them in turn."""

HB_CASES = [  # id, message, tools it should use {name: words its input should have}, what it checks
    ("chat", "hey, how's it going?", {}, "Small talk: no tools"),
    ("money", "how much have I spent this month?", {"budget": ""}, "Looks up the budget"),
    ("remind", "make sure I call the bank tomorrow at 9am", {"remind": "bank"}, "Sets one reminder"),
    ("multi", "check my budget, then set a reminder for 6pm to pay rent, and log $12 for lunch",
     {"budget": "", "remind": "rent", "spend": "12"}, "Three steps in one ask"),
    ("dump", "brain dump: dentist thursday at 3pm, buy milk, and I spent $40 on gas",
     {"remind": "dentist", "spend": "40", "note": "milk"}, "Sorts a brain dump"),
    ("search", "who won the last Broncos game?", {"web_search": ""}, "Searches the web"),
    # harder: more than 3 actions, an input that fails first, and look-then-decide
    ("five", "set reminders for 7am gym, noon lunch with Sam, 3pm call the dentist, 6pm pay rent and 9pm stretch",
     {"remind": ["gym", "sam", "dentist", "rent", "stretch"]}, "Five actions in one ask"),
    ("unclear", "set a reminder to call mom", "ask_or_remind:mom", "No time given: asks, or picks one that works"),
    ("decide", "if I've spent more than $50 on dining this month, remind me to cook at 6pm tonight; "
               "otherwise just tell me what I've spent on dining", "decide_dining", "Looks, then decides"),
]
HB_MODES = (("old", "Old harness"), ("new", "New harness"))
_HB_FAKE_WEB = ("Search results (test page): 1. Example Sports: The Broncos beat the Chiefs 24-20 on Sunday. "
                "https://example.com/broncos")
_HB_SIGNS = re.compile(
    r"\b(delve|crucial|pivotal|tapestry|testament|intricate|underscores?|showcases?|enduring|garner|meticulous|robust|"
    r"interplay|additionally|boasts|leverage|multifaceted|vibrant|seamless|realm|elevate|foster|empower|unlock|"
    r"embark|nestled|serves as|stands as|not only|i hope this helps|great question|certainly!|absolutely right|"
    r"in summary|in conclusion|overall,|feel free)\b|—", re.I)


def hb_signs(text):
    """The signs of AI writing found in a reply (words, phrases, em dashes)."""
    return [m.group(0).lower() for m in _HB_SIGNS.finditer(text or "")]


def hb_tool(name, arg):
    """run_tool's stand-in while the test runs: (ok, text, buttons) or None to run for real."""
    calls = getattr(_REQ, "hb_calls", None)
    if calls is None:
        return None
    calls.append((name.lower(), arg))
    if name.lower() in ("web_search", "fetch_page"):
        return True, _HB_FAKE_WEB, []
    if name.lower() in HEAD_LOOKUPS:
        return None  # read-only: the real thing
    try:  # checked the way the real tool checks it, so a bad input fails like it would for real
        if name.lower() == "remind":
            parse_reminder(arg)
        elif name.lower() == "spend" and not parse_expense(arg if "$" in arg else "$" + arg):
            raise ValueError("couldn't read an amount (like $42 groceries)")
    except ValueError as e:
        calls[-1] = (name.lower(), arg, False)
        return False, f"{name}: {str(e)[:200]}", []
    return True, f"(test, nothing saved) {name}: {arg[:80]}", []


def hb_score(calls, want, reply=""):
    """(ok, what's missing). want: {tool: words (or a list: one call each)} that
    must have worked, or a named check for the harder cases."""
    good = [(c[0], c[1]) for c in calls if len(c) < 3 or c[2]]  # the calls that worked
    has = lambda n, w: any(c == n and (not w or w.lower() in a.lower()) for c, a in good)
    if want == "decide_dining":
        dining = sum(v["spent"] for c, v in month_status().items() if "dining" in c.lower() or "restaurant" in c.lower())
        if not any(c == "budget" for c, _ in good):
            return False, ["budget (it didn't look)"]
        if dining > 50:
            return (True, []) if has("remind", "cook") else (False, [f"remind (dining is ${dining:,.0f})"])
        return (False, [f"set a reminder anyway (dining is ${dining:,.0f})"]) if has("remind", "") else (True, [])
    if isinstance(want, str) and want.startswith("ask_or_remind:"):
        word = want.split(":", 1)[1]
        said = "\n".join(l for l in reply.splitlines() if not l.lstrip().startswith(("\u2713", "\u2717")))  # not the receipts
        if has("remind", word) or ("?" in said and not any(c == "remind" for c, _ in good)):
            return True, []
        return False, ["a working reminder, or a question about the time"]
    if not want and calls:
        return False, ["used tools on small talk"]
    missing = []
    for n, words in want.items():
        for w in (words if isinstance(words, list) else [words]):
            if not has(n, w):
                missing.append(f"{n} {w}".strip())
    return not missing, missing


def hb_run(case_id, mode):
    """One message one way. Returns the row."""
    case = next((c for c in HB_CASES if c[0] == case_id), None)
    if not case or mode not in dict(HB_MODES):
        raise ValueError("unknown case or mode")
    _, text, want, about = case
    thread = [{"id": 0, "from": "you", "text": text, "kind": "message", "at": _now()}]
    _REQ.hb_calls, _REQ.hb_old = [], mode == "old"
    _REQ.tok, _REQ.hb_model_calls = [0, 0], 0
    _REQ.deadline = time.time() + 48
    t0 = time.time()
    row = {"case": case_id, "mode": mode, "about": about, "q": text}
    try:
        got = head_reply_text(thread) if mode == "old" else head_reply_native(thread)
        reply = got["text"] if isinstance(got, dict) else got
        ok, missing = hb_score(_REQ.hb_calls, want, reply)
        row.update(ok=ok, missing=missing, reply=reply[:900], signs=hb_signs(reply), words=len(reply.split()))
    except Exception as e:
        row.update(ok=False, error=_bench_error(e), missing=[], signs=[], words=0, reply="")
    finally:
        row.update(secs=round(time.time() - t0, 1),
                   calls=[f"{c[0]}: {c[1][:60]}" + (" (failed)" if len(c) > 2 and not c[2] else "") for c in _REQ.hb_calls],
                   model_calls=getattr(_REQ, "hb_model_calls", 0), tokens=sum(getattr(_REQ, "tok", [0, 0])))
        _REQ.hb_calls = None
        _REQ.hb_old = False
        _REQ.deadline = None
    saved = _meta_json("hbench:last", {})
    rows = {r["case"] + ":" + r["mode"]: r for r in saved.get("rows", [])}
    rows[case_id + ":" + mode] = row
    store().set_meta("hbench:last", json.dumps({"at": time.time(), "rows": list(rows.values())}))
    return row


def prompt_sizes():
    """Rough tokens (characters / 4) of what each harness sends before the model
    answers, with the real data: the instructions, the chat so far, the tools."""
    thread = store().list_chat(CHAT_HISTORY)
    tok = lambda s: len(s) // 4
    old_sys = head_system() + now_line()
    new_sys = head_system(native=True) + now_line() + head_glance()
    old_chat = "\n".join(chat_line(m) for m in thread[-CHAT_HISTORY:])
    new_chat = head_transcript(thread) if thread else ""
    tools = json.dumps(tool_schemas(head_tools()))
    return {"old": {"instructions": tok(old_sys), "chat": tok(old_chat), "tools": 0, "total": tok(old_sys + old_chat)},
            "new": {"instructions": tok(new_sys), "chat": tok(new_chat), "tools": tok(tools),
                    "total": tok(new_sys + new_chat + tools)}}


def hb_totals(rows):
    """Per mode: passed, average seconds, model calls, tokens, AI-writing signs."""
    out = {}
    for mode, _ in HB_MODES:
        rs = [r for r in rows if r["mode"] == mode]
        if rs:
            out[mode] = {"passed": sum(1 for r in rs if r.get("ok")), "of": len(rs),
                         "secs": round(sum(r["secs"] for r in rs) / len(rs), 1),
                         "model_calls": sum(r.get("model_calls", 0) for r in rs),
                         "tokens": sum(r.get("tokens", 0) for r in rs),
                         "signs": sum(len(r.get("signs", [])) for r in rs)}
    return out


def harness_card():
    cases = json.dumps([c[0] for c in HB_CASES])
    return ('<section class="card stack" id="hbench" style="margin-top:14px"><h2>Harness test</h2>'
            '<p class="muted small">The same messages through Theta’s old harness (ACTION lines, 3 actions, no writing '
            'rule) and the new one (real tool calls, up to 6 rounds, the writing rule), on the real model. Nothing gets '
            'saved: actions are only recorded, and web searches return a fixed test page. About 18 model answers, a few '
            'cents on DeepSeek; it takes two or three minutes.</p>'
            '<p><button type="button" class="btn" id="hb-run">Run the test</button> <span class="note" id="hb-note"></span></p>'
            '<style>#hbench .hbr{padding:10px 0;border-top:1px solid var(--line,rgba(127,127,127,.25))}'
            '#hbench .hbp{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:6px}#hbench .hbc{min-width:0;overflow-wrap:anywhere}'
            '#hbench details{margin-top:4px}</style><div id="hb-out"></div>'
            '<script>(()=>{const H=window.THETA_H,out=document.getElementById("hb-out"),note=document.getElementById("hb-note"),'
            f'btn=document.getElementById("hb-run"),CASES={cases},MODES=["old","new"];'
            'const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;"}[c]));'
            'function cell(r,label){if(!r)return`<div class="hbc"><span class="muted small">${label}</span><div class="muted">not run</div></div>`;'
            'const t=(r.ok?"\u2713":"\u2717")+" "+r.secs+"s \u00b7 "+r.model_calls+" calls"+(r.signs&&r.signs.length?" \u00b7 "+r.signs.length+" AI signs":"");'
            'const why=r.error||((r.missing||[]).length?"missed: "+r.missing.join(", "):"")||"";'
            'return`<div class="hbc"><span class="muted small">${label}</span><div style="font-weight:700;color:${r.ok?"var(--good)":"var(--bad,#d33)"}">${esc(t)}</div>`'
            '+(why?`<div class="muted small">${esc(why)}</div>`:"")+`<details class="small"><summary>reply</summary>${esc(r.reply)}'
            '${(r.calls||[]).length?`<div class="muted">Tools: ${esc(r.calls.join("; "))}</div>`:""}</details></div>`;}'
            'function render(d){const rows=d.rows||[];if(!rows.length){out.innerHTML="";return;}const by={};rows.forEach(r=>by[r.case+":"+r.mode]=r);'
            'const S=d.sizes;const sz=S?`<div class="hbr"><b>Prompt size per model call</b> <span class="muted small">(rough tokens, with your real data and chat)</span><div class="hbp">`'
            '+["old","new"].map(m=>`<div class="hbc"><span class="muted small">${m==="old"?"Old":"New"}</span><div>~${S[m].total.toLocaleString()} tokens</div>'
            '<div class="muted small">instructions ${S[m].instructions.toLocaleString()} \u00b7 chat ${S[m].chat.toLocaleString()} \u00b7 tools ${S[m].tools.toLocaleString()}</div></div>`).join("")+`</div></div>`:"";'
            'const T=d.totals||{};const tot=m=>T[m]?`${T[m].passed}/${T[m].of} passed \u00b7 ${T[m].secs}s avg \u00b7 ${T[m].model_calls} calls \u00b7 ${T[m].tokens} tokens \u00b7 ${T[m].signs} AI signs`:"not run";'
            'out.innerHTML=sz+CASES.map(c=>{const r=by[c+":old"]||by[c+":new"];return`<div class="hbr"><b>${esc(r?r.about:c)}</b><div class="muted small">${esc(r?r.q:"")}</div>'
            '<div class="hbp">${cell(by[c+":old"],"Old")}${cell(by[c+":new"],"New")}</div></div>`;}).join("")'
            '+`<div class="hbr"><b>Total</b><div class="hbp"><div class="hbc"><span class="muted small">Old</span><div>${esc(tot("old"))}</div></div>'
            '<div class="hbc"><span class="muted small">New</span><div>${esc(tot("new"))}</div></div></div></div>`;}'
            'fetch("/api/hbench",{headers:H}).then(r=>r.json()).then(d=>{if(d.ok)render(d);}).catch(()=>{});'
            'btn.onclick=async()=>{btn.disabled=true;let n=0;for(const c of CASES)for(const m of MODES){n++;note.textContent=`Running ${n} of ${CASES.length*2}…`;'
            'try{const d=await(await fetch("/api/hbench",{method:"POST",headers:H,body:JSON.stringify({case:c,mode:m})})).json();if(d.ok)render(d);else note.textContent=d.error;}'
            'catch(e){note.textContent="Failed: "+e.message;}}note.textContent="Done.";btn.disabled=false;};})();</script></section>')
