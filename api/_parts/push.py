"""Phone notifications (Web Push), the typing guard's notify side.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Phone notifications (Web Push). Mistral delivers them. Needs the
# dashboard installed to the iPhone Home Screen (iOS 16.4+), VAPID keys in
# Vercel (VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY; /api/push/new-keys makes a
# pair) and a tap on "Turn on" inside the Home Screen app.
def _clean_secret(value):
    """Forgive the usual paste slips: spaces, line breaks and quotes."""
    return "".join(value.split()).strip("\"'")


VAPID_PUBLIC_KEY = _clean_secret(os.environ.get("VAPID_PUBLIC_KEY", ""))
VAPID_PRIVATE_KEY = _clean_secret(os.environ.get("VAPID_PRIVATE_KEY", ""))
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "")


def push_subs():
    return json.loads(store().get_meta("push:subs") or "[]")


def _b64url(text):
    import base64
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def push_problem():
    """(code, explanation) of why phone notifications can't work, or None.
    Never includes key material."""
    if not VAPID_PUBLIC_KEY and not VAPID_PRIVATE_KEY:
        return "no_keys", ("VAPID keys aren't in this deployment: add VAPID_PUBLIC_KEY and "
                           "VAPID_PRIVATE_KEY in Vercel, then redeploy")
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        missing = "VAPID_PUBLIC_KEY" if not VAPID_PUBLIC_KEY else "VAPID_PRIVATE_KEY"
        return "half_keys", f"{missing} is missing in this deployment: add it in Vercel, then redeploy"
    try:
        pub, priv = _b64url(VAPID_PUBLIC_KEY), _b64url(VAPID_PRIVATE_KEY)
    except ValueError:
        return "bad_format", "a VAPID key isn't valid: copy it again exactly as shown, then redeploy"
    if len(pub) == 32 and len(priv) == 65:
        return "swapped", "VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY are swapped in Vercel"
    if len(pub) != 65 or pub[0] != 4:
        return "bad_public", "VAPID_PUBLIC_KEY isn't a valid public key: copy it again"
    if len(priv) != 32:
        return "bad_private", "VAPID_PRIVATE_KEY isn't a valid private key: copy it again"
    try:
        from cryptography.hazmat.primitives import serialization
        from py_vapid import Vapid02
        import pywebpush  # noqa: F401
    except ImportError:
        return "no_library", "the push library isn't installed on the server (requirements.txt)"
    derived = Vapid02.from_raw(VAPID_PRIVATE_KEY.encode()).public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    if derived != pub:
        return "mismatch", ("the two VAPID keys aren't a pair (one came from another refresh): "
                            "generate a new pair and replace both")
    return None


def _push_name(sub):
    from urllib.parse import urlparse
    host = urlparse(sub.get("endpoint", "")).hostname or "?"
    svc = next((n for h, n in _PUSH_HOSTS if host.endswith(h)), host)
    return f"{sub.get('device') or svc}" + (f", added {_when(sub['made'])}" if sub.get("made") else ", added before devices were tracked")


def _urgent(title, body, url):
    """Pushes the typing guard never holds: reminders, QWERTY's security
    and device alerts, health problems, and Settings' test push."""
    return (url == REMINDER_URL or title == "QWERTY" or url.startswith("/diagnostics")
            or body.startswith("Test: phone notifications"))


