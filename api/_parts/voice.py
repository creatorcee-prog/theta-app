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


# ---- Gemini's voices (Google, free tier where the key's plan allows; not open
# source). The current docs show Gemini TTS on the Interactions API; older
# models used generateContent. Both are tried, and the audio is found in the
# reply whichever shape it has, so a docs change doesn't break the voice.
GEMINI_TTS_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts").strip()
GEMINI_VOICES = ("Charon", "Iapetus", "Algieba", "Sulafat", "Gacrux", "Alnilam", "Achird", "Puck", "Kore",
                 "Aoede", "Zephyr", "Algenib")  # a pick of the 30: informative, clear, smooth, warm, mature, ...
GEMINI_SAY_MAX = 600
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _wav(pcm, rate=24000):
    """16-bit mono PCM wrapped as a WAV file."""
    import struct
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


def _find_audio(node):
    """(mime, base64 data) of the first audio part anywhere in a reply."""
    if isinstance(node, dict):
        mime = node.get("mimeType") or node.get("mime_type") or ""
        if (isinstance(node.get("data"), str) and len(node["data"]) > 64
                and (mime.startswith("audio") or (not mime and node.get("type") == "audio"))):
            return mime or "audio/wav", node["data"]
        for v in node.values():
            hit = _find_audio(v)
            if hit:
                return hit
    elif isinstance(node, list):
        for v in node:
            hit = _find_audio(v)
            if hit:
                return hit
    return None


def gemini_say(text, voice):
    """WAV bytes of `text` in one of Gemini's voices."""
    text = " ".join((text or "").split())
    if not text:
        raise ValueError("nothing to say")
    if len(text) > GEMINI_SAY_MAX:
        raise ValueError(f"send at most {GEMINI_SAY_MAX} characters at a time")
    if voice not in GEMINI_VOICES:
        raise ValueError(f"unknown Gemini voice {voice!r}")
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise LLMError("GEMINI_API_KEY isn't set")
    tries = [
        (f"{_GEMINI_BASE}/interactions", {
            "model": GEMINI_TTS_MODEL,
            "input": [{"type": "user_input", "content": [{"type": "text", "text": text}]}],
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": voice}]}}),
        (f"{_GEMINI_BASE}/models/{GEMINI_TTS_MODEL}:generateContent", {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}),
    ]
    last = None
    for url, body in tries:
        req = urllib.request.Request(url, method="POST", data=json.dumps(body).encode(), headers={
            "x-goog-api-key": key, "Content-Type": "application/json", "User-Agent": "bot-hub/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                out = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raw = e.read()[:2000].decode("utf-8", "replace")
            last = LLMError(("Gemini's voice is out of free uses for now (" if e.code == 429 else "Gemini's voice: (")
                            + _llm_error_text("gemini", e.code, raw) + ")")
            last.status = e.code
            if e.code in (400, 404):  # this API shape isn't the one: try the other
                continue
            raise last
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise LLMError(f"Gemini's voice didn't answer: {type(e).__name__}")
        hit = _find_audio(out)
        if not hit:
            last = LLMError("Gemini's voice sent back no audio")
            continue
        mime, data = hit
        audio = base64.b64decode(data)
        if audio[:4] == b"RIFF":
            return audio
        rate = re.search(r"rate=(\d+)", mime)
        return _wav(audio, int(rate.group(1)) if rate else 24000)
    raise last or LLMError("Gemini's voice didn't answer")


def server_say(text, voice):
    """WAV for a server-side voice: "orpheus:<name>" (or a bare Orpheus name) or "gemini:<name>"."""
    engine, _, name = voice.partition(":") if ":" in voice else ("orpheus", "", voice)
    if engine == "gemini":
        return gemini_say(text, name)
    if engine == "fish":
        return fish_say(text, name or None)
    if engine == "orpheus":
        return orpheus_say(text, name)
    raise ValueError(f"unknown voice {voice!r}")


# ---- Hearing (Glasses mode): when Safari's own dictation won't start from a
# tap on the glasses, the Head page records a clip and Groq's Whisper (free
# tier, the GROQ_API_KEY the hub already has) turns it into text.
HEAR_MODEL = os.environ.get("HEAR_MODEL", "whisper-large-v3-turbo").strip()
HEAR_MAX_BYTES = 3_000_000  # about a minute of phone audio; a clip is a few seconds


def groq_hear(audio, mime="audio/mp4", language="en", detail=False):
    """Text heard in a short audio clip; LLMError when Groq can't.
    language=None: Whisper works out the language. detail: (text, language)."""
    if not audio:
        raise ValueError("no audio")
    if len(audio) > HEAR_MAX_BYTES:
        raise ValueError("that clip is too long")
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        raise LLMError("GROQ_API_KEY isn't set")
    ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/wav": "wav", "audio/mpeg": "mp3"}.get(mime.split(";")[0], "m4a")
    boundary = "theta" + hashlib.sha1(audio[:64] + str(time.time()).encode()).hexdigest()[:16]
    parts = []
    fields = [("model", HEAR_MODEL), ("response_format", "verbose_json" if detail else "json")]
    fields += [("language", language)] if language else []
    for name, value in fields:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="clip.{ext}"\r\n'
                 f'Content-Type: {mime.split(";")[0] or "audio/mp4"}\r\n\r\n'.encode() + audio + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    url = PROVIDERS["groq"][0].rsplit("/chat/completions", 1)[0] + "/audio/transcriptions"
    req = urllib.request.Request(url, method="POST", data=b"".join(parts), headers={
        "Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "bot-hub/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err = LLMError(("Groq's hearing is out of free uses for now (" if e.code == 429 else "Groq's hearing: (")
                       + _llm_error_text("groq", e.code, e.read()[:2000].decode("utf-8", "replace")) + ")")
        err.status = e.code
        raise err
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise LLMError(f"Groq's hearing didn't answer: {type(e).__name__}")
    text = " ".join(str(out.get("text") or "").split())
    return (text, str(out.get("language") or "").lower()) if detail else text
