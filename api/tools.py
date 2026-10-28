"""Agent tools for Theta: web search, page fetch, and persistent tasks.

Import and wire these into api/index.py when ready.
Keep tool implementations here so index.py stays focused on the hub.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# ---------------------------------------------------------------------------
# Web Search + Page Fetch
# ---------------------------------------------------------------------------

SEARCH_PROVIDER = os.environ.get("SEARCH_PROVIDER", "duckduckgo").lower()
SEARCH_API_KEY = os.environ.get("SEARCH_API_KEY") or os.environ.get("TAVILY_API_KEY") or os.environ.get("SERPER_API_KEY")


class SearchError(Exception):
    """A search failure with a machine-readable kind, never a fake result.

    kinds: not_configured (a keyed provider was selected but no key is
    set), unknown_provider, auth (401/403), rate_limit (429),
    timeout, network, malformed (bad JSON or unexpected schema),
    provider_error (other HTTP 4xx/5xx). str() carries the kind so the
    run_tool envelope and the bridge receipt keep it; no key, header,
    or request body is ever included in the message.
    """

    KINDS = {"not_configured", "unknown_provider", "auth", "rate_limit",
             "timeout", "network", "malformed", "provider_error"}

    def __init__(self, kind, message):
        self.kind = kind if kind in self.KINDS else "provider_error"
        self.message = message
        super().__init__(f"Search failed ({self.kind}): {message}")


def _selected_provider():
    """Effective provider name: the env value, or duckduckgo when unset."""
    return (SEARCH_PROVIDER or "duckduckgo").lower()


def _request_json(req, timeout):
    """POST/GET a provider and parse its JSON body, or raise SearchError.

    HTTP status, timeouts, and malformed bodies are distinguished here
    so a provider failure is never reported as an empty search.
    """
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise SearchError("auth", f"provider rejected the key (HTTP {e.code})")
        if e.code == 429:
            raise SearchError("rate_limit", "provider rate limit reached (HTTP 429)")
        raise SearchError("provider_error", f"provider returned HTTP {e.code}")
    except TimeoutError:
        raise SearchError("timeout", "provider request timed out")
    except urllib.error.URLError as e:
        reason = str(getattr(e, "reason", e))
        if "timed out" in reason.lower() or "timeout" in reason.lower():
            raise SearchError("timeout", "provider request timed out")
        raise SearchError("network", f"provider unreachable: {reason[:120]}")
    try:
        data = json.loads(raw)
    except ValueError:
        raise SearchError("malformed", "provider returned non-JSON body")
    if not isinstance(data, dict):
        raise SearchError("malformed", "provider returned a non-object JSON body")
    return data


def _clean_results(items, num, title_key, url_key, snippet_keys):
    """Validate provider items into [{title, url, snippet}].

    Drops items that are not objects, carry no usable content (no title
    and no snippet), or carry a URL that is not http(s). An empty URL
    is kept: the bridge shows title + snippet without a link, and only
    non-empty URLs become Sources.
    """
    out = []
    for r in items or []:
        if not isinstance(r, dict):
            continue
        title = (r.get(title_key) or "").strip()
        url = (r.get(url_key) or "").strip()
        snippet = ""
        for k in snippet_keys:
            snippet = (r.get(k) or "").strip()
            if snippet:
                break
        if not title and not snippet:
            continue
        if url and not url.startswith(("http://", "https://")):
            continue
        out.append({"title": title, "url": url, "snippet": snippet})
    return out[:num]


# A page is read up to this many bytes; the rest is never downloaded, so
# a huge or endless response can't stall a request or fill memory.
FETCH_MAX_BYTES = 2_000_000


def _host_is_public(host: str) -> bool:
    """True only if every resolved address is a public unicast IP.

    Blocks loopback, private (RFC 1918), link-local, reserved,
    unspecified and multicast addresses, so a fetched URL cannot reach
    the host's own network (SSRF). DNS is resolved here, before the
    fetch; a redirect to a private host is checked again by
    _SafeRedirectHandler. A DNS-rebinding swap between the check and
    the fetch remains possible; this guard stops direct private-URL
    fetches, not a determined rebinding attack.
    """
    host = (host or "").strip().strip("[]")
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except Exception:
            return False
        if not ip.is_global or ip.is_multicast:
            return False
    return True


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects to non-public hosts (same SSRF rule as above)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        host = parsed.hostname or ""
        if not host:  # a relative redirect: same host as the request
            host = urllib.parse.urlparse(req.full_url).hostname or ""
        if not _host_is_public(host):
            raise ValueError(f"Blocked redirect to non-public host: {host}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def tool_web_search(query: str, num_results: int = 5) -> list[dict[str, str]]:
    """Return [{title, url, snippet}, ...]; raise SearchError on failure.

    Selection is explicit, never a silent downgrade: a named keyed
    provider without a key is a not_configured error, and an unknown
    provider name is an error. Only the default (unset) or an explicit
    "duckduckgo" uses the zero-key Instant Answer path, whose limits
    are labeled in its docstring and in the bridge receipt.
    """
    query = (query or "").strip()
    if not query:
        return []
    num_results = max(1, min(int(num_results or 5), 10))
    provider = _selected_provider()

    if provider == "tavily":
        if not SEARCH_API_KEY:
            raise SearchError("not_configured",
                              "SEARCH_PROVIDER=tavily but no API key is set "
                              "(set SEARCH_API_KEY or TAVILY_API_KEY)")
        return _search_tavily(query, num_results)
    if provider == "serper":
        if not SEARCH_API_KEY:
            raise SearchError("not_configured",
                              "SEARCH_PROVIDER=serper but no API key is set "
                              "(set SEARCH_API_KEY or SERPER_API_KEY)")
        return _search_serper(query, num_results)
    if provider == "duckduckgo":
        return _search_duckduckgo(query, num_results)
    raise SearchError("unknown_provider",
                      f"unknown SEARCH_PROVIDER {provider!r} "
                      "(duckduckgo, tavily, serper)")


def tool_fetch_page(url: str, max_chars: int = 6000) -> dict[str, str]:
    """Return {title, text, url} with main content cleaned."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return {"title": "", "text": "Invalid URL", "url": url}
    host = urllib.parse.urlparse(url).hostname or ""
    if not _host_is_public(host):
        return {"title": "", "text": f"Blocked: host is not public: {host}", "url": url}

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ThetaBot/1.0; +https://github.com/creatorcee-prog/theta-app)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        opener = urllib.request.build_opener(_SafeRedirectHandler)
        with opener.open(req, timeout=12) as resp:
            raw = resp.read(FETCH_MAX_BYTES).decode("utf-8", errors="replace")
            final_url = resp.geturl()
    except Exception as e:
        if "Blocked redirect" in str(e):
            return {"title": "", "text": f"Blocked: {e}", "url": url}
        return {"title": "", "text": f"Fetch failed: {e}", "url": url}

    title = _extract_title(raw)
    text = _html_to_text(raw)
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "\u2026"
    return {"title": title, "text": text, "url": final_url}