def notify(title, body, url="/"):
    """Push to every subscribed device; returns how many got it. Quietly
    does nothing until keys and a subscription exist. Dead subscriptions
    (404/410) are dropped. While you're typing, a non-urgent push is held
    (see TYPING_GUARD_SECONDS) and goes out with the next release."""
    if not _urgent(title, body, url) and user_typing():
        _hold(push={"title": title, "body": body[:240], "url": url})
        return 0
    title, body = head_push(title, body)
    subs = push_subs()
    problem = push_problem()
    if problem:
        store().set_meta("push:last_error", problem[1])
        return 0
    if not subs:
        return 0
    try:
        from py_vapid import Vapid02
        from pywebpush import WebPushException, webpush
    except ImportError:
        return 0
    subject = VAPID_SUBJECT or store().get_meta("hub:origin") or ""
    if not subject:
        store().set_meta("push:last_error", "no VAPID_SUBJECT and the dashboard hasn't been opened yet")
        return 0
    vapid = Vapid02.from_raw(VAPID_PRIVATE_KEY.encode())
    payload = json.dumps({"title": title, "body": body[:240], "url": url})
    sent, keep, error, results = 0, [], "", []
    for sub in subs:
        wire = {"endpoint": sub["endpoint"], "keys": sub["keys"]}
        try:
            # high urgency: phones in Low Power Mode otherwise hold pushes back
            r = webpush(wire, payload, vapid_private_key=vapid, vapid_claims={"sub": subject}, ttl=3600, timeout=10,
                        headers={"Urgency": "high"})
            sent += 1
            keep.append(sub)
            results.append({"device": _push_name(sub), "ok": True, "code": getattr(r, "status_code", None)})
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            gone = code in (404, 410)
            if not gone:  # gone for good: drop it
                keep.append(sub)
            error = f"push service returned {code}: {str(e)[:120]}"
            results.append({"device": _push_name(sub), "ok": False, "code": code,
                            "why": "this sign-up no longer exists (app removed or re-added), so it was dropped"
                            if gone else error})
        except Exception as e:  # network trouble shouldn't break a round
            keep.append(sub)
            error = f"push failed: {e!r}"[:160]
            results.append({"device": _push_name(sub), "ok": False, "code": None, "why": error})
    if keep != subs:
        store().set_meta("push:subs", json.dumps(keep))
    store().set_meta("push:last_error", error)
    store().set_meta("push:last", json.dumps({"at": time.time(), "results": results}))
    return sent


def new_vapid_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    import base64
    key = ec.generate_private_key(ec.SECP256R1())
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return {"VAPID_PUBLIC_KEY": b64(key.public_key().public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)),
            "VAPID_PRIVATE_KEY": b64(key.private_numbers().private_value.to_bytes(32, "big"))}


APP_NAME = "Theta"
# Each agent's avatar: a gradient tile with a white line glyph (24-unit grid).
# Theta's doubles as the app icon. "hub" is the system, "you" the user.
AGENT_LOOKS = {
    "theta": ("#6d5efc", "#22b8f0", '<ellipse cx="12" cy="12" rx="6.5" ry="9"/><path d="M5.5 12h13"/>'),
    "mistral": ("#14b8a6", "#0ea5e9", '<path d="M3 8.5h11a2.5 2.5 0 1 0-2.5-2.5"/>'
                '<path d="M3 12.5h15a2.5 2.5 0 1 1-2.5 2.5"/><path d="M3 16.5h6"/>'),
    "glass": ("#10b981", "#0f766e", '<path d="M6.5 4h11L21 9l-9 11L3 9z"/><path d="M3 9h18"/>'
              '<path d="M10 4L8.5 9 12 20l3.5-11L14 4"/>'),
    "remi": ("#f472b6", "#e11d48", '<path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.4 '
             '4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z"/>'),
    "lenz": ("#f59e0b", "#ea580c", '<circle cx="12" cy="12" r="9"/><path d="M10 8.5v7l5.5-3.5z"/>'),
    "red": ("#f05252", "#b91c1c", '<path d="M4 10v4h3l7 4V6l-7 4z"/><path d="M17.5 9a4 4 0 0 1 0 6"/>'),
    "blue": ("#3b82f6", "#1d4ed8", '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9h8M8 12h5"/>'),
    "gray": ("#94a3b8", "#475569", '<path d="M12 4v16M8 20h8M5 7h14"/><path d="M5 7l-2.5 6a2.5 2.5 0 0 0 5 0z"/>'
             '<path d="M19 7l-2.5 6a2.5 2.5 0 0 0 5 0z"/>'),
    "charter": ("#8b5cf6", "#4f46e5", '<path d="M4 20h16"/><path d="M7 16v-5M12 16V6M17 16v-8"/>'),
    "james": ("#fb923c", "#dc2626", '<path d="M6.5 7v10M17.5 7v10M3.5 9.5v5M20.5 9.5v5M6.5 12h11"/>'),
    "qwerty": ("#84cc16", "#3f6212", '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/>'
               '<path d="M6.5 10h.01M10 10h.01M14 10h.01M17.5 10h.01M7.5 14h9"/>'),
    "hub": ("#64748b", "#334155", '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><circle cx="12" cy="12" r="2.5"/>'),
    "you": ("#a1a1aa", "#52525b", '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>'),
}


