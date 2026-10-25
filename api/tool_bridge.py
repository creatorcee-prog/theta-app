"""Phase 4 bridge: thin ACTION wrappers around api/tools.py.

Imported by api/index.py so the main hub file only needs a few lines
to register the tools. Keeps SSRF guards and the structured envelope
inside tools.py.
"""
from __future__ import annotations

# tools.py is loaded by path next to this file, not by sys.path, for the
# same reason index.py loads this bridge by path: on Vercel the api/
# directory is not guaranteed to be on sys.path, and a failed
# `import tools` here would leave the tools registered but unusable
# (every wrapper raises "tool layer not available"). Any failure is
# recorded in TOOLS_LAYER_ERROR and shown on /diagnostics.
TOOLS_LAYER_ERROR = None
agent_tools = None
try:
    import importlib.util
    import os as _os
    _here = _os.path.dirname(_os.path.abspath(__file__)) if "__file__" in globals() else ""
    _tools_path = _os.path.join(_here, "tools.py") if _here else ""
    if _tools_path and _os.path.exists(_tools_path):
        _spec = importlib.util.spec_from_file_location("agent_tools", _tools_path)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        agent_tools = _mod
    else:
        import tools as agent_tools
except Exception as e:  # recorded, not swallowed: see tools_diag()
    TOOLS_LAYER_ERROR = f"{type(e).__name__}: {e}"
    agent_tools = None


# Set by api/index.py's loader to its own store() the moment it loads
# this bridge. That is the primary path: it is a reference to the
# already-loaded hub module, so the bridge never needs to import the
# hub at all — no sys.path dependence, no second copy of the hub
# module under Vercel's file-path loading, and no circular import
# (the reference is resolved at tool-call time, after index.py has
# finished loading and defined store()).
HUB_STORE = None


def _store():
    """Return the hub store, preferring the already-loaded hub module.

    Order: (1) the HUB_STORE reference injected by index.py's loader;
    (2) an already-imported "index" module in sys.modules (same object,
    never a fresh import); (3) a plain `import index` as a last resort
    for standalone use of this bridge, where no hub is loaded yet so
    the import creates the first copy, not a second one.
    """
    if HUB_STORE is not None:
        return HUB_STORE()
    import sys
    h = sys.modules.get("index")
    if h is not None:
        return h.store()
    import index as h
    return h.store()


def tool_web_search(arg, agent):
    """Read-only: search the web. Uses tools.py (DuckDuckGo fallback or configured provider)."""
    if agent_tools is None:
        raise ValueError("tool layer not available")
    query = (arg or "").strip()
    if not query:
        raise ValueError("need a search query")
    out = agent_tools.run_tool(_store(), {"name": "web_search", "args": {"query": query, "num_results": "5"}}, agent_id=agent)
    if out.get("status") != "ok":
        raise ValueError(out.get("error") or "search failed")
    results = out.get("data") or []
    if not results:
        return "No results"
    lines = []
    for i, r in enumerate(results[:5], 1):
        title = (r.get("title") or "").strip() or "(no title)"
        url = (r.get("url") or "").strip()
        snip = (r.get("snippet") or "").strip()[:200]
        lines.append(f"{i}. {title}" + (f" — {url}" if url else "") + (f"\n   {snip}" if snip else ""))
    src = out.get("sources") or []
    receipt = "Web search results:\n" + "\n".join(lines)
    if src:
        receipt += "\nSources: " + ", ".join(s for s in src if s)[:400]
    return receipt


def tool_fetch_page(arg, agent):
    """Read-only: fetch a public page. SSRF-guarded in tools.py."""
    if agent_tools is None:
        raise ValueError("tool layer not available")
    url = (arg or "").strip()
    if not url:
        raise ValueError("need a URL")
    out = agent_tools.run_tool(_store(), {"name": "fetch_page", "args": {"url": url, "max_chars": "4000"}}, agent_id=agent)
    if out.get("status") != "ok":
        raise ValueError(out.get("error") or "fetch failed")
    data = out.get("data") or {}
    title = (data.get("title") or "").strip() or "(no title)"
    body = (data.get("text") or "").strip()[:1500]
    final = data.get("url") or url
    return f"Fetched {title} ({final}):\n{body}"