def _search_tavily(query: str, num: int) -> list[dict[str, str]]:
    body = json.dumps({"api_key": SEARCH_API_KEY, "query": query, "max_results": num}).encode()
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    data = _request_json(req, timeout=15)
    if "results" not in data:
        raise SearchError("malformed", "Tavily response is missing the results key")
    results = data.get("results")
    if results is None:
        results = []
    elif not isinstance(results, list):
        raise SearchError("malformed", "Tavily results is not a list")
    return _clean_results(results, num, "title", "url", ("content", "snippet"))


def _search_serper(query: str, num: int) -> list[dict[str, str]]:
    body = json.dumps({"q": query, "num": num}).encode()
    req = urllib.request.Request(
        "https://google.serper.dev/search",
        data=body,
        headers={"Content-Type": "application/json", "X-API-KEY": SEARCH_API_KEY},
        method="POST",
    )
    data = _request_json(req, timeout=15)
    if "organic" not in data:
        raise SearchError("malformed", "Serper response is missing the organic key")
    organic = data.get("organic")
    if organic is None:
        organic = []
    elif not isinstance(organic, list):
        raise SearchError("malformed", "Serper organic is not a list")
    return _clean_results(organic, num, "title", "link", ("snippet",))


def _search_duckduckgo(query: str, num: int) -> list[dict[str, str]]:
    """Zero-key fallback. Uses the Instant Answer API only (no key needed).

    This is an instant-answer lookup, NOT a general web index, and the
    receipt says so when it comes back empty: entity queries return an
    abstract and related topics, but general web and news queries
    usually come back empty. That empty is genuine, not a failure —
    but it is not evidence that the web has no matching pages. For
    general search, configure a keyed provider (SEARCH_PROVIDER=tavily
    or serper with SEARCH_API_KEY). A transport or parse failure
    raises SearchError, never a disguised empty result.
    """
    q = urllib.parse.quote(query)
    req = urllib.request.Request(
        f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=1",
        headers={"User-Agent": "ThetaBot/1.0"},
    )
    data = _request_json(req, timeout=8)
    out = []
    if data.get("AbstractText"):
        url = data.get("AbstractURL") or ""
        if url and not url.startswith(("http://", "https://")):
            url = ""
        out.append({
            "title": data.get("Heading") or query,
            "url": url,
            "snippet": data.get("AbstractText") or "",
        })

    def _collect(topics):
        for t in topics or []:
            if not isinstance(t, dict):
                continue
            if t.get("Text"):
                url = t.get("FirstURL") or ""
                if url and not url.startswith(("http://", "https://")):
                    continue
                out.append({
                    "title": t.get("Text", "")[:80],
                    "url": url,
                    "snippet": t.get("Text") or "",
                })
            elif isinstance(t.get("Topics"), list):
                # Category groups nest real results one level down.
                _collect(t["Topics"])

    _collect(data.get("RelatedTopics"))
    return out[:num]


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:200]
    return ""


