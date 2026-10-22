"""Agent tools for Theta: web search, page fetch, and persistent tasks.

Import and wire these into api/index.py when ready.
Keep tool implementations here so index.py stays focused on the hub.
"""

from __future__ import annotations

import json
import os
import re
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

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ThetaBot/1.0; +https://github.com/creatorcee-prog/theta-app)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            final_url = resp.geturl()
    except Exception as e:
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

def task_create(store, title: str, by: str = "hub", channel: str | None = None) -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        return {"error": "title required"}
    tid = f"t{int(time.time() * 1000)}"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    item = {
        "id": tid,
        "title": title[:300],
        "done": False,
        "created": now,
        "updated": now,
        "by": by,
        "channel": channel,
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


def _task_set_done(store, task_id: str, done: bool) -> dict[str, Any]:
    task_id = (task_id or "").strip()
    if not task_id:
        return {"error": "task_id required"}
    try:
        raw = store._cmd("GET", f"hub:task:{task_id}")
        item = json.loads(raw) if raw else None
    except Exception:
        item = getattr(store, "_tasks", {}).get(task_id)
    if not item:
        return {"error": "task not found"}
    item["done"] = done
    item["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        store._cmd("SET", f"hub:task:{task_id}", json.dumps(item))
    except Exception:
        if hasattr(store, "_tasks"):
            store._tasks[task_id] = item
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


def run_tool(store, call: dict[str, Any], agent_id: str = "hub") -> Any:
    """Dispatch a parsed tool call. Returns a JSON-serializable result."""
    name = call.get("name") or ""
    args = call.get("args") or {}

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
    return {"error": f"unknown tool: {name}"}