def _pt(cx, cy, r, deg):
    import math
    a = math.radians(deg - 90)
    return f"{cx + r * math.cos(a):.2f} {cy + r * math.sin(a):.2f}"


def _arc(r, a0, a1, cx=12, cy=12):
    """An open arc path from angle a0 to a1 (degrees, clockwise from top)."""
    return f"M{_pt(cx, cy, r, a0)}A{r} {r} 0 {1 if (a1 - a0) % 360 > 180 else 0} 1 {_pt(cx, cy, r, a1)}"


def _aperture():
    out = []
    for k in range(6):
        o0, o1 = _pt(12, 12, 10, 60 * k), _pt(12, 12, 10, 60 * k + 60)
        i0, i1 = _pt(12, 12, 3.6, 60 * k + 40), _pt(12, 12, 3.6, 60 * k + 100)
        out.append(f'<path d="M{o0}L{o1}L{i1}z"/><path d="M{o0}L{i1}L{i0}z" opacity=".62"/>')
    return "".join(out)


# Avatars: a solid emblem per agent on a lit, glassy tile. Marks are
# drawn in a 24x24 box, white fill or a 2.6 stroke, one shared tile so
# every agent reads at small sizes. Theta's mark never changes: the
# app icon (_icon_png) is drawn from its exact proportions. The
# pre-Stage-3a marks are kept verbatim below as AGENT_MARKS_LEGACY
# (and the line glyphs in AGENT_LOOKS stay), so the original icons
# remain retrievable in this file.
AGENT_MARKS = {
    "theta": '<path fill-rule="evenodd" d="M4.4 12a7.6 10 0 1 0 15.2 0a7.6 10 0 1 0-15.2 0zM7.5 12a4.5 7 0 1 0 9 0a4.5 7 0 1 0-9 0z"/>'
             '<rect x="7.2" y="10.6" width="9.6" height="2.8" rx="1.4"/>',
    "mistral": (f'<g fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round"><path d="{_arc(9.4, 20, 250)}"/>'
                f'<path d="{_arc(6.2, 140, 370)}" opacity=".8"/><path d="{_arc(3, 260, 470)}" opacity=".6"/></g>'),
    "glass": '<path d="M6.2 4.5h11.6l3.7 5H2.5z" opacity=".95"/><path d="M9 4.5h6l-3 5z" opacity=".55"/>'
             '<path d="M2.5 9.5H12v11z" opacity=".78"/><path d="M12 9.5h9.5L12 20.5z" opacity=".5"/>',
    "remi": '<path d="M12 20.6C6 16.4 2.7 13 2.7 9.2 2.7 6.3 5 4 7.8 4c1.8 0 3.3.9 4.2 2.3C12.9 4.9 14.4 4 16.2 4 '
            '19 4 21.3 6.3 21.3 9.2c0 3.8-3.3 7.2-9.3 11.4z"/>',
    "lenz": '<path fill-rule="evenodd" d="M12 2.5a9.5 9.5 0 1 0 0 19a9.5 9.5 0 1 0 0-19zM10.2 8.4v7.2L16.2 12z"/>',
    "red": '<path d="M3 10.5v3h3.5L12 18V6L6.5 10.5z"/>'
            '<g fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round"><path d="M15 9.5a3.6 3.6 0 0 1 0 5"/><path d="M18 7.5a6.5 6.5 0 0 1 0 9"/></g>',
    "blue": '<path fill-rule="evenodd" d="M4 5.5h16v10H9.5L4.5 20V5.5zM7.5 8.5h9v2h-9zM7.5 12h6v2h-6z"/>',
    "gray": '<g fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v16M8.5 20h7M5 7h14"/><path d="M5 7l-2.5 5.5a2.5 2.5 0 0 0 5 0z"/><path d="M19 7l-2.5 5.5a2.5 2.5 0 0 0 5 0z"/></g>',
    "charter": '<rect x="3.5" y="13" width="4.6" height="7.5" rx="2.3" opacity=".6"/>'
               '<rect x="9.7" y="8.5" width="4.6" height="12" rx="2.3" opacity=".8"/>'
               '<rect x="15.9" y="3.5" width="4.6" height="17" rx="2.3"/>',
    "james": '<g fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round"><path d="M7 7v10M17 7v10M4 9.5v5M20 9.5v5M7 12h10"/></g>',
    "qwerty": '<path d="M12 2.6l7.8 2.9v6c0 4.7-3.3 8.5-7.8 10-4.5-1.5-7.8-5.3-7.8-10v-6z"/>'
              '<path d="M10.2 9.4L7.6 12l2.6 2.6M13.8 9.4l2.6 2.6-2.6 2.6" fill="none" stroke="{c2}" stroke-width="2.6" '
              'stroke-linecap="round" stroke-linejoin="round"/>',
    "hub": '<path fill-rule="evenodd" d="M12 2.5l8.2 4.75v9.5L12 21.5l-8.2-4.75v-9.5zM12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6z"/>',
    "you": '<circle cx="12" cy="8.2" r="4.2"/><path d="M3.8 20.8a8.2 8.2 0 0 1 16.4 0z"/>',
}


