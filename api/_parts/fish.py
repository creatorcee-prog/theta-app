"""Theta's voice on Fish Audio (2026-11-04). Part of api/index.py, loaded INTO its namespace by
_load_part() (see store.py).

Fish Audio's S2.1 Pro voices, over its API (FISH_AUDIO_API_KEY in Vercel, Sensitive). The free model
(s2.1-pro-free) is tried first. When it's busy or out, the paid one (s2.1-pro, $15 per million
characters) is used only up to the monthly cap you set in Settings, $0 by default (free only). When
neither can speak, the Head page falls back to Piper on the phone and says why. You pick the voice in
Settings from Fish Audio's public library (top-rated English voices, with samples to play)."""

FISH_KEY_ENV = "FISH_AUDIO_API_KEY"
FISH_API = "https://api.fish.audio"
FISH_FREE_MODEL = os.environ.get("FISH_FREE_MODEL", "s2.1-pro-free").strip()
FISH_PAID_MODEL = os.environ.get("FISH_PAID_MODEL", "s2.1-pro").strip()
FISH_PER_MILLION = 15.0  # dollars per million UTF-8 bytes on the paid model (docs.fish.audio, 2026-11)
FISH_SAY_MAX = 600  # characters a request: a sentence or two
FISH_CAP_MAX = 50.0  # the most the monthly cap can be set to, in dollars
_FISH_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def fish_key():
    return os.environ.get(FISH_KEY_ENV, "").strip()


def fish_cfg():
    """{"voice": id, "name": title, "cap": dollars a month for the paid model}."""
    c = _meta_json("fish:cfg", {})
    return {"voice": c.get("voice") or "", "name": c.get("name") or "", "cap": float(c.get("cap") or 0),
            "keep": c.get("keep") or [], "seeded": bool(c.get("seeded")), "page": int(c.get("page") or 1)}


FISH_KEEP_MAX = 12


def _keep_item(v):
    """One kept voice as the list shows it, checked (the page sends these back)."""
    if not isinstance(v, dict) or not _FISH_ID.match(str(v.get("id") or "")):
        raise ValueError("that isn't a Fish Audio voice id")
    sample = str(v.get("sample") or "")
    return {"id": v["id"], "name": " ".join(str(v.get("name") or "Untitled").split())[:60],
            "about": " ".join(str(v.get("about") or "").split())[:140],
            "sample": sample if sample.startswith("https://") else "", "uses": int(v.get("uses") or 0)}


def fish_set(voice=None, name=None, cap=None, keep=None, seeded=None, page=None):
    c = fish_cfg()
    if page is not None:  # where the list of new voices starts (Swap moves it on), so a reload doesn't bring old ones back
        try:
            c["page"] = max(1, min(int(page), 20))
        except (TypeError, ValueError):
            raise ValueError("page must be a number")
    if keep is not None:
        if not isinstance(keep, list) or len(keep) > FISH_KEEP_MAX:
            raise ValueError(f"keep at most {FISH_KEEP_MAX} voices")
        c["keep"] = list({k["id"]: k for k in map(_keep_item, keep)}.values())
    if seeded is not None:
        c["seeded"] = bool(seeded)
    if voice is not None:
        if voice and not _FISH_ID.match(voice):
            raise ValueError("that isn't a Fish Audio voice id")
        c["voice"], c["name"] = voice, " ".join(str(name or "").split())[:60]
    if cap is not None:
        try:
            cap = float(cap)
        except (TypeError, ValueError):
            raise ValueError("the cap is a number of dollars")
        if not 0 <= cap <= FISH_CAP_MAX:
            raise ValueError(f"the cap is between $0 and ${FISH_CAP_MAX:.0f} a month")
        c["cap"] = round(cap, 4)
    store().set_meta("fish:cfg", json.dumps(c))
    return c


def fish_usage(now=None):
    """This month's use: characters on the free and paid models, and what the paid ones cost."""
    month = datetime.fromtimestamp(now or time.time(), hub_tz()).strftime("%Y-%m")
    u = _meta_json("fish:used", {})
    if u.get("month") != month:
        u = {"month": month, "free": 0, "paid": 0}
    u["cost"] = round(u.get("paid", 0) * FISH_PER_MILLION / 1e6, 4)
    return u