def _html_to_text(html: str) -> str:
    """Very light cleaner. Prefer the more sophisticated one already in index.py if available."""
    # Remove scripts/styles
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    # Tags to newlines / spaces
    html = re.sub(r"<(br|/p|/div|/h[1-6]|/li)[^>]*>", "\n", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"[ \t]+", " ", html)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Persistent Tasks
# ---------------------------------------------------------------------------

# These expect a store object that has the same Redis/memory interface as
# the one in index.py (add_chat, list_chat, _cmd, etc.). Pass the store in.

def task_create(store, title: str, by: str = "hub", channel: str | None = None,
                sources: list | None = None) -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        return {"error": "title required"}
    tid = f"t{int(time.time() * 1000)}"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    item = {
        "id": tid,
        "title": title[:300],
        "done": False,
        "status": "open",
        "created": now,
        "updated": now,
        "by": by,
        "agent": by,
        "channel": channel,
        "steps": [],
        "results": [],
        "sources": list(sources or []),
        "blockers": [],
        "approvals": [],
    }
    # Prefer a real Redis list if available
    try:
        store._cmd("LPUSH", "hub:tasks", tid)
        store._cmd("SET", f"hub:task:{tid}", json.dumps(item))
    except Exception:
        # Fallback for in-memory store
        if not hasattr(store, "_tasks"):
            store._tasks = {}
            store._task_ids = []
        store._tasks[tid] = item
        store._task_ids.insert(0, tid)
    return item


