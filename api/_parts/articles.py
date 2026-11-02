"""Reading articles for the news crew.

Part of api/index.py, split out for size (Stage 7.2). Loaded INTO
index.py's namespace by _load_part() at this same spot, not imported,
so every name is still index.<name> (see store.py)."""

# ---- Reading articles: the news bots (and Lenz) read the story itself,
# write a short neutral brief with a few exact quotes and a line on the
# article's framing, and credit everyone who wrote it. Only the brief,
# short quotes and the link are kept; the article text is used once and
# dropped (republishing whole articles would be copying the outlets' work).
# Sites that refuse automated readers are respected, not dodged.
ARTICLE_UA = "Theta-dashboard/1.0 (personal news reader; https://github.com/creatorcee-prog/dashboard-app)"
ARTICLE_TYPES = {"newsarticle", "article", "reportagenewsarticle", "analysisnewsarticle", "blogposting",
                 "opinionnewsarticle", "backgroundnewsarticle", "liveblogposting", "webpage"}
_ARTICLE_CACHE = {}  # url -> (fetched_at, article); per process
BRIEF_KEEP = 60  # briefs remembered (by story URL)
_BRIEF_LOCK = threading.Lock()


def _ld_objects(page):
    out = []
    for block in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", page, re.S | re.I):
        try:
            data = json.loads(html.unescape(block.strip()))
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            o = stack.pop(0)
            if isinstance(o, dict):
                stack += o.get("@graph", []) if isinstance(o.get("@graph"), list) else []
                out.append(o)
            elif isinstance(o, list):
                stack += o
    return out


def _author_names(v):
    """Author names from JSON-LD's author field (a dict, a list or text)."""
    if isinstance(v, list):
        return [n for x in v for n in _author_names(x)]
    if isinstance(v, dict):
        return _author_names(v.get("name"))
    if isinstance(v, str) and v.strip() and not v.startswith("http"):
        return [n.strip() for n in re.split(r",| and ", re.sub(r"^by\s+", "", v.strip(), flags=re.I)) if n.strip()]
    return []


def _meta(page, *names):
    vals = []
    for n in names:
        for m in re.finditer(r"<meta\b[^>]*>", page, re.I):
            tag = m.group(0)
            if re.search(r"(?:name|property)=[\"']" + re.escape(n) + r"[\"']", tag, re.I):
                c = re.search(r"content=[\"']([^\"']*)", tag, re.I)
                if c and c.group(1).strip():
                    vals.append(html.unescape(c.group(1).strip()))
    return vals


