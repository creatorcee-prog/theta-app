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
    """Return [{title, url, snippet}, ...]."""
    query = (query or "").strip()
    if not query:
        return []
    num_results = max(1, min(int(num_results or 5), 10))

    if SEARCH_PROVIDER == "tavily" and SEARCH_API_KEY:
        return _search_tavily(query, num_results)
    if SEARCH_PROVIDER == "serper" and SEARCH_API_KEY:
        return _search_serper(query, num_results)
    # Default / fallback: DuckDuckGo Instant Answer + HTML (no key needed)
    return _search_duckduckgo(query, num_results)


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
            raw = resp.read().decode("utf-8", errors="replace")
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
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"title": "Search error", "url": "", "snippet": str(e)}]
    out = []
    for r in data.get("results", [])[:num]:
        out.append({
            "title": r.get("title") or "",
            "url": r.get("url") or "",
            "snippet": r.get("content") or r.get("snippet") or "",
        })
    return out


def _search_serper(query: str, num: int) -> list[dict[str, str]]:
    body = json.dumps({"q": query, "num": num}).encode()
    req = urllib.request.Request(
        "https://google.serper.dev/search",
        data=body,
        headers={"Content-Type": "application/json", "X-API-KEY": SEARCH_API_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{"title": "Search error", "url": "", "snippet": str(e)}]
    out = []
    for r in data.get("organic", [])[:num]:
        out.append({
            "title": r.get("title") or "",
            "url": r.get("link") or "",
            "snippet": r.get("snippet") or "",
        })
    return out


def _search_duckduckgo(query: str, num: int) -> list[dict[str, str]]:
    """Zero-key fallback. Uses the Instant Answer API + a light HTML scrape."""
    # Instant Answer
    try:
        q = urllib.parse.quote(query)
        req = urllib.request.Request(
            f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=1",
            headers={"User-Agent": "ThetaBot/1.0"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        out = []
        if data.get("AbstractText"):
            out.append({
                "title": data.get("Heading") or query,
                "url": data.get("AbstractURL") or "",
                "snippet": data.get("AbstractText") or "",
            })
        for t in data.get("RelatedTopics", [])[:num]:
            if isinstance(t, dict) and t.get("Text"):
                out.append({
                    "title": t.get("Text", "")[:80],
                    "url": t.get("FirstURL") or "",
                    "snippet": t.get("Text") or "",
                })
        if out:
            return out[:num]
    except Exception:
        pass
    return [{"title": "No results", "url": "", "snippet": f"No results for: {query}"}]


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


def run_tool(store, call: dict[str, Any], agent_id: str = "hub") -> dict[str, Any]:
    """Dispatch a parsed tool call, wrapped in a structured envelope.

    {status: "ok" | "error", data, sources, error, duration_ms}. data is
    the tool's own result; sources lists URLs a web result came from;
    error is None on success. External content stays data: it is never
    treated as instructions."""
    name = call.get("name") or ""
    args = call.get("args") or {}
    t0 = time.perf_counter()
    try:
        result = _run_tool_inner(store, name, args, agent_id)
    except Exception as e:
        result = {"error": str(e)}
    ms = int((time.perf_counter() - t0) * 1000)
    if isinstance(result, dict) and result.get("error"):
        return {"status": "error", "data": None, "sources": [], "error": str(result["error"]), "duration_ms": ms}
    sources: list[str] = []
    if name == "web_search" and isinstance(result, list):
        if result and result[0].get("title") == "Search error":
            return {"status": "error", "data": None, "sources": [],
                    "error": str(result[0].get("snippet", "")), "duration_ms": ms}
        sources = [r.get("url", "") for r in result if r.get("url")]
    elif name == "fetch_page" and isinstance(result, dict):
        text = result.get("text", "")
        if text.startswith(("Fetch failed:", "Blocked:", "Invalid URL")):
            return {"status": "error", "data": None, "sources": [], "error": text, "duration_ms": ms}
        if result.get("url"):
            sources = [result["url"]]
    return {"status": "ok", "data": result, "sources": sources, "error": None, "duration_ms": ms}


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
    return {"error": f"unknown tool: {name}"}