AGENT_MARKS_LEGACY = {
    "theta": '<path fill-rule="evenodd" d="M4.4 12a7.6 10 0 1 0 15.2 0a7.6 10 0 1 0-15.2 0zM7.5 12a4.5 7 0 1 0 9 0a4.5 7 0 1 0-9 0z"/>'
             '<rect x="7.2" y="10.6" width="9.6" height="2.8" rx="1.4"/>',
    "mistral": (f'<g fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round"><path d="{_arc(9.4, 20, 250)}"/>'
                f'<path d="{_arc(6.2, 140, 370)}" opacity=".8"/><path d="{_arc(3, 260, 470)}" opacity=".6"/></g>'),
    "glass": '<path d="M6.2 4.5h11.6l3.7 5H2.5z" opacity=".95"/><path d="M9 4.5h6l-3 5z" opacity=".55"/>'
             '<path d="M2.5 9.5H12v11z" opacity=".78"/><path d="M12 9.5h9.5L12 20.5z" opacity=".5"/>',
    "remi": '<path d="M12 20.6C6 16.4 2.7 13 2.7 9.2 2.7 6.3 5 4 7.8 4c1.8 0 3.3.9 4.2 2.3C12.9 4.9 14.4 4 16.2 4 '
            '19 4 21.3 6.3 21.3 9.2c0 3.8-3.3 7.2-9.3 11.4z"/>',
    "lenz": _aperture(),
    "red": '<path d="M12 2.5a9.5 9.5 0 0 1 0 19z"/><path d="M12 2.5a9.5 9.5 0 0 0 0 19z" opacity=".34"/>',
    "blue": '<path d="M12 2.5a9.5 9.5 0 0 0 0 19z"/><path d="M12 2.5a9.5 9.5 0 0 1 0 19z" opacity=".34"/>',
    "gray": '<path d="M11 2.56a9.5 9.5 0 0 0 0 18.88z" opacity=".62"/><path d="M13 2.56a9.5 9.5 0 0 1 0 18.88z" opacity=".62"/>'
            '<circle cx="12" cy="12" r="2.2"/>',
    "charter": '<rect x="3.5" y="13" width="4.6" height="7.5" rx="2.3" opacity=".6"/>'
               '<rect x="9.7" y="8.5" width="4.6" height="12" rx="2.3" opacity=".8"/>'
               '<rect x="15.9" y="3.5" width="4.6" height="17" rx="2.3"/>',
    "james": '<path d="M8 9.6V8a4 4 0 0 1 8 0v1.6" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/>'
             '<circle cx="12" cy="14.6" r="6.6"/>',
    "qwerty": '<path d="M12 2.6l7.8 2.9v6c0 4.7-3.3 8.5-7.8 10-4.5-1.5-7.8-5.3-7.8-10v-6z"/>'
              '<path d="M10.2 9.4L7.6 12l2.6 2.6M13.8 9.4l2.6 2.6-2.6 2.6" fill="none" stroke="{c2}" stroke-width="2" '
              'stroke-linecap="round" stroke-linejoin="round"/>',
    "hub": '<path fill-rule="evenodd" d="M12 2.5l8.2 4.75v9.5L12 21.5l-8.2-4.75v-9.5zM12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6z"/>',
    "you": '<circle cx="12" cy="8.2" r="4.2"/><path d="M3.8 20.8a8.2 8.2 0 0 1 16.4 0z"/>',
}


