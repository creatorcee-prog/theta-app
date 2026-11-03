"""Theta on the phone's Home Screen and in Shortcuts (Stage 9b). Part of
api/index.py, loaded INTO its namespace by _load_part() (see store.py).

A web app can't make an iPhone widget or see the rest of the phone, so two
free iPhone apps stand in:
- Scriptable draws a Home Screen widget (Theta's rings, its latest line,
  what's next) from GET /api/phone/widget. The script is
  api/_parts/theta-widget.js (Settings copies it); it refreshes when iOS lets it (about every 15
  minutes), not live.
- Shortcuts automations tell Theta what the phone knows (arrived at the
  gym, alarm stopped, Focus on) with POST /api/phone/event. Each lands in
  the chat as a quiet event Theta reads; "woke up" also sends the morning
  brief right then, if it hasn't gone out yet.
Both take the ASK_KEY header (x-ask-key), the key that can only ask, or a
signed-in browser."""

PHONE_EVENT_MAX = 200
_WAKE = re.compile(r"\b(woke|wake|awake|alarm (?:stopped|off|dismissed)|good morning|up now)\b", re.I)


def ask_key_ok(headers):
    return bool(ASK_KEY) and hmac.compare_digest(str(headers.get("x-ask-key") or ""), ASK_KEY)


def _short(text, n):
    text = " ".join(speakable(text or "").split())
    return text if len(text) <= n else text[:n - 1].rsplit(" ", 1)[0] + "…"


def phone_widget(now=None):
    """What the widget shows: Theta's latest line, the next event, focus,
    and what's waiting for you."""
    now = now or time.time()
    msgs = store().list_chat(ALLCHAT_KEEP)
    mine = [m for m in msgs if m["from"] == "theta" and m.get("kind") != "event"]
    last = mine[-1] if mine else None
    out = {"ok": True, "name": "Theta", "line": _short(last["text"], 140) if last else "Tap to talk to me.",
           "at": _clock(datetime.fromtimestamp(_chat_ts(last), hub_tz())) if last else "",
           "next": None, "focus": None, "waiting": 0, "reminders": 0, "url": "/head"}
    if calendar_linked():
        today = datetime.fromtimestamp(now, hub_tz()).date()
        soon = [o for o in calendar_events(today, today + timedelta(days=1))
                if not o["all_day"] and not o["birthday"] and o["start"].timestamp() > now]
        if soon:
            o = soon[0]
            day = "" if o["start"].date() == today else "Tomorrow "
            out["next"] = f"{day}{_clock(o['start'])} {o['title']}"[:60]
    f = focus_state()
    if f and f.get("until", 0) > now:
        left = max(1, round((f["until"] - now) / 60))
        out["focus"] = f"{f['task']}, {left} min left"[:60]
    out["waiting"] = sum(1 for p in proposals().values() if p.get("status") == "open" and p.get("by") == "theta")
    end = datetime.combine(datetime.fromtimestamp(now, hub_tz()).date() + timedelta(days=1),
                           datetime.min.time(), hub_tz()).timestamp()
    out["reminders"] = sum(1 for r in reminders() if r["at"] < end or r.get("pending"))
    return out


def phone_event(text, now=None):
    """A Shortcuts automation telling Theta something. Returns what Theta did."""
    text = " ".join(str(text or "").split())[:PHONE_EVENT_MAX]
    if not text:
        raise ValueError("event required, like: arrived at the gym")
    memory_check(text)  # nothing planted through a shortcut either
    post_event("you", f"📱 Phone: {text}")
    did = "noted"
    local = datetime.fromtimestamp(now or time.time(), hub_tz())
    if _WAKE.search(text) and local.hour >= 4:
        try:
            if send_digest(opener=False, now=local):
                did = "noted, and sent the morning brief"
        except Exception as e:  # the event is kept either way
            print(f"wake brief failed: {e!r}")
    return did


