"""Theta's voice: Orpheus on Groq (Stage 8.4b). Part of api/index.py, loaded
INTO its namespace by _load_part() (see store.py).

Orpheus (Canopy Labs, Apache-2.0) is the most natural of the free voices,
hosted by Groq on the key the hub already has (GROQ_API_KEY). Its free
tier takes up to ORPHEUS_MAX characters a request, so the Head page sends a
reply a sentence or two at a time (spoken replies are ~30 words: usually
one request). When Groq says no (the day's free uses are spent, or the
model's terms haven't been accepted), the page falls back to the phone's
own voice and says why."""

ORPHEUS_MODEL = os.environ.get("ORPHEUS_MODEL", "canopylabs/orpheus-v1-english").strip()
ORPHEUS_VOICES = ("troy", "daniel", "austin", "autumn", "diana", "hannah")  # Groq's Orpheus English voices
ORPHEUS_MAX = 200  # characters per request on Groq's free tier


def orpheus_say(text, voice):
    """WAV bytes of `text` in `voice`; LLMError (with Groq's reason) when it can't."""
    text = " ".join((text or "").split())
    if not text:
        raise ValueError("nothing to say")
    if len(text) > ORPHEUS_MAX:
        raise ValueError(f"send at most {ORPHEUS_MAX} characters at a time")
    if voice not in ORPHEUS_VOICES:
        raise ValueError(f"unknown voice {voice!r} (one of: {', '.join(ORPHEUS_VOICES)})")
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        raise LLMError("GROQ_API_KEY isn't set")
    url = PROVIDERS["groq"][0].rsplit("/chat/completions", 1)[0] + "/audio/speech"
    req = urllib.request.Request(url, method="POST", data=json.dumps(
        {"model": ORPHEUS_MODEL, "input": text, "voice": voice, "response_format": "wav"}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "bot-hub/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            audio = resp.read()
    except urllib.error.HTTPError as e:
        raw = e.read()[:2000].decode("utf-8", "replace")
        why = _llm_error_text("groq", e.code, raw)
        if e.code == 429:
            why = "Theta's Groq voice is out of free uses for now (" + why + ")"
        elif "terms" in raw.lower():
            why = ("Groq needs you to accept the Orpheus model's terms once: console.groq.com, Playground, pick "
                   f"{ORPHEUS_MODEL}, accept (" + why + ")")
        err = LLMError(why)
        err.status = e.code
        raise err
    except (urllib.error.URLError, TimeoutError) as e:
        raise LLMError(f"Groq's voice didn't answer: {type(e).__name__}")
    if not audio:
        raise LLMError("Groq's voice sent back no audio")
    try:  # a count for the day, so Diagnostics can say how much was used
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        used = _meta_json("voice:used", {})
        store().set_meta("voice:used", json.dumps({day: used.get(day, 0) + 1}))
    except Exception:
        pass
    return audio