def agent_look(agent_id):
    return AGENT_LOOKS.get(agent_id) or AGENT_LOOKS["hub"]


def avatar_svg(agent_id, size=40):
    """An agent's avatar as standalone SVG (also served at /avatar/<id>.svg):
    their emblem, softly shadowed, on a lit gradient tile."""
    aid = agent_id if agent_id in AGENT_LOOKS else "hub"
    c1, c2, _ = agent_look(aid)
    mark = AGENT_MARKS.get(aid, AGENT_MARKS["hub"]).replace("{c2}", c2)
    g = f"av-{aid}"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" width="{size}" height="{size}" '
            f'role="img" aria-label="{html.escape(display_name(agent_id) if agent_id in AGENTS else agent_id)}">'
            f'<defs><linearGradient id="{g}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c1}"/>'
            f'<stop offset="1" stop-color="{c2}"/></linearGradient>'
            f'<radialGradient id="{g}-l" cx=".22" cy=".12" r=".95"><stop offset="0" stop-color="#fff" stop-opacity=".38"/>'
            f'<stop offset=".55" stop-color="#fff" stop-opacity="0"/></radialGradient>'
            f'<linearGradient id="{g}-s" x1="0" y1="0" x2="0" y2="1"><stop offset=".45" stop-color="#000" stop-opacity="0"/>'
            f'<stop offset="1" stop-color="#000" stop-opacity=".22"/></linearGradient></defs>'
            f'<rect width="40" height="40" rx="11" fill="url(#{g})"/><rect width="40" height="40" rx="11" fill="url(#{g}-l)"/>'
            f'<rect width="40" height="40" rx="11" fill="url(#{g}-s)"/>'
            f'<rect x=".5" y=".5" width="39" height="39" rx="10.5" fill="none" stroke="#fff" stroke-opacity=".22"/>'
            f'<g transform="translate(5.8 6.9) scale(1.18)" fill="#000" opacity=".2">{mark.replace(chr(35) + "fff", chr(35) + "000")}</g>'
            f'<g transform="translate(5.8 5.8) scale(1.18)" fill="#fff">{mark}</g></svg>')


_ICONS = {}


