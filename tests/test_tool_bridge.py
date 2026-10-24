"""Phase 4: bridge from api/tools.py into the existing ACTION / run_actions path."""
import sys, os
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
os.environ.setdefault("DASHBOARD_KEY", "dk-long-enough-key")
os.environ.setdefault("GROQ_API_KEY", "")
os.environ.setdefault("GEMINI_API_KEY", "")
import index as h


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


# tools are registered
check("web_search in TOOLS", "web_search" in h.TOOLS)
check("fetch_page in TOOLS", "fetch_page" in h.TOOLS)
check("task_create in TOOLS", "task_create" in h.TOOLS)
check("tools_prompt offers fetch_page", "fetch_page" in h.tools_prompt("glass"))
check("tools_prompt offers web_search", "web_search" in h.tools_prompt("mistral"))
check("James still has no tools", "ACTION:" not in h.system_prompt("james", tools=True))

# SSRF still enforced through the bridge
r = h.run_actions("glass", "ACTION: fetch_page | http://127.0.0.1/secret")
check("private host blocked via ACTION", "✗" in str(r) and "Blocked" in str(r))

r = h.run_actions("glass", "ACTION: fetch_page | not-a-url")
check("bad scheme rejected", "✗" in str(r))

# task ledger end-to-end through ACTION
r = h.run_actions("mistral", "ACTION: task_create | Phase 4 bridge test")
check("task_create receipt", "✓" in str(r) and "Phase 4 bridge test" in str(r) and "id t" in str(r))
tid = None
import re
m = re.search(r"id (t\d+)", str(r))
if m:
    tid = m.group(1)
check("got task id", bool(tid))

r = h.run_actions("mistral", f"ACTION: task_note | {tid} | ran bridge test")
check("task_note receipt", "✓" in str(r) and "ran bridge test" in str(r))

r = h.run_actions("mistral", "ACTION: task_list | open")
check("task_list shows open task", "✓" in str(r) and "Phase 4 bridge test" in str(r))

r = h.run_actions("mistral", f"ACTION: task_complete | {tid}")
check("task_complete receipt", "✓" in str(r) and "completed" in str(r).lower())

r = h.run_actions("mistral", "ACTION: task_list | done")
check("task_list done finds it", "✓" in str(r) and "Phase 4 bridge test" in str(r))

# missing / invalid
r = h.run_actions("glass", "ACTION: task_complete | nope-id")
check("missing task errors", "✗" in str(r))

r = h.run_actions("glass", "ACTION: web_search | ")
check("empty search query errors", "✗" in str(r))

# existing tools still work
r = h.run_actions("glass", "ACTION: remember | Bridge test home: Testville")
check("existing remember still works", "✓" in str(r) and "Remembered" in str(r))

print("done")
