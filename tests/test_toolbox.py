"""Tests for api/tools.py: the SSRF guard on page fetch, the structured
tool-result envelope, and the persistent task ledger. No network is
needed: public-IP literals pass the guard without DNS, and the page
parse path is tested through a stubbed opener."""
import sys, os, json, urllib.request
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import tools


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


# --- SSRF guard: what counts as public ---
for host in ("127.0.0.1", "10.0.0.5", "172.16.0.9", "192.168.1.1", "169.254.1.1",
             "::1", "0.0.0.0", "localhost", "224.0.0.1"):
    check(f"{host} is not public", not tools._host_is_public(host))
for host in ("8.8.8.8", "1.1.1.1"):
    check(f"{host} is public", tools._host_is_public(host))

# --- fetch: blocked before connecting, bad scheme rejected ---
r = tools.tool_fetch_page("http://127.0.0.1:9/x")
check("fetch to loopback is blocked before connecting", r["text"].startswith("Blocked:"))
r = tools.tool_fetch_page("http://10.0.0.5/x")
check("fetch to a private address is blocked", r["text"].startswith("Blocked:"))
r = tools.tool_fetch_page("notaurl")
check("non-http URL rejected", r["text"] == "Invalid URL")

# --- redirects to private hosts are refused ---
h = tools._SafeRedirectHandler()
try:
    h.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1/x")
    blocked = False
except ValueError:
    blocked = True
check("redirects to private hosts are refused", blocked)

# --- fetch parses a page through the guarded opener (no live network) ---
real_build = urllib.request.build_opener


class FakeResp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"<html><head><title>Hi</title></head><body><p>Hello world</p></body></html>"

    def geturl(self):
        return "http://8.8.8.8/"


class FakeOpener:
    def open(self, req, timeout=None):
        return FakeResp()


def fake_build(*a):
    if a and a[0] is tools._SafeRedirectHandler:
        return FakeOpener()
    return real_build(*a)


urllib.request.build_opener = fake_build
try:
    r = tools.tool_fetch_page("http://8.8.8.8/")
finally:
    urllib.request.build_opener = real_build
check("fetch parses a page through the guarded opener",
      r["title"] == "Hi" and "Hello world" in r["text"] and r["url"] == "http://8.8.8.8/")

# --- envelope + task ledger (a plain store object uses the in-memory fallback) ---
class FakeStore:
    pass


store = FakeStore()
out = tools.run_tool(store, {"name": "task_create", "args": {"title": "Try the new donut"}}, agent_id="glass")
check("task_create envelope",
      out["status"] == "ok" and out["error"] is None and isinstance(out["duration_ms"], int)
      and out["data"]["status"] == "open" and out["data"]["agent"] == "glass"
      and out["data"]["steps"] == [] and out["data"]["sources"] == [])
tid = out["data"]["id"]
out = tools.run_tool(store, {"name": "task_note",
                             "args": {"task_id": tid, "step": "fetched prices", "result": {"n": 3}}})
check("task_note records steps and results",
      out["status"] == "ok" and out["data"]["steps"] == ["fetched prices"]
      and out["data"]["results"] == [{"n": 3}])
out = tools.run_tool(store, {"name": "task_note",
                             "args": {"task_id": tid, "blocker": "waiting on approval"}})
check("task_note records blockers",
      out["data"]["blockers"] == ["waiting on approval"])
out = tools.run_tool(store, {"name": "task_complete", "args": {"task_id": tid}})
check("task_complete flips status",
      out["status"] == "ok" and out["data"]["status"] == "done" and out["data"]["done"] is True)
out = tools.run_tool(store, {"name": "task_list", "args": {"status": "done"}})
check("task_list finds completed tasks",
      any(t["id"] == tid for t in out["data"]))
out = tools.run_tool(store, {"name": "task_complete", "args": {"task_id": "nope"}})
check("task_complete on a missing task errors",
      out["status"] == "error" and out["error"])
out = tools.run_tool(store, {"name": "task_reopen", "args": {"task_id": tid}})
check("task_reopen flips status back",
      out["status"] == "ok" and out["data"]["status"] == "open" and out["data"]["done"] is False)
out = tools.run_tool(store, {"name": "task_list", "args": {"status": "open"}})
check("task_list finds reopened tasks",
      any(t["id"] == tid for t in out["data"]))
out = tools.run_tool(store, {"name": "task_reopen", "args": {"task_id": tid}})
check("task_reopen of an open task is idempotent",
      out["status"] == "ok" and out["data"]["status"] == "open")
out = tools.run_tool(store, {"name": "task_reopen", "args": {"task_id": "nope"}})
check("task_reopen on a missing task errors",
      out["status"] == "error" and out["error"])
out = tools.run_tool(store, {"name": "task_reopen", "args": {"task_id": ""}})
check("task_reopen without an id errors",
      out["status"] == "error" and out["error"])
out = tools.run_tool(store, {"name": "nope_tool", "args": {}})
check("unknown tool errors in the envelope",
      out["status"] == "error" and "unknown tool" in out["error"])
out = tools.run_tool(store, {"name": "fetch_page", "args": {"url": "http://10.0.0.5/x"}})
check("fetch_page envelope reports a blocked host as an error",
      out["status"] == "error" and "Blocked" in out["error"])
print("done")