def task_list(store, status: str = "open", limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 20), 50))
    ids: list[str] = []
    try:
        ids = store._cmd("LRANGE", "hub:tasks", "0", str(limit * 3 - 1)) or []
    except Exception:
        ids = getattr(store, "_task_ids", [])[: limit * 3]

    out = []
    for tid in ids:
        try:
            raw = store._cmd("GET", f"hub:task:{tid}")
            item = json.loads(raw) if raw else None
        except Exception:
            item = getattr(store, "_tasks", {}).get(tid)
        if not item:
            continue
        if status == "open" and item.get("done"):
            continue
        if status == "done" and not item.get("done"):
            continue
        out.append(item)
        if len(out) >= limit:
            break
    return out


def task_complete(store, task_id: str) -> dict[str, Any]:
    return _task_set_done(store, task_id, True)


def task_reopen(store, task_id: str) -> dict[str, Any]:
    return _task_set_done(store, task_id, False)


def _task_load(store, task_id: str) -> dict[str, Any] | None:
    """A task by id, from Redis or the in-memory fallback. None if missing."""
    try:
        raw = store._cmd("GET", f"hub:task:{task_id}")
        return json.loads(raw) if raw else None
    except Exception:
        return getattr(store, "_tasks", {}).get(task_id)


def _task_save(store, task_id: str, item: dict[str, Any]) -> None:
    try:
        store._cmd("SET", f"hub:task:{task_id}", json.dumps(item))
    except Exception:
        if hasattr(store, "_tasks"):
            store._tasks[task_id] = item


