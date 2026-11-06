"""Personas (2026-11-06): who Theta is, kept as swappable sets. A persona is a name, what it calls you, its
personality (in place of SOUL.md), and its look and sound on this phone: voice and voice effect, avatar
(style, size, energy, colors, pictures) and, if you want, its own theme and frame. Swap one in and all of
it changes at once; with none active, Theta is Theta (SOUL.md, today's settings).

Part of api/index.py (loaded into its namespace by _load_part, after vault.py, whose soul_text() this
wraps). Stored in the hub's store as meta "personas" (a list) and "persona:active" (an id)."""

PERSONA_MAX = 12          # saved personas
PERSONA_SOUL_MAX = 4000   # characters of personality, like SOUL.md
PERSONA_LOOK_MAX = 900_000  # the look on the phone (avatar pictures can be big); larger looks keep everything but the pictures
_LOOK_KEYS = ("voice", "fx", "fxAmt", "avatar", "avimg", "ui")


def personas():
    out = _meta_json("personas", [])
    return out if isinstance(out, list) else []


def active_persona():
    pid = store().get_meta("persona:active") or ""
    return next((p for p in personas() if p.get("id") == pid), None) if pid else None


def persona_name():
    p = active_persona()
    return (p or {}).get("name") or "Theta"


def _clean_persona(d, old=None):
    old = old or {}
    name = " ".join(str(d.get("name") or old.get("name") or "").split())[:40]
    if not name:
        raise ValueError("a persona needs a name")
    look = d.get("look") if isinstance(d.get("look"), dict) else old.get("look", {})
    look = {k: str(v)[:PERSONA_LOOK_MAX] for k, v in look.items() if k in _LOOK_KEYS and v is not None}
    if sum(len(v) for v in look.values()) > PERSONA_LOOK_MAX:
        look.pop("avimg", None)  # pictures too big to keep: everything else still saves
    return {"id": old.get("id") or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] + "-" + hashlib.sha1(
                f"{name}{time.time_ns()}".encode()).hexdigest()[:5],
            "name": name,
            "address": " ".join(str(d.get("address", old.get("address", "")) or "").split())[:40],
            "soul": str(d.get("soul", old.get("soul", "")) or "")[:PERSONA_SOUL_MAX],
            "look": look, "updated": time.time()}


def save_persona(d):
    ps = personas()
    old = next((p for p in ps if p.get("id") == d.get("id")), None) if d.get("id") else None
    p = _clean_persona(d, old)
    if old:
        ps = [p if x.get("id") == p["id"] else x for x in ps]
    else:
        if len(ps) >= PERSONA_MAX:
            raise ValueError(f"that's {PERSONA_MAX} personas already: delete one first")
        ps.append(p)
    store().set_meta("personas", json.dumps(ps))
    return p


def activate_persona(pid):
    if pid and not any(p.get("id") == pid for p in personas()):
        raise ValueError("no such persona")
    store().set_meta("persona:active", pid or "")
    return active_persona()


def delete_persona(pid):
    store().set_meta("personas", json.dumps([p for p in personas() if p.get("id") != pid]))
    if (store().get_meta("persona:active") or "") == pid:
        store().set_meta("persona:active", "")


# The personality: the active persona's in place of SOUL.md, with its name and what it calls you said
# outright, so every prompt that reads soul_text() speaks as it.
_soul_text_base = soul_text


def soul_text():
    p = active_persona()
    if not p:
        return _soul_text_base()
    head = f"# {p['name']}\n\nYour name is {p['name']}." + (
        f' Call the user "{p["address"]}" (that\'s how they want to be addressed).' if p.get("address") else "")
    body = p.get("soul", "").strip() or _soul_text_base()
    return head + "\n\n" + body


def persona_summary(p):
    return {k: p.get(k) for k in ("id", "name", "address", "soul")} | {"look": sorted((p.get("look") or {}).keys())}


def personas_route(method, path, data):
    """GET /api/personas, POST /api/personas (save), /api/personas/activate, /api/personas/delete,
    GET /api/personas/look?id= (the full look, to put on this phone)."""
    try:
        if method == "GET" and path == "/api/personas":
            a = active_persona()
            return {"ok": True, "active": (a or {}).get("id", ""), "personas": [persona_summary(p) for p in personas()]}
        if method == "GET" and path == "/api/personas/look":
            p = next((x for x in personas() if x.get("id") == data.get("id")), None)
            return {"ok": bool(p), "look": (p or {}).get("look", {}), "error": "" if p else "no such persona"}
        if method == "POST" and path == "/api/personas":
            return {"ok": True, "persona": persona_summary(save_persona(data))}
        if method == "POST" and path == "/api/personas/activate":
            p = activate_persona(str(data.get("id") or ""))
            return {"ok": True, "active": (p or {}).get("id", ""), "look": (p or {}).get("look", {})}
        if method == "POST" and path == "/api/personas/delete":
            delete_persona(str(data.get("id") or ""))
            return {"ok": True}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "unknown persona route"}


