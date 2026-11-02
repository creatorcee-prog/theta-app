"""Face ID sign-in (passkeys) and the sign-in page.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Face ID sign-in (passkeys). Your phone checks your face itself; the
# hub only ever sees a signature, never a picture. Register a device in
# Settings while signed in; after that the sign-in page has "Sign in with
# Face ID", which sets the same login cookie the dashboard key does.
# ES256 (P-256) passkeys, the kind iPhones, Macs and Android phones make.
PASSKEY_CHALLENGE_SECONDS = 300
_PK_LOCK = threading.Lock()


def _b64u_decode(s):
    s = str(s)
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def cbor_decode(data):
    """Just enough CBOR for WebAuthn (maps, arrays, ints, bytes, text)."""
    def item(i):
        ib = data[i]
        major, info = ib >> 5, ib & 31
        i += 1
        if info < 24:
            val = info
        elif info in (24, 25, 26, 27):
            n = 1 << (info - 24)
            val = int.from_bytes(data[i:i + n], "big")
            i += n
        else:
            raise ValueError("unsupported CBOR")
        if major == 0:
            return val, i
        if major == 1:
            return -1 - val, i
        if major in (2, 3):
            chunk = data[i:i + val]
            return (bytes(chunk) if major == 2 else chunk.decode()), i + val
        if major == 4:
            out = []
            for _ in range(val):
                v, i = item(i)
                out.append(v)
            return out, i
        if major == 5:
            out = {}
            for _ in range(val):
                k, i = item(i)
                v, i = item(i)
                out[k] = v
            return out, i
        if major == 7 and info in (20, 21, 22):
            return {20: False, 21: True, 22: None}[info], i
        raise ValueError("unsupported CBOR")
    value, _ = item(0)
    return value


def passkeys():
    return _meta_json("passkeys", [])


def new_challenge(kind):
    c = _b64u(os.urandom(32))
    with _PK_LOCK:
        live = {k: v for k, v in _meta_json("pk:challenges", {}).items() if v["exp"] > time.time()}
        live[c] = {"kind": kind, "exp": time.time() + PASSKEY_CHALLENGE_SECONDS}
        store().set_meta("pk:challenges", json.dumps(dict(list(live.items())[-50:])))
    return c


def _take_challenge(c, kind):
    """A challenge is good once, for its kind, for 5 minutes."""
    with _PK_LOCK:
        live = _meta_json("pk:challenges", {})
        got = live.pop(c, None)
        store().set_meta("pk:challenges", json.dumps(live))
    return bool(got and got["kind"] == kind and got["exp"] > time.time())


def _check_client(client_json, kind, origin):
    cd = json.loads(client_json)
    if cd.get("type") != f"webauthn.{kind}":
        raise ValueError("wrong ceremony")
    if cd.get("origin") != origin:
        raise ValueError(f"wrong origin {cd.get('origin')}")
    if not _take_challenge(cd.get("challenge", ""), kind):
        raise ValueError("challenge expired or already used")


def _check_auth_data(auth, rp_id):
    if auth[:32] != hashlib.sha256(rp_id.encode()).digest():
        raise ValueError("passkey is for another site")
    flags = auth[32]
    if not flags & 0x01 or not flags & 0x04:
        raise ValueError("the device didn't verify you (Face ID, Touch ID or passcode)")
    return flags, int.from_bytes(auth[33:37], "big")


def register_passkey(data, rp_id, origin, name="This device"):
    from cryptography.hazmat.primitives.asymmetric import ec
    _check_client(_b64u_decode(data["clientDataJSON"]), "create", origin)
    att = cbor_decode(_b64u_decode(data["attestationObject"]))
    auth = att["authData"]
    flags, count = _check_auth_data(auth, rp_id)
    if not flags & 0x40:
        raise ValueError("no credential in the response")
    n = int.from_bytes(auth[53:55], "big")
    cred_id, cose = auth[55:55 + n], cbor_decode(auth[55 + n:])
    if cose.get(3) != -7 or cose.get(1) != 2 or cose.get(-1) != 1:
        raise ValueError("only ES256 (P-256) passkeys are supported")
    ec.EllipticCurvePublicNumbers(int.from_bytes(cose[-2], "big"), int.from_bytes(cose[-3], "big"),
                                  ec.SECP256R1()).public_key()  # a real point on the curve, or this raises
    pk = {"id": _b64u(cred_id), "x": _b64u(cose[-2]), "y": _b64u(cose[-3]), "count": count,
          "name": str(name)[:60] or "This device", "created": time.time(), "used": None, "site": rp_id}
    with _PK_LOCK:
        keys = [k for k in passkeys() if k["id"] != pk["id"]] + [pk]
        store().set_meta("passkeys", json.dumps(keys[-10:]))
    post_event("qwerty", f"QWERTY added a Face ID sign-in: {pk['name']}")
    return pk


def verify_passkey(data, rp_id, origin):
    """True when the signature is from one of your registered devices."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    key = next((k for k in passkeys() if k["id"] == data.get("id")), None)
    if not key:
        raise ValueError("this device isn't registered")
    client = _b64u_decode(data["clientDataJSON"])
    _check_client(client, "get", origin)
    auth = _b64u_decode(data["authenticatorData"])
    _, count = _check_auth_data(auth, rp_id)
    pub = ec.EllipticCurvePublicNumbers(int.from_bytes(_b64u_decode(key["x"]), "big"),
                                        int.from_bytes(_b64u_decode(key["y"]), "big"), ec.SECP256R1()).public_key()
    try:
        pub.verify(_b64u_decode(data["signature"]), auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise ValueError("signature didn't match")
    if count and key["count"] and count <= key["count"]:
        raise ValueError("this passkey may have been copied (its counter went backwards)")
    with _PK_LOCK:
        keys = passkeys()
        for k in keys:
            if k["id"] == key["id"]:
                k.update(count=count, used=time.time())
        store().set_meta("passkeys", json.dumps(keys))
    return key


def passkey_fail(headers, stage, error, site):
    """Keep the last few Face ID failures with their reasons (for QWERTY)."""
    try:
        fails = _meta_json("pk:fails", [])
        fails.append({"at": time.time(), "stage": stage, "error": error[:200], "site": site,
                      "device": device_label(headers.get("user-agent")), "place": _place(headers)})
        store().set_meta("pk:fails", json.dumps(fails[-15:]))
    except Exception:
        pass


def _rp(headers):
    """The site passkeys belong to, and the origin the browser reports."""
    host = (headers.get("host") or "localhost").split(",")[0].strip()
    proto = "http" if host.startswith(("127.0.0.1", "localhost")) else "https"
    return host.split(":")[0], f"{proto}://{host}"


_SIGNIN_JS = r"""
(() => {
  const out = document.getElementById("si-status"), b64 = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - s.length % 4) % 4)), c => c.charCodeAt(0));
  const u = buf => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  // Safari only shows Face ID when the request starts right from a tap, so
  // the challenge is fetched ahead of time (and refreshed before it expires).
  const why = (e, stage) => {
    const msg = (e && (e.name ? e.name + ": " : "") + (e.message || e)) || "unknown";
    fetch("/api/passkey/fail", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({stage, error: msg})}).catch(() => {});
    if (e && e.name === "NotAllowedError") return "Face ID was cancelled or timed out, or this device has no Theta passkey for " +
      location.hostname + " (a passkey only works on the address it was added on).";
    if (e && e.name === "InvalidStateError") return "This device is already added.";
    if (e && e.name === "SecurityError") return "This address can't use passkeys (" + location.hostname + ").";
    return e.message || String(e);
  };
  const ready = (url, h) => {
    let o = null, at = 0;
    const load = async () => { try { const d = await (await fetch(url, {headers: h || {}})).json(); if (d.ok) { o = d; at = Date.now(); } } catch (e) {} };
    load();
    document.addEventListener("visibilitychange", () => { if (!document.hidden && Date.now() - at > 120000) load(); });
    return async () => { if (!o || Date.now() - at > 240000) await load(); const x = o; o = null; load(); if (!x) throw new Error("Couldn't reach Theta. Check your connection."); return x; };
  };
  const opts = window.PublicKeyCredential && !document.getElementById("si-face").hidden ? ready("/api/passkey/options?type=login") : null;
  document.getElementById("si-face").onclick = async () => {
    if (!window.PublicKeyCredential) { out.textContent = "This browser can't use passkeys. Use your key below."; return; }
    out.textContent = "Waiting for Face ID...";
    try {
      const o = await opts();
      const cred = await navigator.credentials.get({publicKey: {challenge: b64(o.challenge), rpId: o.rpId, userVerification: "required", timeout: 60000}});
      const r = cred.response;
      const unlock = document.getElementById("si-face").dataset.unlock;
      const d = await (await fetch(unlock ? "/api/passkey/unlock" : "/api/passkey/login", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(
        {id: cred.id, clientDataJSON: u(r.clientDataJSON), authenticatorData: u(r.authenticatorData), signature: u(r.signature)})})).json();
      if (!d.ok) throw new Error(d.error);
      out.textContent = unlock ? "Unlocked." : "Signed in."; location.reload();
    } catch (e) { out.textContent = "Couldn't sign in: " + why(e, "sign-in"); }
  };
  document.getElementById("si-key").onsubmit = e => { e.preventDefault(); const k = document.getElementById("si-keyin").value.trim(); if (k) location.href = location.pathname + "?key=" + encodeURIComponent(k); };
})();
"""

_PASSKEY_JS = r"""
(() => {
  const out = document.getElementById("pk-status"), H = window.THETA_H;
  const b64 = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - s.length % 4) % 4)), c => c.charCodeAt(0));
  const u = buf => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const add = document.getElementById("pk-add");
  // Safari only shows Face ID when the request starts right from a tap, so
  // the challenge is fetched ahead of time (and refreshed before it expires).
  const why = (e, stage) => {
    const msg = (e && (e.name ? e.name + ": " : "") + (e.message || e)) || "unknown";
    fetch("/api/passkey/fail", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({stage, error: msg})}).catch(() => {});
    if (e && e.name === "NotAllowedError") return "Face ID was cancelled or timed out, or this device has no Theta passkey for " +
      location.hostname + " (a passkey only works on the address it was added on).";
    if (e && e.name === "InvalidStateError") return "This device is already added.";
    if (e && e.name === "SecurityError") return "This address can't use passkeys (" + location.hostname + ").";
    return e.message || String(e);
  };
  const ready = (url, h) => {
    let o = null, at = 0;
    const load = async () => { try { const d = await (await fetch(url, {headers: h || {}})).json(); if (d.ok) { o = d; at = Date.now(); } } catch (e) {} };
    load();
    document.addEventListener("visibilitychange", () => { if (!document.hidden && Date.now() - at > 120000) load(); });
    return async () => { if (!o || Date.now() - at > 240000) await load(); const x = o; o = null; load(); if (!x) throw new Error("Couldn't reach Theta. Check your connection."); return x; };
  };
  if (!window.PublicKeyCredential) { add.disabled = true; out.textContent = "This browser can't make passkeys."; }
  const lockBtn = document.getElementById("lock-set"), lockOut = document.getElementById("lock-status");
  const lockOpts = lockBtn && lockBtn.dataset.on === "1" && window.PublicKeyCredential ? ready("/api/passkey/options?type=login", H) : null;
  if (lockBtn) lockBtn.onclick = async () => {
    const on = lockBtn.dataset.on === "1";
    lockBtn.disabled = true;
    try {
      let assertion = null;
      if (on) {
        if (!lockOpts) throw new Error("This browser can't use Face ID here.");
        lockOut.textContent = "Look at your phone...";
        const o = await lockOpts();
        const cred = await navigator.credentials.get({publicKey: {challenge: b64(o.challenge), rpId: o.rpId, userVerification: "required", timeout: 60000}});
        const r = cred.response;
        assertion = {id: cred.id, clientDataJSON: u(r.clientDataJSON), authenticatorData: u(r.authenticatorData), signature: u(r.signature)};
      }
      const d = await (await fetch("/api/lock/set", {method: "POST", headers: H, body: JSON.stringify({on, assertion})})).json();
      if (!d.ok) throw new Error(d.error);
      location.reload();
    } catch (e) { lockOut.textContent = on ? "Couldn't turn it on: " + why(e, "lock") : "Couldn't turn it off: " + (e.message || e); lockBtn.disabled = false; }
  };
  const opts = window.PublicKeyCredential ? ready("/api/passkey/options?type=register", H) : null;
  add.onclick = async () => {
    out.textContent = "Follow your device's prompt...";
    try {
      const o = await opts();
      const cred = await navigator.credentials.create({publicKey: {
        challenge: b64(o.challenge), rp: {name: "Theta", id: o.rpId},
        user: {id: b64(o.userId), name: "theta-owner", displayName: "Theta"},
        pubKeyCredParams: [{type: "public-key", alg: -7}], timeout: 60000, attestation: "none",
        authenticatorSelection: {residentKey: "required", userVerification: "required"},
        excludeCredentials: o.have.map(id => ({type: "public-key", id: b64(id)}))}});
      const d = await (await fetch("/api/passkey/register", {method: "POST", headers: H, body: JSON.stringify({
        name: document.getElementById("pk-name").value || "This device",
        clientDataJSON: u(cred.response.clientDataJSON), attestationObject: u(cred.response.attestationObject)})})).json();
      if (!d.ok) throw new Error(d.error);
      out.textContent = "Added. You can sign in with Face ID on this device now."; setTimeout(() => location.reload(), 900);
    } catch (e) { out.textContent = "Couldn't add it: " + why(e, "adding"); }
  };
  document.querySelectorAll("[data-pk-remove]").forEach(b => b.onclick = async () => {
    const d = await (await fetch("/api/passkey/remove", {method: "POST", headers: H, body: JSON.stringify({id: b.dataset.pkRemove})})).json();
    if (d.ok) b.closest("li").remove();
  });
})();
"""


def signin_page(headers):
    """What you see without the key: Face ID, or type the key. A device whose
    Face ID lock has closed gets the same page as a lock: Unlock with Face ID."""
    has = bool(passkeys())
    locked = getattr(_REQ, "locked", False)
    body = (
        f'<div style="max-width:420px;margin:12vh auto 0" class="card stack"><div class="hero">{avatar_img("theta", 56)}'
        f'<div><p class="eyebrow">{APP_NAME}</p><h1>{"Locked" if locked else "Sign in"}</h1></div></div>'
        + ('<p class="muted small">Theta was in the background, so it needs Face ID again.</p>'
           '<button class="btn" id="si-face" type="button" data-unlock="1">Unlock with Face ID</button>' if locked and has else
           '<button class="btn" id="si-face" type="button">Sign in with Face ID</button>' if has else
           '<p class="muted small">Open Theta once with your key, then add Face ID sign-in in Settings.</p>'
           '<button class="btn" id="si-face" type="button" hidden></button>')
        + '<form id="si-key" class="box" style="padding:5px 5px 5px 14px"><input id="si-keyin" type="password" '
          'placeholder="Dashboard key" aria-label="Dashboard key" autocomplete="current-password" '
          'style="flex:1;border:0;background:transparent;outline:none;padding:8px 0;min-width:0">'
          '<button class="btn small" type="submit">Open</button></form><p class="note" id="si-status"></p></div>'
        f"<script>{_SIGNIN_JS}</script>")
    theme, mode, _, _, _ = ui_prefs(headers)
    return (f'<!doctype html><html lang="en" data-theme="{theme}" data-mode="{mode}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<title>Sign in · {APP_NAME}</title><link rel="stylesheet" href="/ui.css?v={_ASSET_V}">'
            '<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">'
            '<link rel="apple-touch-icon" href="/apple-touch-icon.png?v=2"></head>'
            f'<body><main class="main">{body}</main></body></html>')


_PUSH_HOSTS = (("push.apple.com", "Apple (iPhone, iPad or Mac)"), ("fcm.googleapis.com", "Chrome or Android"),
               ("mozilla.com", "Firefox"), ("notify.windows.com", "Edge on Windows"))


def _when(t):
    if not t:
        return "unknown"
    d = datetime.fromtimestamp(t, hub_tz())
    return f"{d:%b} {d.day}, {_clock(d)}"


def devices_report():
    """Everything the hub knows about what's connected to it."""
    from urllib.parse import urlparse
    push = []
    for x in push_subs():
        host = urlparse(x.get("endpoint", "")).hostname or "?"
        push.append({"id": hashlib.sha1(x.get("endpoint", "").encode()).hexdigest()[:10],
                     "service": next((n for h, n in _PUSH_HOSTS if host.endswith(h)), host),
                     "device": x.get("device") or "added before devices were tracked",
                     "place": x.get("place", ""), "made": x.get("made")})
    return {"sessions": sorted(sessions().values(), key=lambda d: -d["seen"]),
            "passkeys": passkeys(), "push": push,
            "key_users": sorted(_meta_json("key:users", {}).values(), key=lambda d: -d["seen"]),
            "bots": list(BOT_KEYS),
            "pk_fails": _meta_json("pk:fails", [])[-5:], "push_fails": _meta_json("push:fails", [])[-5:]}


def devices_text():
    """The device list as plain lines, for QWERTY and /devices."""
    r = devices_report()
    out = [f"Signed-in devices ({len(r['sessions'])}):"]
    out += [f"- {(chr(34) + d['name'] + chr(34) + ' (named by the user), ') if d.get('name') else 'NOT NAMED: '}"
            f"{d['label']}{', ' + device_os(d.get('ua')) if device_os(d.get('ua')) else ''} · {d['how']} · "
            f"{d.get('place') or 'place unknown'} · IP {d.get('ip') or '?'} · "
            f"signed in {_when(d['made'])}, last seen {_when(d['seen'])}" for d in r["sessions"]] or ["- none yet"]
    gone = _meta_json("sessions:out", [])[-5:]
    if gone:
        out.append("Signed out recently:")
        out += [f"- {device_name(d)}, {d['how']}, {d.get('place') or 'place unknown'}, IP {d.get('ip') or '?'}, "
                f"signed out {_when(d['out_at'])}" for d in reversed(gone)]
    out.append(f"Face ID passkeys ({len(r['passkeys'])}):")
    out += [f"- {k['name']} (for {k.get('site') or 'site not recorded'}), added {_when(k['created'])}, "
            f"last used {_when(k.get('used'))}" for k in r["passkeys"]] or ["- none"]
    out.append(f"Getting notifications ({len(r['push'])}):")
    out += [f"- {x['service']}: {x['device']}" + (f" near {x['place']}" if x["place"] else "") for x in r["push"]] or ["- none"]
    if r["key_users"]:
        out.append("Used the key directly:")
        out += [f"- {k['label']} via {k['via']} · {k.get('place') or '?'} · IP {k.get('ip') or '?'} · "
                f"{k['uses']} times, last {_when(k['seen'])}" for k in r["key_users"]]
    if BOT_KEYS:
        out.append("Bots with their own keys: " + ", ".join(display_name(b) for b in BOT_KEYS))
    if r["push_fails"]:
        out.append("Recent notification sign-up failures:")
        out += [f"- {_when(f['at'])} {f['stage']} on {f['device']} ({'Home Screen app' if f['standalone'] else 'in the browser'}): "
                f"{f['error']}" for f in r["push_fails"]]
    if r["pk_fails"]:
        out.append("Recent Face ID failures:")
        out += [f"- {_when(f['at'])} {f['stage']} on {f['device']} at {f['site']}: {f['error']}" for f in r["pk_fails"]]
    out.append("Devices still on the old sign-in appear once they next open Theta; changing DASHBOARD_KEY "
               "cuts off any device not listed.")
    return "\n".join(out)


_DEVICES_JS = """
(() => {
  const box = document.getElementById("devices"); if (!box) return;
  box.addEventListener("click", async e => {
    const pr = e.target.closest("[data-pushrm]");
    if (pr) {
      const d = await (await fetch("/api/push/remove", {method: "POST", headers: window.THETA_H, body: JSON.stringify({id: pr.dataset.pushrm})})).json();
      if (d.ok) pr.closest("li").remove(); else box.querySelector(".note").textContent = d.error;
      return;
    }
    const nm = e.target.closest("[data-name]");
    if (nm) {
      const name = prompt("Name this device (like My iPhone). Leave empty to clear.", nm.dataset.cur || "");
      if (name === null) return;
      const d = await (await fetch("/api/devices/name", {method: "POST", headers: window.THETA_H, body: JSON.stringify({id: nm.dataset.name, name})})).json();
      if (d.ok) location.reload(); else box.querySelector(".note").textContent = d.error;
      return;
    }
    const b = e.target.closest("[data-signout]"); if (!b) return;
    const all = b.dataset.signout === "*";
    if (all && !confirm("Sign out every other device? They'll need the key or Face ID again.")) return;
    const d = await (await fetch("/api/devices/signout", {method: "POST", headers: window.THETA_H,
      body: JSON.stringify({id: b.dataset.signout})})).json();
    const note = box.querySelector(".note");
    if (!d.ok) { note.textContent = d.error; return; }
    if (all) location.reload(); else b.closest("li").remove();
  });
  // Tell the hub what this device is (the Home Screen app?) and which
  // notification sign-up it holds, so the list pairs them up.
  (async () => {
    let endpoint = null;
    try {
      const reg = navigator.serviceWorker && await navigator.serviceWorker.getRegistration();
      const sub = reg && await reg.pushManager.getSubscription();
      endpoint = sub ? sub.endpoint : null;
    } catch (_) {}
    const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
    try {
      const d = await (await fetch("/api/devices/hello", {method: "POST", headers: window.THETA_H,
        body: JSON.stringify({standalone, endpoint})})).json();
      if (d.changed) location.reload();
    } catch (_) {}
  })();
})();
"""


def device_name(d):
    """Your name for it if you gave one, else 'iPhone · Home Screen app' (when
    Settings said so) or the user agent's guess."""
    if d.get("name"):
        return d["name"]
    return d["label"].split(" · ")[0] + " · " + d["app"] if d.get("app") else d["label"]


def device_facts(d):
    """'iPhone · Safari, iOS 26.1 · signed in Oct 23 4:12 AM by key link · near Denver, CO, US'."""
    kind = d["label"].split(" · ")[0] + " · " + d["app"] if d.get("app") else d["label"]
    os_ = device_os(d.get("ua"))
    return " · ".join(p for p in (
        (kind + (f", {os_}" if os_ else "")) if d.get("name") else os_,
        f"signed in {datetime.fromtimestamp(d['made'], hub_tz()):%b %d} {_clock(datetime.fromtimestamp(d['made'], hub_tz()))} by {d['how']}",
        f"near {d['place']}" if d.get("place") else "place unknown") if p)


def devices_card(headers):
    """One list: each device, whether it's this one, and whether it gets notifications."""
    r, me = devices_report(), current_session(headers) or getattr(_REQ, "session", None) or {}
    esc = html.escape
    subs = push_subs()
    by_sess = {x.get("sess") for x in subs if x.get("sess")}
    ids = {d["id"] for d in r["sessions"]}
    loose = [x for x in subs if x.get("sess") not in ids]  # notifications not tied to a signed-in device
    devs = sorted(r["sessions"], key=lambda d: (d["id"] != me.get("id"), -d["seen"]))
    recent_fail = next((f for f in reversed(r["push_fails"]) if time.time() - f["at"] < 86400), None)

    def row(d):
        mine = d["id"] == me.get("id")
        on = d["id"] in by_sess
        why = (f' · <span class="bad-t">{esc(recent_fail["error"])}</span>' if mine and not on and recent_fail else "")
        return (f'<li class="dev"><div class="brow" style="align-items:center"><span><b>{esc(device_name(d))}</b>'
                + (' <span class="chip">This device</span>' if mine else "")
                + ('' if d.get("name") or mine else ' <span class="chip bad-t">Not named</span>') + '</span><span>'
                + f'<button class="btn ghost small" type="button" data-name="{esc(d["id"])}" data-cur="{esc(d.get("name", ""))}">'
                  f'{"Rename" if d.get("name") else "Name it"}</button>'
                + ('' if mine else f' <button class="btn ghost small" type="button" data-signout="{esc(d["id"])}">Sign out</button>')
                + f'</span></div><div class="small muted">{esc(device_facts(d))}</div>'
                  f'<div class="small"><span class="{"ok-t" if on else "muted"}">'
                  f'{"Notifications on" if on else "Notifications off"}</span>{why}'
                  f'<span class="muted"> · active {_when(d["seen"])}</span></div></li>')
    rows = "".join(row(d) for d in devs)
    rows += "".join(f'<li class="dev"><div class="brow" style="align-items:center"><span><b>{esc(x["device"])}</b></span>'
                    f'<button class="btn ghost small" type="button" data-pushrm="{esc(x["id"])}">Remove</button></div>'
                    f'<div class="small"><span class="ok-t">Notifications on</span><span class="muted"> · not signed in '
                    f'here (open Settings on that device to link it)</span></div></li>'
                    for x in r["push"] if any(hashlib.sha1(y.get("endpoint", "").encode()).hexdigest()[:10] == x["id"] for y in loose))
    details = "".join(f'<li class="small">{esc(device_name(d))}: {esc(d["how"])}, signed in {_when(d["made"])}, '
                      f'{esc(d.get("place") or "place unknown")}, IP {esc(d.get("ip") or "?")}</li>' for d in devs)
    details += "".join(f'<li class="small">Used the key directly: {esc(k["label"])} via {esc(k["via"])}, '
                       f'{k["uses"]}×, last {_when(k["seen"])}, IP {esc(k.get("ip") or "?")}</li>' for k in r["key_users"])
    details += "".join(f'<li class="small">Notifications didn\'t turn on ({_when(f["at"])}, {esc(f["device"])}): '
                       f'{esc(f["error"])}</li>' for f in reversed(r["push_fails"]))
    details += "".join(f'<li class="small">Face ID failed ({_when(f["at"])}, {esc(f["device"])}): {esc(f["error"])}</li>'
                       for f in reversed(r["pk_fails"]))
    gone = list(reversed(_meta_json("sessions:out", [])))
    gone_list = "".join(f'<li class="small"><b>{esc(device_name(d))}</b> · signed out {_when(d["out_at"])}'
                        f'<div class="muted">{esc(device_facts(d))}, IP {esc(d.get("ip") or "?")}</div></li>' for d in gone)
    return ('<section class="card stack" id="devices" aria-label="Devices"><div class="brow"><h2>Devices</h2>'
            + (f'<button class="btn ghost small" type="button" data-signout="*">Sign out all others</button>'
               if len(devs) > 1 else "") + '</div>'
            '<p class="muted small">Everything signed in to Theta. Name your own devices, so anything '
            'marked <b>Not named</b> is one you should look at; sign out anything you don\'t recognize. '
            'Phones don\'t tell websites their names, so the hub only sees the kind of device and where it is.</p>'
            f'<ul class="list">{rows or "<li class=empty>None yet.</li>"}</ul>'
            + (f'<details class="small"><summary class="muted">Details: where and how each signed in</summary>'
               f'<p class="muted small">Locations are rough: phones on cellular data often show the carrier\'s hub. '
               'To cut off anything not listed, change <code>DASHBOARD_KEY</code> in Vercel and redeploy.</p>'
               f'<ul class="list">{details}</ul></details>' if details else "")
            + (f'<details class="small"><summary class="muted">Signed out recently ({len(gone)})</summary>'
               f'<ul class="list">{gone_list}</ul></details>' if gone else "")
            + f'<p class="note"></p><script>{_DEVICES_JS}</script></section>')


def passkeys_card(headers=None):
    lock_on = bool((current_session(headers or {}) or {}).get("lock"))
    rows = "".join(
        f'<li><div class="brow" style="align-items:center"><span>{html.escape(k["name"])}</span>'
        f'<button class="btn ghost small" type="button" data-pk-remove="{html.escape(k["id"])}">Remove</button></div>'
        f'<div class="muted small">Added {datetime.fromtimestamp(k["created"], hub_tz()):%b %d}'
        + (f', last used {datetime.fromtimestamp(k["used"], hub_tz()):%b %d %H:%M}' if k.get("used") else "")
        + (f' · for {html.escape(k["site"])}' if k.get("site") else "")
        + (f'<br><b style="color:var(--warn)">Made for {html.escape(k["site"])}, so it won\'t work at this address '
           f'({html.escape(_rp(headers)[0])}). Open Theta at {html.escape(k["site"])}, or add this device again here.</b>'
           if headers and k.get("site") and k["site"] != _rp(headers)[0] else "")
        + "</div></li>" for k in passkeys())
    return ('<section class="card stack" id="faceid"><div><h2>Sign in with Face ID</h2><p class="muted small">Add this '
            'device and Theta opens with Face ID (or Touch ID, or your passcode) instead of the key in a link. Your face '
            'never leaves your phone; Theta only checks a signature. Passkeys sync through iCloud Keychain to your other '
            'Apple devices.</p></div>'
            '<div style="display:flex;gap:8px;flex-wrap:wrap"><input id="pk-name" class="field" style="flex:1;min-width:160px" '
            'placeholder="Name, like iPhone" aria-label="Device name"><button class="btn" id="pk-add" type="button">'
            'Add this device</button></div><p class="note" id="pk-status"></p>'
            f'<ul class="list">{rows or "<li class=empty>No devices yet.</li>"}</ul>'
            + ((f'<div class="stack" style="gap:6px"><h3>Face ID lock on this device</h3><p class="muted small">Asks for Face ID '
                f'every time Theta comes back after being in the background (a glance of under {LOCK_GRACE} seconds, like '
                'checking a notification, doesn\'t count). Until it passes, Theta shows nothing and the hub answers nothing '
                'from this device.</p>'
                + ('<p><span class="chip ok-t">On</span> <button class="btn ghost small" id="lock-set" type="button" data-on="0">'
                   'Turn off</button></p>' if lock_on else
                   '<p><button class="btn" id="lock-set" type="button" data-on="1">Ask for Face ID when Theta opens</button></p>')
                + '<p class="note" id="lock-status"></p></div>') if rows else "")
            + '</section>'
            f"<script>{_PASSKEY_JS}</script>")
