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
    return {"voice": c.get("voice") or "", "name": c.get("name") or "", "cap": float(c.get("cap") or 0)}


def fish_set(voice=None, name=None, cap=None):
    c = fish_cfg()
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
            '<p class="muted small">Play a sample, then tap <b>Use</b>. The free model speaks first; if it’s busy, the paid '
            'one can step in up to your monthly cap. If neither can, Theta uses Piper on your phone.</p>'
            '<div class="brow" style="gap:8px;flex-wrap:wrap"><input class="field" id="fish-q" placeholder="Search voices (like: british, calm, deep)" '
            'style="flex:1;min-width:180px"><button class="btn" type="button" id="fish-go">Search</button></div>'
            '<div id="fish-list" class="stack" style="gap:8px"><p class="muted small">Loading the top voices…</p></div>'
            '<button class="btn" type="button" id="fish-more" hidden>More voices</button>'
            '<div class="brow" style="gap:8px;align-items:center;flex-wrap:wrap"><label class="small" for="fish-cap">Paid voice cap, per month: $</label>'
            f'<input class="field" id="fish-cap" type="number" min="0" max="{FISH_CAP_MAX:.0f}" step="0.5" value="{cfg["cap"]:g}" style="width:90px">'
            '<button class="btn" type="button" id="fish-save">Save</button><span class="note small" id="fish-note"></span></div>'
            f'<p class="muted small">This month: {u.get("free", 0):,} characters free, {u.get("paid", 0):,} paid '
            f'(${u["cost"]:.2f}). $1 is about 66,000 characters, around 440 spoken replies.</p>'
            "<script>" + _FISH_JS + "</script></section>")


_FISH_JS = r"""
(() => {
  const list = document.getElementById("fish-list"), q = document.getElementById("fish-q"), more = document.getElementById("fish-more");
  const note = document.getElementById("fish-note"), nowEl = document.getElementById("fish-now");
  let page = 1, playing = null;
  const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };
  async function load(reset) {
    if (reset) { page = 1; list.replaceChildren(el("p", "muted small", "Loading…")); }
    try {
      const d = await (await fetch("/api/voice/fish/voices?q=" + encodeURIComponent(q.value) + "&page=" + page, {headers: window.THETA_H})).json();
      if (!d.ok) throw new Error(d.error);
      if (reset) list.replaceChildren();
      if (!d.voices.length && reset) list.append(el("p", "muted small", "No voices found. Try another word."));
      d.voices.forEach(v => {
        const row = el("div", "brow"); row.style.cssText = "gap:10px;align-items:center;border-top:1px solid var(--border);padding-top:8px";
        const txt = el("div"); txt.style.cssText = "flex:1;min-width:0";
        txt.append(el("b", null, v.name), el("div", "muted small", v.about || (v.uses.toLocaleString() + " uses")));
        const play = el("button", "btn", "▶"); play.type = "button"; play.disabled = !v.sample; play.title = "Play a sample";
        play.onclick = () => { if (playing) playing.pause(); playing = new Audio(v.sample); playing.play().catch(() => {}); };
        const use = el("button", "btn", "Use"); use.type = "button";
        use.onclick = async () => {
          const r = await (await fetch("/api/voice/fish/config", {method: "POST", headers: window.THETA_H, body: JSON.stringify({voice: v.id, name: v.name})})).json();
          if (!r.ok) { note.textContent = r.error; return; }
          try { localStorage.setItem("theta:voice", "fish:" + v.id); localStorage.setItem("theta:fishName", v.name); } catch (e) {}
          nowEl.innerHTML = ""; nowEl.append("Theta speaks as ", el("b", null, v.name), ".");
          note.textContent = "Saved. Theta uses " + v.name + " from now on.";
        };
        row.append(txt, play, use); list.append(row);
      });
      more.hidden = d.voices.length < 12;
    } catch (e) { list.replaceChildren(el("p", "muted small", "Couldn’t load voices: " + e.message)); }
  }
  document.getElementById("fish-go").onclick = () => load(true);
  q.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); load(true); } });
  more.onclick = () => { page++; load(false); };
  document.getElementById("fish-save").onclick = async () => {
    const r = await (await fetch("/api/voice/fish/config", {method: "POST", headers: window.THETA_H,
      body: JSON.stringify({cap: Number(document.getElementById("fish-cap").value || 0)})})).json();
    note.textContent = r.ok ? "Cap saved." : r.error;
  };
  load(true);
})();
"""