def _icon_png(size):
    """The app icon: Theta's avatar emblem (the theta: an oval ring crossed
    by a bar) on his lit gradient tile, matching /avatar/theta.svg. Drawn
    here from distance fields, anti-aliased, as a PNG with no deps. Full
    bleed: iOS and Android round the corners themselves."""
    if size in _ICONS:
        return _ICONS[size]
    import struct
    import zlib
    (r1, g1, b1), (r2, g2, b2) = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in AGENT_LOOKS["theta"][:2])
    u = size / 40  # the avatar is drawn in a 40-unit box; the mark sits at translate(5.8) scale(1.18)
    cx = cy = (5.8 + 12 * 1.18) * u
    ora, orb, ira, irb = 7.6 * 1.18 * u, 10 * 1.18 * u, 4.5 * 1.18 * u, 7 * 1.18 * u
    bhw, bhh = 4.8 * 1.18 * u, 1.4 * 1.18 * u  # bar half-width / half-height (fully rounded ends)
    drop = 1.1 * u

    def ell(px, py, a, b):  # first-order signed distance to an ellipse
        k = ((px / a) ** 2 + (py / b) ** 2) ** 0.5
        grad = ((px / a ** 2) ** 2 + (py / b ** 2) ** 2) ** 0.5 / k if k else 1 / b
        return (k - 1) / grad

    def mark(px, py):  # signed distance to the theta (negative inside)
        ring = max(ell(px, py, ora, orb), -ell(px, py, ira, irb))
        qx, qy = max(abs(px) - (bhw - bhh), 0.0), abs(py)
        bar = (qx * qx + qy * qy) ** 0.5 - bhh
        return min(ring, bar)

    rows = []
    for y in range(size):
        row = bytearray(b"\x00")
        fy = (y + 0.5) / size
        for x in range(size):
            fx = (x + 0.5) / size
            t = (fx + fy) / 2  # diagonal gradient, top-left to bottom-right
            r, g, b = r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t
            light = max(0.0, 1 - ((fx - 0.22) ** 2 + (fy - 0.12) ** 2) ** 0.5 / (0.95 * 0.55)) * 0.38
            r, g, b = r + (255 - r) * light, g + (255 - g) * light, b + (255 - b) * light
            shade = max(0.0, (fy - 0.45) / 0.55) * 0.22
            r, g, b = r * (1 - shade), g * (1 - shade), b * (1 - shade)
            px, py = x + 0.5 - cx, y + 0.5 - cy
            sh = min(1.0, max(0.0, 0.5 - mark(px, py - drop))) * 0.2  # the shadow under the mark
            r, g, b = r * (1 - sh), g * (1 - sh), b * (1 - sh)
            a = min(1.0, max(0.0, 0.5 - mark(px, py)))
            row += bytes((round(r + (255 - r) * a), round(g + (255 - g) * a), round(b + (255 - b) * a)))
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    _ICONS[size] = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))
    return _ICONS[size]


_SW_JS = """
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data.json(); } catch (_) { d = {title: "Theta", body: e.data ? e.data.text() : ""}; }
  e.waitUntil(self.registration.showNotification(d.title || "Theta",
    {body: d.body || "", data: {url: d.url || "/"}, icon: "/icon-192.png?v=2", badge: "/icon-192.png?v=2"}));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil(clients.openWindow((e.notification.data && e.notification.data.url) || "/"));
});
"""


