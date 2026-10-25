"""Regression test: the Phase 4 tools must REGISTER and EXECUTE even when
the api/ directory is NOT on sys.path (the Vercel function-directory
case that the PR #45 bridge import already survived once).

A plain registration check is not enough: tool_bridge.py used to do
`import tools` off sys.path, which would have left the tools listed in
the prompt but unusable ("tool layer not available" at call time). So
this test spawns a clean subprocess that loads api/index.py by file
path with the api dir scrubbed from sys.path, then runs an ACTUAL tool
execution (task_create + task_list through run_actions) and requires
receipts. The ledger runs on the memory store in the child: this test
varies the import path, not the storage backend, so it is identical in
both run_all.sh modes."""
import sys, os, subprocess, tempfile, shutil
sys.dont_write_bytecode = True

CHILD = r'''
import sys, os
api_dir = os.path.abspath(sys.argv[1])
# Simulate the deployment condition: api/ must not be on sys.path.
sys.path = [p for p in sys.path
            if p not in ("",) and os.path.abspath(p) != api_dir]
os.chdir("/tmp")
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="glass:gk1,lenz:lk", GROQ_API_KEY="<redacted>", GEMINI_API_KEY="<redacted>",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g",
                  VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="")
import importlib.util
spec = importlib.util.spec_from_file_location("index", os.path.join(api_dir, "index.py"))
h = importlib.util.module_from_spec(spec)
sys.modules["index"] = h  # the entry module, as a function runtime holds it
spec.loader.exec_module(h)
SEVEN = ["web_search", "fetch_page", "task_create", "task_list", "task_complete", "task_reopen", "task_note"]
assert h.BRIDGE_IMPORT_ERROR is None, h.BRIDGE_IMPORT_ERROR
assert sorted(h.BRIDGE_TOOLS) == sorted(SEVEN), sorted(h.BRIDGE_TOOLS)
diag = h.tools_diag()
assert diag["tools_layer"] == "ok", diag
p = h.tools_prompt("mistral")
assert all(f"ACTION: {t} |" in p for t in SEVEN), "prompt missing tools"
out = h.run_actions("mistral", "ACTION: task_create | nopath probe")
assert isinstance(out, str) and "Task created: nopath probe" in out, out
out = h.run_actions("mistral", "ACTION: task_list | open")
assert "nopath probe" in out, out
print("CHILD-OK")
'''


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        if detail:
            print(detail[-3000:])
        sys.exit(1)


HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.join(HERE, "..", "api")
tmp = tempfile.mkdtemp(prefix="theta-nopath-")
try:
    for f in ("index.py", "tool_bridge.py", "tools.py"):
        shutil.copy(os.path.join(API, f), os.path.join(tmp, f))
    r = subprocess.run([sys.executable, "-c", CHILD, tmp],
                       capture_output=True, text=True, timeout=180, cwd="/tmp")
    check("tools register AND execute with api/ off sys.path",
          r.returncode == 0 and "CHILD-OK" in r.stdout,
          "STDOUT:\n" + r.stdout + "\nSTDERR:\n" + r.stderr)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("done")
