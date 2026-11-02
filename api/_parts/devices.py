"""Devices and sessions.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Devices: each browser that signs in (key link or Face ID) gets its
# own random session cookie, so the hub knows every device and you can
# sign one out. The old login cookie held the key itself; a device still
# carrying it is moved to a session the next time it opens Theta (and
# listed then). Only a hash of each session token is stored.
SESSION_KEEP = 40
SESSION_IDLE_DAYS = 45
SESSION_SEEN_EVERY = 300  # seconds between "last seen" writes per device
_SESS_LOCK = threading.Lock()
_RT = threading.local()  # per round job thread: where that agent's posts go instead of the chat


def _round_capture(sender, text, kind, image, buttons):
    """During a round, an agent's chat posts go to Mistral (who posts one
    summary) instead of the chat. Posts with buttons stay, since Approve
    and the like only work on the agent's own message."""
    bucket = getattr(_RT, "capture", None)
    if bucket is None or kind != "message" or buttons or sender in ("mistral", "theta", "hub", "you"):
        return False
    bucket.append({"from": sender, "text": text, "image": image})
    return True


_REQ = threading.local()  # per request: cookies to set, session made


def _same(a, b):
    return bool(a) and bool(b) and hmac.compare_digest(str(a), str(b))


def _tok_hash(tok):
    return hashlib.sha256(str(tok).encode()).hexdigest()[:40]


def sessions():
    """{token hash: device} for every signed-in browser."""
    return _meta_json("sessions", {})


def device_label(ua):
    """'iPhone · Home Screen app', 'Mac · Chrome' and so on, from a user agent."""
    ua = ua or ""
    if not ua:
        return "Unknown device"
    if re.search(r"curl|python|wget|go-http|node-fetch|axios|okhttp", ua, re.I):
        return f"Script ({ua.split('/')[0][:30]})"
    dev = ("iPhone" if "iPhone" in ua else "iPad" if "iPad" in ua else "Android" if "Android" in ua else
           "Mac" if "Macintosh" in ua else "Windows PC" if "Windows" in ua else "Chromebook" if "CrOS" in ua else
           "Linux" if "Linux" in ua else "Device")
    if dev == "Android":
        m = re.search(r"Android [\d.]+; ([^;)]+?)(?: Build|\))", ua)
        if m and m.group(1).strip() not in ("K", "wv"):
            dev += f" ({m.group(1).strip()[:30]})"
    app = ("Edge" if re.search(r"Edg[AiOS]*/", ua) else "Opera" if re.search(r"OPR/|OPX/|Opera", ua) else
           "Chrome" if re.search(r"CriOS/|Chrome/", ua) else "Firefox" if re.search(r"FxiOS/|Firefox/", ua) else
           "Shortcuts" if re.search(r"Shortcuts|CFNetwork|Siri", ua) else "Safari" if "Safari/" in ua else
           "Home Screen app" if dev in ("iPhone", "iPad") and "Mobile/" in ua else "browser")
    return f"{dev} · {app}"


def device_os(ua):
    """'iOS 26.1', 'Android 15', 'Windows', 'macOS' from a user agent, or ''."""
    ua = ua or ""
    m = re.search(r"(?:iPhone|CPU) OS (\d+)[_.](\d+)", ua)
    if m:
        return f"{'iPadOS' if 'iPad' in ua else 'iOS'} {m.group(1)}.{m.group(2)}"
    m = re.search(r"Android (\d+(?:\.\d+)?)", ua)
    if m:
        return f"Android {m.group(1)}"
    return ("macOS" if "Macintosh" in ua else "Windows" if "Windows" in ua else "ChromeOS" if "CrOS" in ua
            else "Linux" if "Linux" in ua else "")


def _place(headers):
    """Rough location from Vercel's IP headers (city, region, country), or ''."""
    from urllib.parse import unquote
    parts = [unquote(headers.get(h) or "").strip() for h in
             ("x-vercel-ip-city", "x-vercel-ip-country-region", "x-vercel-ip-country")]
    return ", ".join(p for p in parts if p)[:80]


