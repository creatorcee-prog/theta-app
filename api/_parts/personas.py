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
        'Pick one and it takes over at once. "Theta" is the original.</p></div>'
        '<div class="field"><label for="pa-pick">Active</label><select id="pa-pick"><option value="">Theta (original)</option></select></div>'
        '<div style="display:flex;gap:8px;flex-wrap:wrap"><button type="button" class="btn small" id="pa-new">New persona</button>'
        '<button type="button" class="btn ghost small" id="pa-edit-btn" hidden>Edit this one</button></div>'
        '<div class="stack" id="pa-form" hidden style="margin-top:4px"><h3 id="pa-form-title" style="margin:0">New persona</h3>'
        '<div class="field"><label for="pa-name">Name</label><input id="pa-name" maxlength="40" placeholder="Like: Simaris"></div>'
        '<div class="field"><label for="pa-addr">What it calls you</label><input id="pa-addr" maxlength="40" placeholder="Like: Hunter"></div>'
        '<div class="field"><label for="pa-soul">Personality</label><textarea id="pa-soul" rows="7" maxlength="4000" '
        'placeholder="How it talks and what it cares about, in your words. Empty keeps Theta\'s own."></textarea></div>'
        '<div class="field"><label for="pa-av">Avatar</label><select id="pa-av"><option value="">As it is now</option>'
        '<option value="precision">Precision</option><option value="lumen">Lumen</option><option value="flow">Flow</option>'
        '<option value="signal">Signal</option><option value="urchin">Urchin Pour</option><option value="rings">Classic rings</option>'
        '<option value="image">My pictures</option></select></div>'
        '<label class="small"><input type="checkbox" id="pa-look" checked> Save the voice, voice effect and avatar I have on right now</label>'
        '<label class="small"><input type="checkbox" id="pa-ui"> ...and the theme, frame and background too</label>'
        '<div style="display:flex;gap:8px;flex-wrap:wrap"><button type="button" class="btn" id="pa-save">Save</button>'
        '<button type="button" class="btn ghost" id="pa-cancel">Cancel</button>'
        '<button type="button" class="btn ghost" id="pa-del" hidden>Delete this one</button></div></div>'
        '<p class="muted small" id="pa-note" role="status"></p></section>'
        f"<script>{PERSONA_JS}</script>")


