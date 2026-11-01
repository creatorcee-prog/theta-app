"""Regression test: the bridge must use the ALREADY-LOADED hub module,
not `import index`.

test_bridge_nopath.py loads index.py by path but registers it as
"index" in sys.modules, so the bridge's old `import index` fallback
still found it there. Under Vercel's actual loading the entrypoint
may be held under a different name (or not registered at all), so
`import index` can fail outright — or, worse, load a SECOND copy of
the 700KB hub module with its own store, so a task created through
the bridge lands in a different store than the hub reads.

So this test spawns a clean subprocess that loads api/index.py by
file path under a NON-"index" name, with the api dir scrubbed from
sys.path and "index" never placed in sys.modules. The only way
task_create can then succeed is the injected reference: index.py's
loader hands the bridge its own store() (HUB_STORE), resolved at
call time. The test requires, in order: the reference is the hub's
own function, it returns the hub's own store object, no "index"
module appears in sys.modules before or after the tool runs, and an
actual task_create + task_list through run_actions succeed with the
task visible in the hub's ledger. The ledger runs on the memory
store in the child: this test varies the module loading, not the
storage backend, so it is identical in both run_all.sh modes.

A negative control runs the same child against the OLD bridge
(plain `import index` in _store): it must fail, proving the test
detects the fragility instead of passing vacuously.
"""
import sys, os, subprocess, tempfile, shutil
sys.dont_write_bytecode = True

CHILD = r'''
import sys, os
api_dir = os.path.abspath(sys.argv[1])
# Simulate Vercel-style loading: the entrypoint is loaded by file
# path, api/ is not on sys.path, and nothing is registered as "index".
sys.path = [p for p in sys.path
            if p not in ("",) and os.path.abspath(p) != api_dir]
os.chdir("/tmp")
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="glass:gk1,lenz:lk", GROQ_API_KEY="<redacted>", GEMINI_API_KEY="<redacted>",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g",
                  VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="")
os.environ.pop("KV_REST_API_URL", None)  # memory store: loading, not storage, is under test
os.environ.pop("KV_REST_API_TOKEN", None)
import importlib.util
spec = importlib.util.spec_from_file_location("theta_hub", os.path.join(api_dir, "index.py"))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
TEN = ["web_search", "fetch_page", "task_create", "task_list", "task_complete", "task_reopen", "task_note", "follow_create", "follow_list", "follow_cancel"]
assert h.BRIDGE_IMPORT_ERROR is None, h.BRIDGE_IMPORT_ERROR
assert sorted(h.BRIDGE_TOOLS) == sorted(TEN), sorted(h.BRIDGE_TOOLS)
assert "index" not in sys.modules, "hub was imported as 'index' during load"
# The injected reference must be the hub's own store function, and it
# must return the hub's own store object: no second copy of the hub.
assert getattr(h._tb, "HUB_STORE", None) is h._bridge_store, "bridge has no injected hub reference"
assert h._tb.HUB_STORE() is h.store(), "bridge store is not the hub store"
out = h.run_actions("mistral", "ACTION: task_create | hubref probe")
assert isinstance(out, str) and "Task created: hubref probe" in out, out
out = h.run_actions("mistral", "ACTION: task_list | open")
assert "hubref probe" in out, out
assert "index" not in sys.modules, "hub was imported as 'index' during tool runs"
diag = h.tools_diag()
assert diag["import_error"] is None, diag
assert diag["tools_layer"] == "ok", diag
assert sorted(diag["bridge_tools"]) == sorted(TEN), diag
assert all(diag["mistral_prompt"].values()), diag
print("CHILD-OK")
'''

OLD_STORE = '''def _store():
    """Lazy import of the hub store to avoid circular imports at load time."""
    import index as h
    return h.store()'''


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        if detail:
            print(detail[-3000:])
        sys.exit(1)


def run_child(d):
    return subprocess.run([sys.executable, "-c", CHILD, d],
                          capture_output=True, text=True, timeout=180, cwd="/tmp")


HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.join(HERE, "..", "api")
tmp = tempfile.mkdtemp(prefix="theta-hubref-")
ctl = tempfile.mkdtemp(prefix="theta-hubref-old-")
try:
    for f in ("index.py", "tool_bridge.py", "tools.py"):
        shutil.copy(os.path.join(API, f), os.path.join(tmp, f))
    shutil.copytree(os.path.join(API, "_parts"), os.path.join(tmp, "_parts"))  # index.py's parts (Stage 7.2)
    shutil.copytree(os.path.join(API, "_parts"), os.path.join(ctl, "_parts"))  # index.py's parts (Stage 7.2)
    for f in ("index.py", "tools.py"):
        shutil.copy(os.path.join(API, f), os.path.join(ctl, f))
    # Old bridge: the new _store chain replaced by the plain import.
    bridge = open(os.path.join(API, "tool_bridge.py")).read()
    start = bridge.index("# Set by api/index.py's loader")
    end = bridge.index("def tool_web_search")
    bridge_old = bridge[:start] + OLD_STORE + "\n\n\n" + bridge[end:]
    assert "HUB_STORE" not in bridge_old and "import index as h" in bridge_old
    open(os.path.join(ctl, "tool_bridge.py"), "w").write(bridge_old)

    r = run_child(tmp)
    check("bridge uses the already-loaded hub (no 'index' module, no second copy)",
          r.returncode == 0 and "CHILD-OK" in r.stdout,
          "STDOUT:\n" + r.stdout + "\nSTDERR:\n" + r.stderr)
    r = run_child(ctl)
    check("negative control: old `import index` bridge fails the same setup",
          r.returncode != 0 and "CHILD-OK" not in r.stdout,
          "STDOUT:\n" + r.stdout + "\nSTDERR:\n" + r.stderr)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(ctl, ignore_errors=True)
print("done")