def _fish_count(kind, n):
    try:
        u = fish_usage()
        u[kind] = u.get(kind, 0) + n
        u.pop("cost", None)
        store().set_meta("fish:used", json.dumps(u))
    except Exception:
        pass  # never let a count cost a reply


def _fish_post(model, text, voice):
    body = {"text": text, "reference_id": voice, "format": "mp3", "mp3_bitrate": 64, "latency": "balanced", "normalize": True}
    req = urllib.request.Request(f"{FISH_API}/v1/tts", method="POST", data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {fish_key()}", "Content-Type": "application/json", "model": model, "User-Agent": "bot-hub/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            audio = resp.read()
    except urllib.error.HTTPError as e:
        raw = e.read()[:2000].decode("utf-8", "replace")
        try:
            why = str(json.loads(raw).get("message") or raw)[:200]
        except ValueError:
            why = raw[:200]
        err = LLMError({401: "Fish Audio didn't accept the key (check FISH_AUDIO_API_KEY in Vercel)",
                        402: "Fish Audio says the account needs credit",
                        429: "Fish Audio is busy (too many at once)",
                        503: "Fish Audio is overloaded right now"}.get(e.code, f"Fish Audio said {e.code}") + f": {why}")
        err.status = e.code
        raise err
    except (urllib.error.URLError, TimeoutError) as e:
        err = LLMError(f"Fish Audio didn't answer: {type(e).__name__}")
        err.status = 0
        raise err
    if not audio:
        raise LLMError("Fish Audio sent back no audio")
    return audio


def fish_say(text, voice=None):
    """MP3 bytes of `text` in the chosen Fish Audio voice: the free model first, then the paid one within the cap."""
    text = " ".join((text or "").split())
    if not text:
        raise ValueError("nothing to say")
    if len(text) > FISH_SAY_MAX:
        raise ValueError(f"send at most {FISH_SAY_MAX} characters at a time")
    if not fish_key():
        raise LLMError(f"{FISH_KEY_ENV} isn't set in Vercel yet")
    cfg = fish_cfg()
    voice = voice or cfg["voice"]
    if not voice or not _FISH_ID.match(voice):
        raise ValueError("no Fish Audio voice picked yet (Settings, Theta's voice)")
    try:
        audio = _fish_post(FISH_FREE_MODEL, text, voice)
        _fish_count("free", len(text.encode()))
        return audio
    except LLMError as e:
        if getattr(e, "status", None) == 401:
            raise
        first = e
    n = len(text.encode())
    if fish_usage()["cost"] + n * FISH_PER_MILLION / 1e6 > cfg["cap"]:
        err = LLMError(str(first) + (". The paid voice is off (cap $0 in Settings)" if not cfg["cap"]
                                     else f". This month's ${cfg['cap']:.2f} cap for the paid voice is used up"))
        err.status = 429  # out for now: the page falls back to Piper
        raise err
    audio = _fish_post(FISH_PAID_MODEL, text, voice)
    _fish_count("paid", n)
    return audio


def fish_voices(q="", page=1):
    """Top-rated public English voices on Fish Audio, with a sample to play: [{id, name, about, sample, image}]."""
    if not fish_key():
        raise LLMError(f"{FISH_KEY_ENV} isn't set in Vercel yet")
    q = " ".join(str(q or "").split())[:60]
    page = max(1, min(int(page or 1), 20))
    cache_key = f"fish:voices:{q.lower()}:{page}"
    hit = _meta_json(cache_key, {})
    if hit.get("at", 0) > time.time() - 86400:
        return hit["items"]
    params = {"page_size": 12, "page_number": page, "language": "en", "sort_by": "score"}
    if q:
        params["title"] = q
    req = urllib.request.Request(f"{FISH_API}/model?" + urlencode(params), headers={
        "Authorization": f"Bearer {fish_key()}", "User-Agent": "bot-hub/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise LLMError(f"Fish Audio's voice list said {e.code}")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise LLMError(f"Fish Audio's voice list didn't answer: {type(e).__name__}")
    items = []
    for m in out.get("items") or []:
        vid = str(m.get("_id") or "")
        if not _FISH_ID.match(vid):
            continue
        sample = next((s.get("audio") for s in m.get("samples") or [] if str(s.get("audio") or "").startswith("https://")), "")
        image = str(m.get("cover_image") or "")
        items.append({"id": vid, "name": str(m.get("title") or "Untitled")[:60],
                      "about": " ".join(str(m.get("description") or "").split())[:140],
                      "sample": sample, "image": image if image.startswith("https://") else "",
                      "uses": int(m.get("task_count") or 0)})
    store().set_meta(cache_key, json.dumps({"at": time.time(), "items": items}))
    return items


FISH_SAMPLE_MAX = 4_000_000  # bytes: a sample is a few seconds


def fish_sample_ok(url):
    """Only Fish Audio's own https addresses are fetched for a sample (so this can't be used to reach anything else)."""
    try:
        u = urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and not u.port and (host == "fish.audio" or host.endswith(".fish.audio"))


def fish_sample(url):
    """A voice sample's audio bytes, fetched on the server when the browser can't read it directly (for effects)."""
    if not fish_sample_ok(url):
        raise ValueError("not a Fish Audio sample address")
    req = urllib.request.Request(url, headers={"User-Agent": "bot-hub/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if not fish_sample_ok(resp.geturl()):  # followed a redirect somewhere else
                raise ValueError("the sample moved off Fish Audio")
            kind = (resp.headers.get("Content-Type") or "audio/mpeg").split(";")[0]
            data = resp.read(FISH_SAMPLE_MAX + 1)
    except urllib.error.HTTPError as e:
        raise LLMError(f"Fish Audio's sample said {e.code}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise LLMError(f"Fish Audio's sample didn't answer: {type(e).__name__}")
    if len(data) > FISH_SAMPLE_MAX:
        raise ValueError("that sample is too big")
    if not kind.startswith("audio/"):
        kind = "audio/mpeg"
    return kind, data


def fish_card():
    """Settings: pick Theta's Fish Audio voice (listen first), and the paid voice's monthly cap."""
    on, cfg, u = bool(fish_key()), fish_cfg(), fish_usage()
    if not on:
        return ('<section class="card stack" id="voice"><h2>Theta’s voice (Fish Audio)</h2><p class="muted small">Add '
                f'<code>{FISH_KEY_ENV}</code> in Vercel (Settings, Environment Variables, Sensitive on), then redeploy. '
                'After that, pick a voice here. Until then Theta speaks with Piper on your phone.</p></section>')
    now = (f'Theta speaks as <b>{html.escape(cfg["name"] or cfg["voice"])}</b>.' if cfg["voice"]
           else 'No voice picked yet: Theta speaks with Piper until you pick one below.')
    return ('<section class="card stack" id="voice"><h2>Theta’s voice (Fish Audio)</h2>'
            f'<p class="small" id="fish-now">{now}</p>'
            '<p class="muted small">Play a sample, then tap <b>Use</b>. <b>Keep</b> pins a voice to the top; <b>Swap the rest</b> '
            'replaces the others with voices you haven\u2019t heard. The free model speaks first; if it’s busy, the paid '
            'one can step in up to your monthly cap. If neither can, Theta uses Piper on your phone.</p>'
            '<div class="brow" style="gap:8px;flex-wrap:wrap"><input class="field" id="fish-q" placeholder="Search voices (like: british, calm, deep)" '
            'style="flex:1;min-width:180px"><button class="btn" type="button" id="fish-go">Search</button></div>'
            '<div class="brow" style="gap:8px;align-items:center;flex-wrap:wrap"><label class="small">Effect <select class="field" id="fish-fx" '
            'style="width:auto">' + "".join(f'<option value="{k}">{html.escape(v)}</option>' for k, v in VOICE_FX.items()) + '</select></label>'
            '<label class="small">Strength <input type="range" id="fish-fx-amt" min="10" max="100" value="60"></label>'
            '<span class="muted small">Samples play with it, and so does Theta.</span></div>'
            '<div id="fish-list" class="stack" style="gap:8px"><p class="muted small">Loading the top voices…</p></div>'
            '<p class="brow" style="gap:8px;margin:0"><button class="btn" type="button" id="fish-swap" hidden>Swap the rest for new voices</button>'
            '<button class="btn" type="button" id="fish-more" hidden>More voices</button></p>'
            '<div class="brow" style="gap:8px;align-items:center;flex-wrap:wrap"><label class="small" for="fish-cap">Paid voice cap, per month: $</label>'
            f'<input class="field" id="fish-cap" type="number" min="0" max="{FISH_CAP_MAX:.0f}" step="0.5" value="{cfg["cap"]:g}" style="width:90px">'
            '<button class="btn" type="button" id="fish-save">Save</button><span class="note small" id="fish-note"></span></div>'
            f'<p class="muted small">This month: {u.get("free", 0):,} characters free, {u.get("paid", 0):,} paid '
            f'(${u["cost"]:.2f}). $1 is about 66,000 characters, around 440 spoken replies.</p>'
            f"<script>window.FISH_CFG={json.dumps({'keep': cfg['keep'], 'seeded': cfg['seeded'], 'voice': cfg['voice'], 'page': cfg['page']}).replace('</', '<\\/')};"
            + _FISH_JS + "</script></section>")


_FISH_JS = r"""
(() => {
  const list = document.getElementById("fish-list"), q = document.getElementById("fish-q"), more = document.getElementById("fish-more");
  const swap = document.getElementById("fish-swap"), note = document.getElementById("fish-note"), nowEl = document.getElementById("fish-now");
  const CFG = window.FISH_CFG || {keep: [], seeded: false};
  let keep = CFG.keep.slice(), shown = [], seen = new Set(keep.map(v => v.id)), page = 1, playing = null;
  const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };
  const post = body => fetch("/api/voice/fish/config", {method: "POST", headers: window.THETA_H, body: JSON.stringify(body)}).then(r => r.json());
  const kept = id => keep.some(k => k.id === id);
  // the effect: the same one Theta speaks with (saved on this device; the Theta page has it too)
  const fxSel = document.getElementById("fish-fx"), fxAmt = document.getElementById("fish-fx-amt");
  const fxInit = () => { const F = window.thetaFx; if (!F) return; // the page script (ui.js) loads after this one
    fxSel.value = F.kind(); if (!fxSel.value) fxSel.value = "off"; fxAmt.value = F.amount();
    fxSel.onchange = () => F.set(fxSel.value); fxAmt.onchange = () => F.set(null, fxAmt.value); };
  if (window.thetaFx) fxInit(); else addEventListener("DOMContentLoaded", fxInit);
  const sampleCache = new Map();
  async function sampleBlob(url) { // straight from Fish Audio if it allows it, else through the hub
    if (sampleCache.has(url)) return sampleCache.get(url);
    let blob = null;
    try { const r = await fetch(url, {mode: "cors"}); if (r.ok) blob = await r.blob(); } catch (e) {}
    if (!blob) { const r = await fetch("/api/voice/fish/sample?url=" + encodeURIComponent(url), {headers: window.THETA_H}); if (!r.ok) throw new Error("sample " + r.status); blob = await r.blob(); }
    sampleCache.set(url, blob); return blob;
  }
  async function playSample(url, btn) {
    if (playing) { playing.pause(); playing = null; }
    const plain = () => { playing = new Audio(url); playing.play().catch(() => {}); };
    const FXN = window.thetaFx;
    if (!FXN || fxSel.value === "off") return plain();
    const was = btn.textContent; btn.textContent = "\u2026"; btn.disabled = true;
    try {
      const out = await FXN.render(await sampleBlob(url), fxSel.value, fxAmt.value), u = URL.createObjectURL(out);
      playing = new Audio(u); playing.onended = () => URL.revokeObjectURL(u); await playing.play();
    } catch (e) { note.textContent = "Played without the effect (" + e.message + ")."; plain(); }
    finally { btn.textContent = was; btn.disabled = false; }
  }
  async function fetchPage(p) {
    const d = await (await fetch("/api/voice/fish/voices?q=" + encodeURIComponent(q.value) + "&page=" + p, {headers: window.THETA_H})).json();
    if (!d.ok) throw new Error(d.error); return d.voices;
  }
  function row(v) {
    const r = el("div", "brow"); r.style.cssText = "gap:8px;align-items:center;border-top:1px solid var(--border);padding-top:8px";
    const txt = el("div"); txt.style.cssText = "flex:1;min-width:0";
    txt.append(el("b", null, (kept(v.id) ? "\u2605 " : "") + v.name), el("div", "muted small", v.about || (v.uses.toLocaleString() + " uses")));
    const play = el("button", "btn", "\u25B6"); play.type = "button"; play.disabled = !v.sample; play.title = "Play a sample";
    play.onclick = () => playSample(v.sample, play);
    const pin = el("button", "btn", kept(v.id) ? "Kept" : "Keep"); pin.type = "button";
    pin.onclick = async () => {
      keep = kept(v.id) ? keep.filter(k => k.id !== v.id) : keep.concat([v]).slice(-12);
      const d = await post({keep}); if (!d.ok) { note.textContent = d.error; return; } draw();
    };
    const use = el("button", "btn", CFG.voice === v.id ? "In use" : "Use"); use.type = "button";
    use.onclick = async () => {
      const d = await post({voice: v.id, name: v.name}); if (!d.ok) { note.textContent = d.error; return; }
      CFG.voice = v.id;
      try { localStorage.setItem("theta:voice", "fish:" + v.id); localStorage.setItem("theta:fishName", v.name); } catch (e) {}
      nowEl.replaceChildren("Theta speaks as ", el("b", null, v.name), "."); note.textContent = "Saved. Theta uses " + v.name + " from now on."; draw();
    };
    r.append(txt, play, pin, use); return r;
  }
  function draw() {
    const rest = shown.filter(v => !kept(v.id));
    list.replaceChildren(...keep.map(row), ...rest.map(row));
    if (!keep.length && !rest.length) list.append(el("p", "muted small", "No voices found. Try another word."));
    swap.hidden = !rest.length; more.hidden = !shown.length;
  }
  async function fresh(n, save = true) { // n voices not heard yet, from the next pages
    const out = [], from = page;
    for (let tries = 0; out.length < n && tries < 4; tries++) {
      const vs = await fetchPage(page++);
      vs.forEach(v => { if (!seen.has(v.id) && out.length < n) { seen.add(v.id); out.push(v); } });
      if (vs.length < 12) break;
    }
    if (save && !q.value) post({page: from}); // a reload shows these, not the ones swapped away
    return out;
  }
  async function load() {
    page = !q.value && CFG.seeded ? (CFG.page || 1) : 1; seen = new Set(keep.map(v => v.id));
    list.replaceChildren(el("p", "muted small", "Loading\u2026"));
    try {
      const first = await fetchPage(page++);
      if (!CFG.seeded && !q.value) { // once: keep Ethan and Egirl, swap the rest (asked for 2026-11-04)
        CFG.seeded = true;
        const pick = first.filter(v => /^\s*(ethan|e[\s-]?girl)\b/i.test(v.name) && !kept(v.id));
        keep = keep.concat(pick).slice(-12); first.forEach(v => seen.add(v.id));
        await post({keep, seeded: true});
        shown = pick.length ? await fresh(12 - keep.length) : first;
      } else {
        shown = first.filter(v => !kept(v.id)); shown.forEach(v => seen.add(v.id));
      }
      draw();
    } catch (e) { list.replaceChildren(el("p", "muted small", "Couldn\u2019t load voices: " + e.message)); }
  }
  swap.onclick = async () => {
    swap.disabled = true;
    try { shown = await fresh(Math.max(1, 12 - keep.length)); draw(); note.textContent = shown.length ? "" : "No more new voices for that search."; }
    catch (e) { note.textContent = e.message; } finally { swap.disabled = false; }
  };
  more.onclick = async () => { try { shown = shown.concat(await fresh(12, false)); draw(); } catch (e) { note.textContent = e.message; } };
  document.getElementById("fish-go").onclick = load;
  q.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); load(); } });
  document.getElementById("fish-save").onclick = async () => {
    const d = await post({cap: Number(document.getElementById("fish-cap").value || 0)}); note.textContent = d.ok ? "Cap saved." : d.error;
  };
  load();
})();
"""