def tool_task_create(arg, agent):
    """Create a persistent task in the ledger."""
    if agent_tools is None:
        raise ValueError("tool layer not available")
    title = (arg or "").strip()
    if not title:
        raise ValueError("need a task title")
    out = agent_tools.run_tool(_store(), {"name": "task_create", "args": {"title": title}}, agent_id=agent)
    if out.get("status") != "ok":
        raise ValueError(out.get("error") or "could not create task")
    t = out["data"]
    return f"Task created: {t.get('title')} (id {t.get('id')})"


def tool_task_list(arg, agent):
    """List open (or done) tasks from the ledger."""
    if agent_tools is None:
        raise ValueError("tool layer not available")
    status = "open"
    a = (arg or "").strip().lower()
    if a in ("done", "completed", "closed"):
        status = "done"
    elif a in ("all", "any"):
        status = "all"
    if status == "all":
        o1 = agent_tools.run_tool(_store(), {"name": "task_list", "args": {"status": "open", "limit": "15"}}, agent_id=agent)
        o2 = agent_tools.run_tool(_store(), {"name": "task_list", "args": {"status": "done", "limit": "10"}}, agent_id=agent)
        items = (o1.get("data") or []) + (o2.get("data") or [])
    else:
        out = agent_tools.run_tool(_store(), {"name": "task_list", "args": {"status": status, "limit": "20"}}, agent_id=agent)
        if out.get("status") != "ok":
            raise ValueError(out.get("error") or "list failed")
        items = out.get("data") or []
    if not items:
        return f"No {status} tasks"
    lines = []
    for t in items[:15]:
        mark = "✓" if t.get("done") else "○"
        lines.append(f"{mark} {t.get('title', '?')} [{t.get('id')}]")
    return "Tasks:\n" + "\n".join(lines)


def tool_task_complete(arg, agent):
    """Mark a task done in the ledger."""
    if agent_tools is None:
        raise ValueError("tool layer not available")
    tid = (arg or "").strip()
    if not tid:
        raise ValueError("need a task_id")
    out = agent_tools.run_tool(_store(), {"name": "task_complete", "args": {"task_id": tid}}, agent_id=agent)
    if out.get("status") != "ok":
        raise ValueError(out.get("error") or "complete failed")
    t = out["data"]
    return f"Task completed: {t.get('title')} ({t.get('id')})"


def tool_task_reopen(arg, agent):
    """Reopen a completed task in the ledger."""
    if agent_tools is None:
        raise ValueError("tool layer not available")
    tid = (arg or "").strip()
    if not tid:
        raise ValueError("need a task_id")
    out = agent_tools.run_tool(_store(), {"name": "task_reopen", "args": {"task_id": tid}}, agent_id=agent)
    if out.get("status") != "ok":
        raise ValueError(out.get("error") or "reopen failed")
    t = out["data"]
    return f"Task reopened: {t.get('title')} ({t.get('id')})"


def tool_task_note(arg, agent):
    """Append a step or note to a task. Format: task_id | step text"""
    if agent_tools is None:
        raise ValueError("tool layer not available")
    raw = (arg or "").strip()
    if "|" not in raw:
        raise ValueError("use: task_id | step text")
    tid, _, step = raw.partition("|")
    tid, step = tid.strip(), step.strip()
    if not tid or not step:
        raise ValueError("need task_id and step text")
    out = agent_tools.run_tool(_store(), {"name": "task_note", "args": {"task_id": tid, "step": step}}, agent_id=agent)
    if out.get("status") != "ok":
        raise ValueError(out.get("error") or "note failed")
    return f"Noted on {tid}: {step[:120]}"


# Descriptions for the TOOLS registry (name -> (prompt line, fn, who-or-None))
BRIDGE_TOOLS = {
    "web_search": ("web_search | <query>   (search the web; read-only)", tool_web_search, None),
    "fetch_page": ("fetch_page | <https URL>   (read a public page; SSRF-guarded, read-only)", tool_fetch_page, None),
    "task_create": ("task_create | <title>   (add a task to the persistent ledger)", tool_task_create, None),
    "task_list": ("task_list | open|done|all   (list tasks in the ledger)", tool_task_list, None),
    "task_complete": ("task_complete | <task_id>   (mark a ledger task done)", tool_task_complete, None),
    "task_reopen": ("task_reopen | <task_id>   (reopen a completed task)", tool_task_reopen, None),
    "task_note": ("task_note | <task_id> | <step text>   (append a step to a ledger task)", tool_task_note, None),
}