def widget_script(origin=""):
    """The widget's script, with this hub's address filled in (never a key)."""
    with open(os.path.join(_PARTS_DIR, "theta-widget.js"), encoding="utf-8") as fh:
        text = fh.read()
    return text.replace("__ORIGIN__", origin if re.match(r"^https://[\w.-]+$", origin or "") else "__ORIGIN__", 1)


# Shortcuts automations worth setting up: (when, the event Theta hears, why)
PHONE_AUTOMATIONS = [
    ("Alarm \u2192 Is Stopped", "woke up", "Theta sends the morning brief right then"),
    ("Arrive \u2192 Gym (pick the place)", "arrived at the gym", "Theta knows you're working out"),
    ("Leave \u2192 Home", "left home", "Theta knows you're out"),
    ("Focus \u2192 Work \u2192 Turns On", "work focus on", "Theta keeps it short"),
    ("Focus \u2192 Sleep \u2192 Turns On", "going to bed", "Theta knows the day is done"),
]


def phone_card(headers):
    origin = html.escape(_rp(headers)[1])
    autos = "".join(f"<li><b>{w}</b>: event <code>{html.escape(e)}</code> <span class=muted>({html.escape(why)})</span></li>"
                    for w, e, why in PHONE_AUTOMATIONS)
    return ('<section class="card stack" id="phone"><h2>Home Screen widget and automations</h2>'
            '<p class="muted small">A web app can\u2019t make a widget or see the rest of your phone, so two free apps stand in. '
            'Both use your <code>ASK_KEY</code> (set it in Vercel first: see Voice commands above).</p>'
            '<h3>Widget (Scriptable)</h3><ol class="small" style="margin:0;padding-left:1.2em;line-height:1.6">'
            '<li>Install <b>Scriptable</b> from the App Store (free).</li>'
            '<li>Tap <b>Copy the script</b> below. In Scriptable: <b>+</b>, paste, name it <b>Theta</b>, tap \u25B6 once.</li>'
            f'<li>It asks for your ASK_KEY (your address, <code>{origin}</code>, is already in it). Both stay in the iPhone\u2019s Keychain. Run it again any time to change them.</li>'
            '<li>Long-press the Home Screen \u2192 <b>+</b> \u2192 Scriptable \u2192 Small or Medium \u2192 Add Widget. Then hold it '
            '\u2192 Edit Widget \u2192 Script: <b>Theta</b>.</li></ol>'
            '<p class="muted small">It shows Theta\u2019s rings, its latest line, your next event and any focus session. Tapping it '
            'opens Theta. iOS refreshes it about every 15 minutes, not live.</p>'
            '<p><button type="button" class="btn" id="copy-widget">Copy the script</button> <span class="note" id="copy-note"></span></p>'
            '<h3 style="margin-top:6px">Automations (Shortcuts)</h3><ol class="small" style="margin:0;padding-left:1.2em;line-height:1.6">'
            '<li>Shortcuts \u2192 <b>Automation</b> \u2192 <b>+</b> \u2192 pick one below \u2192 <b>Run Immediately</b>.</li>'
            f'<li>Add <b>Get Contents of URL</b>: <code>{origin}/api/phone/event</code>, Method <b>POST</b>, Header '
            '<code>x-ask-key</code> = your ASK_KEY, Request Body <b>JSON</b> with <code>event</code> = the event text.</li></ol>'
            f'<ul class="small" style="margin:0;padding-left:1.2em;line-height:1.6">{autos}</ul>'
            '<p class="muted small">Each one shows in the chat as a quiet \U0001F4F1 line Theta reads: no reply, no cost.</p>'
            # fetched ahead: iPhone only lets a tap copy, with nothing awaited in between
            '<script>(()=>{let s="";fetch("/api/phone/script",{headers:window.THETA_H}).then(r=>r.text()).then(t=>s=t);'
            'document.getElementById("copy-widget").onclick=()=>{const n=document.getElementById("copy-note");'
            'if(!s){n.textContent="Still loading; tap again in a second.";return;}'
            'navigator.clipboard.writeText(s).then(()=>n.textContent="Copied. Paste it into Scriptable.",'
            'e=>n.textContent="Couldn\u2019t copy: "+e.message);};})();</script></section>')