def read_article(url):
    """{title, authors, publisher, text, blocked}: the article's text and
    byline from its page (structured data first, then meta tags, then
    paragraphs). blocked: the site refused us or had no readable text."""
    hit = _ARTICLE_CACHE.get(url)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    art = {"title": "", "authors": [], "publisher": "", "text": "", "blocked": ""}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ARTICLE_UA, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            page = resp.read(1_500_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        art["blocked"] = (f"the site doesn't allow automated reading ({e.code})" if e.code in (401, 403, 429, 451)
                          else f"the site returned {e.code}")
        _ARTICLE_CACHE[url] = (time.time(), art)
        return art
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        art["blocked"] = "the site didn't answer"
        return art
    for o in _ld_objects(page):
        types = o.get("@type") or []
        types = {t.lower() for t in (types if isinstance(types, list) else [types]) if isinstance(t, str)}
        if not types & ARTICLE_TYPES:
            continue
        art["title"] = art["title"] or str(o.get("headline") or "")
        art["authors"] = art["authors"] or _author_names(o.get("author"))
        pub = o.get("publisher")
        art["publisher"] = art["publisher"] or (pub.get("name", "") if isinstance(pub, dict) else "")
        if isinstance(o.get("articleBody"), str) and len(o["articleBody"]) > len(art["text"]):
            art["text"] = o["articleBody"]
    if not art["authors"]:
        for v in _meta(page, "author", "byl", "parsely-author", "sailthru.author", "article:author"):
            if v.startswith("http"):  # profile links: "/profile/jane-doe" -> Jane Doe
                art["authors"] += [p.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
                                   for p in v.split(",") if "/" in p]
            else:
                art["authors"] += _author_names(v)
    art["authors"] = list(dict.fromkeys(a for a in art["authors"] if 1 < len(a) < 60))[:6]
    art["publisher"] = art["publisher"] or (_meta(page, "og:site_name") or [""])[0]
    if len(art["text"]) < 400:
        page = re.sub(r"<(script|style|noscript|template)\b.*?</\1\s*>", " ", page, flags=re.S | re.I)
        body = re.search(r"<article\b.*?</article>", page, re.S | re.I)
        paras = re.findall(r"<p\b[^>]*>(.*?)</p>", body.group(0) if body else page, re.S | re.I)
        paras = [_plain(p, 2000) for p in paras]
        art["text"] = "\n".join(p for p in paras if len(p) > 60 and not re.search(
            r"(?i)subscribe|sign up|newsletter|cookies|all rights reserved|advertis", p))
    art["text"] = _plain(art["text"], 6000) if "<" in art["text"] else art["text"][:6000]
    if len(art["text"]) < 300:
        art["blocked"] = art["blocked"] or "there was no readable article text (likely a paywall)"
    _ARTICLE_CACHE[url] = (time.time(), art)
    return art


def credit_line(art, outlet):
    names = art.get("authors") or []
    who = (", ".join(names[:-1]) + " and " + names[-1]) if len(names) > 1 else (names[0] if names else "")
    return f"By {who}, {outlet}" if who else f"{outlet} (no byline given)"


_QUOTE_RE = re.compile(r"[\"“]([^\"”]{12,300})[\"”]")


def _squash(text):
    t = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")
    return " ".join(re.sub(r"[^\w' -]", " ", t.lower()).split())


def keep_true_quotes(text, source):
    """Drop any sentence that quotes words the article doesn't contain
    (models sometimes invent quotes). Returns (text, how many dropped)."""
    src = _squash(source)
    sentences = re.split(r"(?<=[.!?][\"”])\s+|(?<=[.!?])\s+(?=[A-Z\"“])", text.strip())
    kept, dropped = [], 0
    for sent in sentences:
        quotes = _QUOTE_RE.findall(sent)
        if quotes and not all(_squash(q) in src for q in quotes):
            dropped += 1
            continue
        kept.append(sent)
    return " ".join(kept), dropped


def story_brief(title, url, outlet, fallback=""):
    """A neutral brief of one story: {summary, bias, credit, read} where
    read says whether the article itself was read. One miner-model call,
    remembered by URL. Quotes are checked against the article's text."""
    have = _meta_json("briefs", {}).get(url)
    if have:
        return have
    art = read_article(url)
    source = art["text"] if not art["blocked"] else (fallback or "")
    credit = credit_line(art, outlet)
    if not source.strip():
        brief = {"summary": "", "bias": "", "credit": credit, "read": False,
                 "note": f"Couldn't read it: {art['blocked'] or 'no text'}."}
        return brief
    reply = llm_chat("miner", [
        {"role": "system", "content": "You brief news stories for a busy reader: neutral, exact, short."},
        {"role": "user", "content": f"Story: {title} ({outlet})\n"
         + ("Article text" if not art["blocked"] else "Only the outlet's own summary (the article couldn't be read)")
         + f":\n{source[:4000]}\n\nWrite exactly two lines.\n"
         "SUMMARY: 2-3 neutral sentences on what happened, using only this text. Where the exact words matter, "
         "quote them word for word in quotation marks (at most 2 short quotes). Never put anything in quotes "
         "that isn't in the text.\n"
         "BIAS: one sentence on how this piece frames the story: loaded words, whose voices lead, context left "
         "out. If it reads as straight reporting, say that. Be fair."}], max_tokens=700)
    summary = re.search(r"SUMMARY:\s*(.+?)(?=\n\s*BIAS:|$)", reply, re.S | re.I)
    bias = re.search(r"BIAS:\s*(.+)", reply, re.S | re.I)
    text, dropped = keep_true_quotes((summary.group(1) if summary else reply).strip(), source)
    brief = {"summary": text, "bias": (bias.group(1).strip().split("\n")[0] if bias else ""), "credit": credit,
             "read": not art["blocked"], "dropped_quotes": dropped,
             "note": "" if not art["blocked"] else f"From the outlet's summary; {art['blocked']}."}
    with _BRIEF_LOCK:
        briefs = _meta_json("briefs", {})
        briefs[url] = brief
        store().set_meta("briefs", json.dumps(dict(list(briefs.items())[-BRIEF_KEEP:])))
    return brief


def brief_text(b):
    parts = [b["summary"]] if b.get("summary") else []
    if b.get("bias"):
        parts.append(f"Framing: {b['bias']}")
    parts.append(b["credit"] + (f". {b['note']}" if b.get("note") else ""))
    return "\n".join(parts)
