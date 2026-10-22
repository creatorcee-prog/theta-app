# Agent Tools: Web Search, Page Fetch & Persistent Tasks

This document describes the two highest-leverage tools to add to Theta.

## 1. Web Search + Page Fetch

### Purpose
Let any agent pull current information from the web instead of being limited to the RSS feeds and APIs already wired.

### Interface (what the agent calls)

```
TOOL: web_search
query: <search terms>
num_results: 5          # optional, default 5

TOOL: fetch_page
url: <https://...>
max_chars: 6000         # optional
```

### Hub functions to implement

```python
def tool_web_search(query: str, num_results: int = 5) -> list[dict]:
    """Return [{title, url, snippet}, ...]"""
    # Recommended providers (pick one):
    # - Tavily (good for agents)
    # - Serper / SerpAPI
    # - Brave Search API
    # - DuckDuckGo (zero cost while testing)
    ...

def tool_fetch_page(url: str, max_chars: int = 6000) -> dict:
    """Return {title, text, url} — cleaned main content."""
    # Reuse the same readability-style cleaning already used for news articles.
    ...
```

### How the agent loop works

1. Agent replies with a `TOOL: ...` block (or structured JSON).
2. Hub parses it, runs the tool, appends the result as a new user message.
3. Agent continues (up to 2 tool rounds) and finally answers the human.

Cache results in Redis for 15–60 minutes.

### Environment variables

```
SEARCH_API_KEY=...          # or TAVILY_API_KEY / SERPER_API_KEY etc.
SEARCH_PROVIDER=tavily      # optional
```

---

## 2. Persistent Tasks / Checklists

### Purpose
Turn markdown checklists into durable work items that survive across messages and can appear on Home.

### Redis keys

```
hub:tasks                 → list of task IDs (newest first)
hub:task:{id}             → JSON {id, title, done, created, updated, by, channel, tags?}
```

### Interface

```
TOOL: task_create
title: Wire web search tool
channel: dev                # optional

TOOL: task_list
status: open                # open | done | all
limit: 20

TOOL: task_complete
task_id: abc123

TOOL: task_reopen
task_id: abc123
```

### Optional auto-parse
When an agent posts a markdown checklist, the hub can optionally extract `- [ ]` items and create tasks automatically.

### Home window
Add a small "Open Tasks" card that calls `task_list(status="open")`.

---

## Integration points in api/index.py

- Add the four tool functions near the other helpers.
- Add a `parse_tool_call(text)` helper.
- Add `run_agent_with_tools(agent_id, messages, max_rounds=2)`.
- Call it from the existing chat reply path (`allchat_reply` / the place that currently does a plain `llm_chat`).
- Expose a simple `GET|POST /api/tasks` for the UI later.

## Suggested order of implementation

1. Redis helpers for tasks (pure data, no external deps).
2. `tool_fetch_page` (you already have article cleaning code).
3. `tool_web_search` (needs an API key).
4. Tool-call parser + agent loop.
5. Wire into chat replies.
6. Optional Home window + `/api/tasks`.