def _task_set_done(store, task_id: str, done: bool) -> dict[str, Any]:
    task_id = (task_id or "").strip()
    if not task_id:
        return {"error": "task_id required"}
    item = _task_load(store, task_id)
    if not item:
        return {"error": "task not found"}
    item["done"] = done
    item["status"] = "done" if done else "open"
    item["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _task_save(store, task_id, item)
    return item


def task_note(store, task_id: str, step: str | None = None, result: Any = None,
              source: str | None = None, blocker: str | None = None,
              approval: str | None = None) -> dict[str, Any]:
    """Append a step, result, source, blocker or approval to a task.

    Steps are what actually happened, in order; while the task is open
    the current step is the last one. Notes never perform an action, so
    retrying a task replays notes, never the action itself."""
    task_id = (task_id or "").strip()
    if not task_id:
        return {"error": "task_id required"}
    item = _task_load(store, task_id)
    if not item:
        return {"error": "task not found"}
    if step:
        item.setdefault("steps", []).append(str(step)[:300])
    if result is not None:
        item.setdefault("results", []).append(result)
    if source:
        item.setdefault("sources", []).append(str(source)[:500])
    if blocker:
        item.setdefault("blockers", []).append(str(blocker)[:300])
    if approval:
        item.setdefault("approvals", []).append(str(approval)[:300])
    item["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _task_save(store, task_id, item)
    return item


# ---------------------------------------------------------------------------
# Tool-call parser (simple text format)
# ---------------------------------------------------------------------------

TOOL_RE = re.compile(
    r"^TOOL:\s*(\w+)\s*$",
    re.I | re.M,
)

def parse_tool_call(text: str) -> dict[str, Any] | None:
    """Parse a simple TOOL: name / key: value block from an agent reply."""
    if not text:
        return None
    m = TOOL_RE.search(text)
    if not m:
        return None
    name = m.group(1).lower()
    # Collect key: value lines after the TOOL line
    args: dict[str, Any] = {}
    after = text[m.end():]
    for line in after.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("tool:"):
            break
        if ":" in line:
            k, v = line.split(":", 1)
            args[k.strip().lower()] = v.strip()
    return {"name": name, "args": args}


# ---------------------------------------------------------------------------
# Follows (Phase F1: record + agent tool. Scheduled checks land in F2, so
# a created record is verified but NOT yet monitored; receipts say so.)
# ---------------------------------------------------------------------------
FOLLOW_FREQUENCIES = {"hourly": 3600, "daily": 86400, "weekly": 604800}
FOLLOW_SOURCES = {"releases", "news", "web"}
FOLLOW_CHANNELS = {"push", "chat", "both"}
FOLLOW_STATES = {"active", "paused", "failed", "canceled"}
_FOLLOW_LOCK = threading.Lock()


def _follow_load_all(store):
    try:
        raw = store._cmd("GET", "hub:follows")
        return json.loads(raw) if raw else []
    except Exception:
        return list(getattr(store, "_follows", []))


def _follow_save_all(store, items):
    try:
        store._cmd("SET", "hub:follows", json.dumps(items))
    except Exception:
        store._follows = items


def _follow_get(store, fid):
    for f in _follow_load_all(store):
        if f.get("id") == fid:
            return f
    return None


def _norm_title(t):
    return " ".join((t or "").split()).casefold()


def follow_create(store, title, kind="", query="", sources="", frequency="", channel="", by="hub"):
    """Create a follow record, then read it back before reporting success.

    Dedup: an active or paused follow with the same normalized title and
    kind returns the existing record instead of a duplicate. States
    reachable here: active (new) and canceled (via follow_cancel); paused
    and failed arrive with the F3 controls and F2 checks.
    """
    title = " ".join((title or "").split())[:300]
    if not title:
        return {"error": "need a title to follow"}
    kind = " ".join((kind or "").split()).lower()[:40] or "title"
    query = " ".join((query or "").split())[:300] or title
    freq = " ".join((frequency or "").split()).lower() or "daily"
    if freq not in FOLLOW_FREQUENCIES:
        return {"error": f"unknown frequency {freq!r} (hourly, daily, weekly)"}
    if isinstance(sources, str):
        srcs = [s.strip().lower() for s in sources.split(",") if s.strip()]
    else:
        srcs = [str(s).strip().lower() for s in (sources or []) if str(s).strip()]
    if not srcs:
        srcs = ["releases", "news", "web"]
    bad = [s for s in srcs if s not in FOLLOW_SOURCES]
    if bad:
        return {"error": f"unknown source(s) {', '.join(bad)} (releases, news, web)"}
    ch = " ".join((channel or "").split()).lower() or "both"
    if ch in ("push+chat", "push_chat"):
        ch = "both"
    if ch not in FOLLOW_CHANNELS:
        return {"error": f"unknown channel {ch!r} (push, chat, both)"}
    with _FOLLOW_LOCK:
        items = _follow_load_all(store)
        for f in items:
            if f.get("state") in ("active", "paused") and _norm_title(f.get("title")) == _norm_title(title) and (f.get("kind") or "title") == kind:
                return {"record": f, "already": True, "verified": True}
        now = time.time()
        rec = {"id": f"f{int(now * 1000)}", "kind": kind, "title": title, "query": query,
               "sources": srcs, "frequency": freq, "channel": ch, "state": "active",
               "created": now, "next_due": now + FOLLOW_FREQUENCIES[freq],
               "last_checked": None, "last_error": "", "seen": [], "by": by}
        items.append(rec)
        _follow_save_all(store, items)
        back = _follow_get(store, rec["id"])
        if not back:
            return {"error": "follow saved but verification read-back failed; check follow_list"}
        return {"record": back, "already": False, "verified": True}


def follow_list(store, status="active", limit=20):
    """List follow records. status: active, paused, failed, canceled, all."""
    status = (status or "active").strip().lower()
    if status not in ("active", "paused", "failed", "canceled", "all"):
        status = "active"
    limit = max(1, min(int(limit or 20), 50))
    items = _follow_load_all(store)
    if status != "all":
        items = [f for f in items if f.get("state") == status]
    items.sort(key=lambda f: f.get("created", 0), reverse=True)
    return items[:limit]


def follow_cancel(store, follow_id):
    """Cancel a follow. The record is kept as canceled, never deleted, so
    the user can still inspect it. Canceling an already-canceled follow
    succeeds idempotently."""
    fid = (follow_id or "").strip()
    if not fid:
        return {"error": "need a follow_id"}
    with _FOLLOW_LOCK:
        items = _follow_load_all(store)
        rec = next((f for f in items if f.get("id") == fid), None)
        if not rec:
            return {"error": "follow not found"}
        if rec.get("state") == "canceled":
            return {"record": rec, "already": True, "verified": True}
        rec["state"] = "canceled"
        _follow_save_all(store, items)
        back = _follow_get(store, fid)
        if not back or back.get("state") != "canceled":
            return {"error": "cancel saved but verification read-back failed; check follow_list"}
        return {"record": back, "already": False, "verified": True}


def run_tool(store, call: dict[str, Any], agent_id: str = "hub") -> dict[str, Any]:
    """Dispatch a parsed tool call, wrapped in a structured envelope.

    {status: "ok" | "error", data, sources, error, duration_ms, provider}.
    data is the tool's own result; sources lists URLs a web result came
    from; error is None on success; provider names the search backend
    for web_search calls (so the bridge can label a zero-key empty).
    External content stays data: it is never treated as instructions.
    A search failure is a SearchError with a kind, never a fake result
    or a successful empty list."""
    name = call.get("name") or ""
    args = call.get("args") or {}
    t0 = time.perf_counter()
    try:
        result = _run_tool_inner(store, name, args, agent_id)
    except SearchError as e:
        result = {"error": str(e)}
    except Exception as e:
        result = {"error": str(e)}
    ms = int((time.perf_counter() - t0) * 1000)
    if isinstance(result, dict) and result.get("error"):
        env = {"status": "error", "data": None, "sources": [], "error": str(result["error"]), "duration_ms": ms}
        if name == "web_search":
            env["provider"] = _selected_provider()
        return env
    sources: list[str] = []
    if name == "web_search" and isinstance(result, list):
        sources = [r.get("url", "") for r in result if r.get("url")]
    elif name == "fetch_page" and isinstance(result, dict):
        text = result.get("text", "")
        if text.startswith(("Fetch failed:", "Blocked:", "Invalid URL")):
            return {"status": "error", "data": None, "sources": [], "error": text, "duration_ms": ms}
        if result.get("url"):
            sources = [result["url"]]
    env = {"status": "ok", "data": result, "sources": sources, "error": None, "duration_ms": ms}
    if name == "web_search":
        env["provider"] = _selected_provider()
    return env


def _run_tool_inner(store, name: str, args: dict[str, Any], agent_id: str) -> Any:
    if name == "web_search":
        return tool_web_search(args.get("query", ""), int(args.get("num_results", 5) or 5))
    if name == "fetch_page":
        return tool_fetch_page(args.get("url", ""), int(args.get("max_chars", 6000) or 6000))
    if name == "task_create":
        return task_create(store, args.get("title", ""), by=agent_id, channel=args.get("channel"))
    if name == "task_list":
        return task_list(store, args.get("status", "open"), int(args.get("limit", 20) or 20))
    if name == "task_complete":
        return task_complete(store, args.get("task_id", ""))
    if name == "task_reopen":
        return task_reopen(store, args.get("task_id", ""))
    if name == "task_note":
        return task_note(store, args.get("task_id", ""), step=args.get("step"), result=args.get("result"),
                         source=args.get("source"), blocker=args.get("blocker"), approval=args.get("approval"))
    if name == "follow_create":
        return follow_create(store, args.get("title", ""), kind=args.get("kind", ""), query=args.get("query", ""),
                             sources=args.get("sources", ""), frequency=args.get("frequency", ""),
                             channel=args.get("channel", ""), by=agent_id)
    if name == "follow_list":
        return follow_list(store, args.get("status", "active"), int(args.get("limit", 20) or 20))
    if name == "follow_cancel":
        return follow_cancel(store, args.get("follow_id", ""))
    return {"error": f"unknown tool: {name}"}