def _ip(headers):
    fwd = headers.get("x-forwarded-for") or headers.get("x-real-ip") or ""
    return fwd.split(",")[0].strip()[:64]


def _set_cookie(name, value, max_age=31536000):
    _cookies().append(("Set-Cookie", f"{name}={value}; Path=/; Max-Age={max_age}; HttpOnly; Secure; SameSite=Lax"))


def _cookies():
    if not hasattr(_REQ, "cookies"):
        _REQ.cookies = []
    return _REQ.cookies


def new_session(headers, how):
    """Sign this browser in: a fresh session cookie, recorded as a device.
    Tells you (phone push and a QWERTY note) about every new sign-in."""
    if getattr(_REQ, "session", None):
        return _REQ.session
    tok = _b64u(os.urandom(32))
    now = time.time()
    dev = {"id": hashlib.sha256(tok.encode() + b"id").hexdigest()[:10], "how": how, "made": now, "seen": now,
           "ua": (headers.get("user-agent") or "")[:300], "ip": _ip(headers), "place": _place(headers)}
    dev["label"] = device_label(dev["ua"])
    with _SESS_LOCK:
        live = {k: v for k, v in sessions().items() if now - v["seen"] < SESSION_IDLE_DAYS * 86400}
        live[_tok_hash(tok)] = dev
        keep = dict(sorted(live.items(), key=lambda kv: kv[1]["seen"])[-SESSION_KEEP:])
        store().set_meta("sessions", json.dumps(keep))
    _set_cookie("hub_key", "", 0)  # the old cookie held the key itself; drop it
    _set_cookie("hub_sess", tok)
    _REQ.session = dev
    where = f" near {dev['place']}" if dev["place"] else ""
    line = f"New sign-in: {dev['label']}{where} ({how})"
    try:
        store().add_chat("qwerty", "QWERTY: " + line, kind="event", channel="dev")
        notify("QWERTY", line + ". Not you? Settings → Devices.", "/settings#devices")
    except Exception as e:
        print(f"couldn't announce a sign-in: {e!r}")
    return dev


def current_session(headers):
    """The signed-in device for this request's hub_sess cookie, or None.
    Refreshes its last-seen time (at most every few minutes)."""
    tok = _cookie(headers, "hub_sess")
    if not tok:
        return None
    key = _tok_hash(tok)
    dev = sessions().get(key)
    if not dev:
        return None
    _REQ.sess_key = key
    now = time.time()
    if now - dev["seen"] > SESSION_SEEN_EVERY:
        with _SESS_LOCK:
            live = sessions()
            if key in live:
                live[key].update(seen=now, ip=_ip(headers) or live[key].get("ip", ""),
                                 place=_place(headers) or live[key].get("place", ""))
                store().set_meta("sessions", json.dumps(live))
    return dev


SIGNED_OUT_KEEP = 15  # signed-out devices remembered on Settings → Devices
# Face ID lock (per device, Settings → Face ID): when the app goes to the
# background it tells the hub; back after more than LOCK_GRACE seconds, the
# hub refuses everything from that device until Face ID passes again.
LOCK_GRACE = int(os.environ.get("LOCK_GRACE_SECONDS", "15"))  # a glance at a notification doesn't lock it


def update_session(key, **fields):
    """Change a signed-in device's record; a None value removes that field."""
    with _SESS_LOCK:
        live = sessions()
        if key not in live:
            return None
        for k, v in fields.items():
            if v is None:
                live[key].pop(k, None)
            else:
                live[key][k] = v
        store().set_meta("sessions", json.dumps(live))
        return live[key]


def lock_check(dev, key):
    """True when this device's Face ID lock is closed. Back within the grace,
    it carries on (and the away mark is cleared); later, it stays locked
    until Face ID passes, however soon after it's used again."""
    if not dev.get("lock"):
        return False
    if dev.get("locked"):
        return True
    if dev.get("hidden"):
        if time.time() - dev["hidden"] > LOCK_GRACE:
            update_session(key, locked=True, hidden=None)
            dev["locked"] = True
            return True
        update_session(key, hidden=None)
        dev.pop("hidden", None)
    return False