# ---- the Settings card and the switcher's script (shared with the Theta page's Voice and tools)
def persona_card():
    return (
        '<section class="card stack" id="personas"><div><h2>Personas</h2><p class="muted small">Who Theta is, kept as sets you can swap: '
        'a name, what it calls you, its personality, and its voice, voice effect, avatar and (if you like) theme and frame on this phone. '
        'Swap one in and all of it changes at once. "Theta" is the original.</p></div>'
        '<div class="field"><label for="pa-pick">Active</label><select id="pa-pick"><option value="">Theta (original)</option></select></div>'
        '<details id="pa-edit"><summary class="btn ghost small">New persona / edit this one</summary><div class="stack" style="margin-top:10px">'
        '<div class="field"><label for="pa-name">Name</label><input id="pa-name" maxlength="40" placeholder="Like: Simaris"></div>'
        '<div class="field"><label for="pa-addr">What it calls you</label><input id="pa-addr" maxlength="40" placeholder="Like: Hunter"></div>'
        '<div class="field"><label for="pa-soul">Personality</label><textarea id="pa-soul" rows="7" maxlength="4000" '
        'placeholder="How it talks and what it cares about, in your words. Empty keeps Theta\'s own."></textarea></div>'
        '<label class="small"><input type="checkbox" id="pa-look" checked> Save the voice, voice effect and avatar I have on right now</label>'
        '<label class="small"><input type="checkbox" id="pa-ui"> ...and the theme, frame and background too</label>'
        '<div style="display:flex;gap:8px;flex-wrap:wrap"><button type="button" class="btn" id="pa-save">Save persona</button>'
        '<button type="button" class="btn ghost" id="pa-new">Start a new one</button>'
        '<button type="button" class="btn ghost" id="pa-del">Delete this one</button></div></div></details>'
        '<p class="muted small" id="pa-note" role="status"></p></section>'
        f"<script>{PERSONA_JS}</script>")


PERSONA_JS = r"""
(() => {
  const H = window.THETA_H || {}, $ = id => document.getElementById(id), pick = $("pa-pick"); if (!pick) return;
  const KEYS = {voice: "theta:voice", fx: "theta:fx", fxAmt: "theta:fxAmt", avatar: "theta:avatar", avimg: "theta:avimg"};
  const ls = {get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} }};
  const note = t => { const n = $("pa-note"); if (n) n.textContent = t || ""; }, val = (id, v) => { const e = $(id); if (e) e.value = v; };
  let list = [], active = "", editing = "";
  async function load() {
    const d = await (await fetch("/api/personas", {headers: H})).json(); if (!d.ok) return;
    list = d.personas; active = d.active;
    pick.replaceChildren(new Option("Theta (original)", ""), ...list.map(p => new Option(p.name + (p.address ? " · calls you " + p.address : ""), p.id)));
    pick.value = active; fill(list.find(p => p.id === active));
  }
  function fill(p) { editing = p ? p.id : ""; val("pa-name", p ? p.name : ""); val("pa-addr", p ? p.address : ""); val("pa-soul", p ? p.soul : "");
    if ($("pa-del")) $("pa-del").hidden = !p; }
  function apply(look) { // put a persona's look on this phone, then reload so everything wears it
    for (const [k, key] of Object.entries(KEYS)) if (look && k in look) ls.set(key, look[k]);
    if (look && look.ui) document.cookie = "theta_ui=" + look.ui + ";path=/;max-age=31536000;samesite=lax";
    (window.top || window).location.reload();
  }
  const snapshot = () => { const look = {}; for (const [k, key] of Object.entries(KEYS)) { const v = ls.get(key); if (v != null) look[k] = v; }
    look.ui = (document.cookie.match(/(?:^|; )theta_ui=([^;]*)/) || [])[1] || ""; return look; };
  pick.addEventListener("change", async () => {
    note("Switching…");
    if (!active) ls.set("theta:originalLook", JSON.stringify(snapshot())); // leaving the original: keep its look on this phone
    const d = await (await fetch("/api/personas/activate", {method: "POST", headers: H, body: JSON.stringify({id: pick.value})})).json();
    if (!d.ok) { note(d.error || "Couldn't switch."); pick.value = active; return; }
    let look = d.look || {};
    if (!pick.value) { try { look = JSON.parse(ls.get("theta:originalLook") || "{}"); } catch (e) { look = {}; } } // back to Theta: its own look
    apply(look);
  });
  if (!$("pa-save")) { load(); return; } // the quick switcher (Theta's Voice and tools): just the list
  $("pa-new").onclick = () => { fill(null); $("pa-name").focus(); note("A new persona: name it, then save."); };
  $("pa-save").onclick = async () => {
    const look = {};
    const now = snapshot();
    if ($("pa-look").checked) for (const k of Object.keys(KEYS)) if (k in now) look[k] = now[k];
    if ($("pa-ui").checked) look.ui = now.ui;
    const body = {id: editing, name: $("pa-name").value, address: $("pa-addr").value, soul: $("pa-soul").value};
    if ($("pa-look").checked || $("pa-ui").checked) body.look = look;
    const d = await (await fetch("/api/personas", {method: "POST", headers: H, body: JSON.stringify(body)})).json();
    if (!d.ok) return note(d.error || "Couldn't save.");
    note("Saved " + d.persona.name + (d.persona.look.includes("avimg") || !look.avimg ? "." : " (its pictures were too big to keep).")); editing = d.persona.id; load();
  };
  $("pa-del").onclick = async () => {
    if (!editing || !confirm("Delete this persona? Its personality and saved look go too.")) return;
    await fetch("/api/personas/delete", {method: "POST", headers: H, body: JSON.stringify({id: editing})}); fill(null); note("Deleted."); load();
  };
  load();
})();
"""