PERSONA_JS = r"""
(() => {
  // Personas (2026-11-07): New persona always starts empty and never touches the one you're on; Edit changes the
  // active one. Saving a new persona switches to it. A switch takes effect at once: the server speaks as it from the
  // next message, and this phone wears its voice, effect and avatar without a reload (only its own theme reloads).
  const H = window.THETA_H || {}, $ = id => document.getElementById(id), pick = $("pa-pick"); if (!pick) return;
  const KEYS = {voice: "theta:voice", fx: "theta:fx", fxAmt: "theta:fxAmt", avatar: "theta:avatar", avimg: "theta:avimg"};
  const ls = {get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} }};
  const note = t => { const n = $("pa-note"); if (n) n.textContent = t || ""; }, val = (id, v) => { const e = $(id); if (e) e.value = v; };
  const uiNow = () => (document.cookie.match(/(?:^|; )theta_ui=([^;]*)/) || [])[1] || "";
  let list = [], active = "", editing = "";
  async function load() {
    const d = await (await fetch("/api/personas", {headers: H})).json(); if (!d.ok) return;
    list = d.personas; active = d.active;
    pick.replaceChildren(new Option("Theta (original)", ""), ...list.map(p => new Option(p.name + (p.address ? " · calls you " + p.address : ""), p.id)));
    pick.value = active; const e = $("pa-edit-btn"); if (e) { e.hidden = !active; const p = list.find(x => x.id === active); if (p) e.textContent = "Edit " + p.name; }
  }
  function open(p) { editing = p ? p.id : ""; const f = $("pa-form"); if (!f) return; f.hidden = false;
    $("pa-form-title").textContent = p ? "Editing " + p.name : "New persona";
    val("pa-name", p ? p.name : ""); val("pa-addr", p ? p.address : ""); val("pa-soul", p ? p.soul : ""); val("pa-av", "");
    $("pa-del").hidden = !p; $("pa-name").focus(); }
  const close = () => { const f = $("pa-form"); if (f) f.hidden = true; editing = ""; };
  // wear a look on this phone; tell every open part of the app (Theta's screen too) so it changes now
  function wear(look, name) {
    for (const [k, key] of Object.entries(KEYS)) if (look && k in look) ls.set(key, look[k]);
    if (look && look.ui && look.ui !== uiNow()) { document.cookie = "theta_ui=" + look.ui + ";path=/;max-age=31536000;samesite=lax"; (window.top || window).location.reload(); return; }
    const ev = () => new CustomEvent("theta:persona", {detail: {name: name || "Theta"}});
    window.dispatchEvent(ev()); try { if (window.top && window.top !== window) window.top.dispatchEvent(ev()); } catch (e) {}
  }
  const snapshot = () => { const look = {}; for (const [k, key] of Object.entries(KEYS)) { const v = ls.get(key); if (v != null) look[k] = v; }
    look.ui = uiNow(); return look; };
  async function switchTo(id) {
    note("Switching…");
    if (!active) ls.set("theta:originalLook", JSON.stringify(snapshot())); // leaving the original: keep its look on this phone
    const d = await (await fetch("/api/personas/activate", {method: "POST", headers: H, body: JSON.stringify({id})})).json();
    if (!d.ok) { note(d.error || "Couldn't switch."); pick.value = active; return; }
    let look = d.look || {};
    if (!id) { try { look = JSON.parse(ls.get("theta:originalLook") || "{}"); } catch (e) { look = {}; } } // back to Theta: its own look
    await load(); const p = list.find(x => x.id === id);
    wear(look, p ? p.name : "Theta"); note(p ? p.name + " is on." : "Theta is back.");
  }
  pick.addEventListener("change", () => switchTo(pick.value));
  if (!$("pa-save")) { load(); return; } // the quick switcher (Theta's Voice and tools): just the list
  $("pa-new").onclick = () => { open(null); note(""); };
  $("pa-edit-btn").onclick = () => { open(list.find(p => p.id === active)); note(""); };
  $("pa-cancel").onclick = () => { close(); note(""); };
  $("pa-save").onclick = async () => {
    const look = {}, now = snapshot(), isNew = !editing;
    if ($("pa-look").checked) for (const k of Object.keys(KEYS)) if (k in now) look[k] = now[k];
    if ($("pa-ui").checked) look.ui = now.ui;
    if ($("pa-av").value) { let av = {}; try { av = JSON.parse(look.avatar || now.avatar || "{}") || {}; } catch (e) {}
      av.style = $("pa-av").value; look.avatar = JSON.stringify(av); } // this persona's own avatar style
    const body = {id: editing, name: $("pa-name").value, address: $("pa-addr").value, soul: $("pa-soul").value};
    if ($("pa-look").checked || $("pa-ui").checked || $("pa-av").value) body.look = look;
    const d = await (await fetch("/api/personas", {method: "POST", headers: H, body: JSON.stringify(body)})).json();
    if (!d.ok) return note(d.error || "Couldn't save.");
    close();
    if (isNew || d.persona.id === active) await switchTo(d.persona.id); else await load(); // a new one takes over; an edit to the active one applies now
    note((isNew ? "Made " : "Saved ") + d.persona.name + (isNew ? " and switched to it." : ".") + (d.persona.look.includes("avimg") || !look.avimg ? "" : " (Its pictures were too big to keep.)"));
  };
  $("pa-del").onclick = async () => {
    if (!editing || !confirm("Delete this persona? Its personality and saved look go too.")) return;
    const was = editing; await fetch("/api/personas/delete", {method: "POST", headers: H, body: JSON.stringify({id: was})}); close();
    if (was === active) await switchTo(""); else await load(); note("Deleted.");
  };
  load();
})();
"""