def name_device(dev_id, name):
    """Your own name for a signed-in device ('My iPhone'); '' clears it."""
    name = re.sub(r"\s+", " ", name or "").strip()[:40]
    with _SESS_LOCK:
        live = sessions()
        hit = next((v for v in live.values() if v["id"] == dev_id), None)
        if not hit:
            return False
        if name:
            hit["name"] = name
        else:
            hit.pop("name", None)
        store().set_meta("sessions", json.dumps(live))
    return True


def sign_out_device(dev_id, keep=None):
    """Remove one device's session (or all but `keep` when dev_id is '*')."""
    with _SESS_LOCK:
        live = sessions()
        out = {k: v for k, v in live.items()
               if (v["id"] != dev_id if dev_id != "*" else v["id"] == keep)}
        store().set_meta("sessions", json.dumps(out))
        gone_devs = [dict(v, out_at=time.time()) for v in live.values() if v not in out.values()]
        if gone_devs:  # kept (no tokens: only their hashes were ever stored) so what was signed out stays on record
            store().set_meta("sessions:out", json.dumps((_meta_json("sessions:out", []) + gone_devs)[-SIGNED_OUT_KEEP:]))
    gone = {v["id"] for v in live.values()} - {v["id"] for v in out.values()}
    subs = push_subs()
    if gone and any(x.get("sess") in gone for x in subs):  # a signed-out device stops getting notifications
        store().set_meta("push:subs", json.dumps([x for x in subs if x.get("sess") not in gone]))
    return len(live) - len(out)


def note_key_use(headers, via):
    """Remember callers that use the key directly (scripts, Siri), per
    device and address, so QWERTY can list them too."""
    if getattr(_REQ, "quiet", False):
        return
    ua, ip = (headers.get("user-agent") or "")[:300], _ip(headers)
    key = hashlib.sha256(f"{via}|{ua}|{ip}".encode()).hexdigest()[:16]
    now = time.time()
    seen = _meta_json("key:users", {})
    if key in seen and now - seen[key]["seen"] < SESSION_SEEN_EVERY:
        return
    seen.setdefault(key, {"made": now, "via": via, "ua": ua, "ip": ip, "label": device_label(ua), "uses": 0})
    seen[key].update(seen=now, place=_place(headers) or seen[key].get("place", ""))
    seen[key]["uses"] += 1
    store().set_meta("key:users", json.dumps(dict(sorted(seen.items(), key=lambda kv: kv[1]["seen"])[-30:])))


def _auth_dashboard(query, headers):
    """Signed in: this browser's session cookie, or the dashboard key as a
    header or ?key= (a key link signs the browser in with its own session).
    The old key-holding hub_key cookie still works once and is swapped for
    a session."""
    if not DASHBOARD_KEY:
        return True
    if getattr(_REQ, "session", None):
        return True
    sess = current_session(headers)
    if sess:
        if not lock_check(sess, _REQ.sess_key):
            return True
        _REQ.locked = True  # signed in, but locked until Face ID: the key still works, as it would anywhere
    if _same(query.get("key", [None])[0], DASHBOARD_KEY):
        if getattr(_REQ, "page", False):  # a page opened from a key link signs the browser in
            new_session(headers, "key link")
        else:  # an API call with ?key= (a script): noted, no session
            try:
                note_key_use(headers, "?key= on the API")
            except Exception:
                pass
        return True
    if _same(_cookie(headers, "hub_key"), DASHBOARD_KEY):
        new_session(headers, "moved from the old sign-in")
        return True
    if _same(headers.get("x-dashboard-key"), DASHBOARD_KEY):
        try:
            note_key_use(headers, "key header")
        except Exception:
            pass  # bookkeeping never blocks a request
        return True
    return False


def _login_cookie(query):
    """Cookies are set by new_session now; kept for the page routes."""
    return []