_PUSH_JS = """
(() => {
  // Buttons are wired first and every step is time-limited and reported, so the
  // page can never fail silently (iPhone gives no console to look at).
  const status = document.getElementById("push-status");
  const say = t => { status.textContent = t; };
  const PH = {"Content-Type": "application/json", "x-dashboard-key": new URLSearchParams(location.search).get("key") || ""};
  const limit = (p, what) => Promise.race([p, new Promise((_, no) =>
    setTimeout(() => no(new Error(what + " took too long")), 10000))]);
  const why = e => (e && e.message) || String(e);
  // Failures are also sent to the hub, so Settings → Devices (and QWERTY) show why.
  const report = (stage, msg) => fetch("/api/push/fail", {method: "POST", headers: PH,
    body: JSON.stringify({stage, error: String(msg).slice(0, 200), standalone})}).catch(() => {});
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  // iPhone only gives Notification and PushManager to Home Screen web apps.
  const noPush = !("PushManager" in window) || !("Notification" in window);
  const noPushWhy = standalone ? "Notifications need iOS 16.4 or later."
    : "This is open in Safari, not as the Home Screen app. Open Theta from its Home Screen icon. "
      + "If the icon opens Safari, delete it, then in Safari tap Share, Add to Home Screen, and keep Open as Web App on.";
  say("Checking notifications...");
  const setup = (async () => {
    if (!("serviceWorker" in navigator)) throw new Error("This browser can't show notifications.");
    if (noPush) throw new Error(noPushWhy);
    await limit(navigator.serviceWorker.register("/sw.js"), "Starting the notification helper");
    const reg = await limit(navigator.serviceWorker.ready, "Starting the notification helper");
    const r = await limit(fetch("/api/push/key", {headers: PH}), "Reaching the hub");
    if (r.status === 401) throw new Error("This app isn't signed in: open it once with ?key=YOUR_KEY, then add it to the Home Screen again.");
    const d = await r.json();
    return {reg, key: d.publicKey, problem: d.problem || "", devices: d.devices || 0};
  })();
  setup.then(async ({reg, problem, devices}) => {
    const sub = await reg.pushManager.getSubscription().catch(() => null);
    // The phone's own copy can outlive the server's (or predate new keys), so trust the server's count.
    say(problem || (sub && devices ? "Notifications are on for this device."
      : "Tap Turn on to get notifications on this device."));
  }, e => { say(why(e)); report("check", why(e)); });
  document.getElementById("push-on").onclick = async () => {
    if (noPush) { say(noPushWhy); report("turn on", noPushWhy); return; }
    say("Turning on...");
    try {
      const perm = await Notification.requestPermission();  // before any other await: iOS needs the tap's user gesture
      if (perm !== "granted") { say("Notifications were not allowed. To retry on iPhone, remove the Home Screen app and add it again.");
        report("permission", "permission is " + perm); return; }
      const {reg, key, problem} = await setup;
      if (!key) { say(problem || "Phone notifications aren't set up on the server yet."); report("server", problem || "no public key"); return; }
      // A sign-up made under older keys blocks a new one, so always start fresh.
      const old = await reg.pushManager.getSubscription();
      if (old) await old.unsubscribe();
      const raw = atob(key.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - key.length % 4) % 4));
      const s = await limit(reg.pushManager.subscribe({userVisibleOnly: true,
        applicationServerKey: Uint8Array.from(raw, c => c.charCodeAt(0))}), "Signing up with Apple");
      const d = await (await fetch("/api/push/subscribe", {method: "POST", headers: PH, body: JSON.stringify({subscription: s})})).json();
      say(d.ok ? "Notifications are on for this device." : "Couldn't turn on: " + d.error);
      if (!d.ok) report("saving", d.error);
    } catch (e) {
      say("Couldn't turn on: " + why(e)); report("turn on", (e && e.name ? e.name + ": " : "") + why(e));
    }
  };
  document.getElementById("push-test").onclick = async () => {
    say("Sending...");
    try {
      const r = await fetch("/api/push/test", {method: "POST", headers: PH, body: "{}"});
      if (r.status === 401) { say("This app isn't signed in: open it once with ?key=YOUR_KEY, then add it to the Home Screen again."); return; }
      const d = await r.json();
      if (!d.ok) { say(d.error); return; }
      const lines = (d.results || []).map(x => (x.ok ? "\u2713 Apple/Google accepted it for " : "\u2717 ") + x.device + (x.ok ? "" : ": " + x.why));
      say((d.sent ? "Sent to " + d.sent + " device(s)." : "Nothing sent: " + (d.error || "no device subscribed"))
        + (lines.length ? "\\n" + lines.join("\\n") : "")
        + (d.sent ? "\\nNothing showed up? Check iPhone Settings, Notifications, Theta (allowed), and that Focus is off. "
          + "If you re-added the Home Screen icon, tap Turn on again here: each icon has its own sign-up." : ""));
    } catch (e) {
      say("Couldn't send: " + why(e));
    }
  };
})();
"""
