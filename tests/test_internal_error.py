"""Reproduce Theta's "internal error" on Mistral tool calls, then prove the fix.

The literal "internal error" comes from exactly one place: app()'s
top-level catch, which fires only when an exception escapes handle().
Six mocked scenarios, no production tasks touched:

1. Valid task_create -> 200, task in the ledger, receipt in the reply.
2. Malformed tool arguments (empty ACTION arg) -> 200, no task, no 500.
   (Malformed lines match no ACTION, so nothing runs: silent, but not a 500.)
3. The tool dispatcher raises a non-ValueError -> must NOT be a 500.
   Before the fix, run_actions only caught (ValueError, CommandError,
   LLMError), so a RuntimeError from any tool escaped to "internal error".
4. Provider HTTP error -> LLMError -> errors dict, 200, not a 500.
5. Tool succeeds but reply persistence fails -> must NOT be a 500.
   Before the fix, the reply save in /api/allchat was unguarded, so a
   store failure there returned "internal error" even though the task
   had already been created. The fixed response says so explicitly.
6. Tool call plus final text -> 200, task created, receipt + text saved.

Scenarios 3 and 5 assert the FIXED behavior, so this file FAILS on
pre-fix code (500 "internal error") and PASSES with the fix. The
diagnostics assertions (a stage line with the exception class) fail
on pre-fix code too, since the old catch logged no stage at all.
"""
import sys, os, io, json, threading, contextlib
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from wsgiref.util import setup_testing_defaults

SCRIPT = {"status": 200, "content": "ok", "error": "provider boom"}
DB = {}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        ln = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(ln) if ln else b""
        if self.path.startswith("/redis"):
            body = json.loads(raw or b"[]")
            op, k, a = body[0], body[1], body[2:]
            if op == "INCR":
                DB[k] = DB.get(k, 0) + 1
                r = DB[k]
            elif op == "LPUSH":
                DB.setdefault(k, []).insert(0, a[0])
                r = 1
            elif op == "LTRIM":
                DB[k] = DB.get(k, [])[int(a[0]):int(a[1]) + 1]
                r = "OK"
            elif op == "LRANGE":
                l = DB.get(k, [])
                e = int(a[1])
                r = l[int(a[0]):(None if e == -1 else e + 1)]
            elif op == "SET":
                DB[k] = a[0]
                r = "OK"
            elif op == "GET":
                r = DB.get(k)
            elif op == "HSET":
                h_ = DB.setdefault(k, {})
                r = sum(1 for x in a[::2] if x not in h_)
                h_.update(zip(a[::2], a[1::2]))
            elif op == "HGET":
                r = DB.get(k, {}).get(a[0])
            elif op == "HMGET":
                r = [DB.get(k, {}).get(x) for x in a]
            elif op == "HGETALL":
                r = [x for kv in DB.get(k, {}).items() for x in kv]
            else:
                r = None
            return self._send(200, {"result": r})
        if SCRIPT["status"] != 200:
            return self._send(SCRIPT["status"], {"error": {"message": SCRIPT["error"]}})
        return self._send(200, {"choices": [{"message": {"content": SCRIPT["content"]}}]})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="glass:gk1,lenz:lk", GROQ_API_KEY="<redacted>", GEMINI_API_KEY="<redacted>",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g",
                  VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="<redacted>")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        if detail:
            print(detail[-2000:])
        sys.exit(1)


def call(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs,
           "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items():
        env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env)
    got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s, h=dict(hd))))
    return int(got["s"][:3]), (json.loads(out) if out[:1] in (b"{", b"[") else out)


K = {"x-dashboard-key": "dk"}


def post_chat(text):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        s, b = call("POST", "/api/allchat", headers=K, body={"text": text, "channel": "all", "rid": "testrid1"})
    return s, b, buf.getvalue()


def ledger():
    out = h.run_actions("mistral", "ACTION: task_list | open")
    return out if isinstance(out, str) else ""


def all_text(messages):
    return "\n".join(m.get("text", "") for m in messages if isinstance(m, dict))


# 1. Valid task_create.
SCRIPT.update(status=200, content="ACTION: task_create | repro one")
s, b, _ = post_chat("please create a task")
check("1 valid task_create returns 200", s == 200, f"status={s} body={b!r}"[:500])
check("1 task is in the ledger", "repro one" in ledger())
check("1 reply carries the receipt", "Task created: repro one" in all_text(b.get("messages", [])))

# 2. Malformed tool arguments: empty ACTION arg matches nothing.
SCRIPT.update(status=200, content="ACTION: task_create |")
s, b, _ = post_chat("please create a task")
check("2 malformed args do not 500", s == 200, f"status={s} body={b!r}"[:500])
check("2 malformed args create no task", "repro two" not in ledger())

# 3. The tool dispatcher raises a non-ValueError.
orig = h.TOOLS["task_create"]


def boom(arg, agent):
    raise RuntimeError("dispatcher boom")


h.TOOLS["task_create"] = (orig[0], boom, None)
try:
    SCRIPT.update(status=200, content="ACTION: task_create | repro three")
    s, b, log = post_chat("please create a task")
finally:
    h.TOOLS["task_create"] = orig
check("3 dispatcher exception is not a 500", s == 200, f"status={s} body={b!r}"[:500])
check("3 dispatcher failure is a visible receipt",
      "task_create" in all_text(b.get("messages", [])) and "dispatcher boom" in all_text(b.get("messages", [])))
check("3 dispatcher failure is logged with its class",
      "stage=tool.done" in log and "status=error" in log, log[-500:])

# 4. Provider HTTP error.
SCRIPT.update(status=500, content="ignored")
s, b, _ = post_chat("please create a task")
check("4 provider error is not a 500", s == 200, f"status={s} body={b!r}"[:500])
check("4 provider error lands in errors", bool(b.get("errors")), f"body={b!r}"[:500])
check("4 provider error is not the generic message", b.get("error") != "internal error")

# 5. Tool succeeds but reply persistence fails.
real_store = h.store()


class FailSaveProxy:
    """The store works, except saving an assistant reply raises: the
    task_create ledger writes go through, the reply save does not."""

    def __init__(self, real):
        self._real = real

    def add_chat(self, sender, *a, **kw):
        if sender != "you":
            raise RuntimeError("KV error: boom")
        return self._real.add_chat(sender, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._real, name)


h._STORE = FailSaveProxy(real_store)
try:
    SCRIPT.update(status=200, content="ACTION: task_create | repro five")
    s, b, log = post_chat("please create a task")
finally:
    h._STORE = real_store
check("5 persistence failure is not a generic 500", s != 500 or b.get("error") != "internal error",
      f"status={s} body={b!r}"[:500])
check("5 persistence failure names the stage", "couldn't save the reply" in str(b.get("error", "")),
      f"body={b!r}"[:500])
check("5 the task still exists despite the failed reply", "repro five" in ledger())
check("5 persistence failure is logged with its class",
      "stage=reply.persist_failed" in log and "RuntimeError" in log, log[-500:])

# 6. Tool call followed by a final assistant response.
SCRIPT.update(status=200, content="Starting the test.\nACTION: task_create | repro six\nAll done.")
s, b, _ = post_chat("please create a task")
check("6 tool call + final response returns 200", s == 200, f"status={s} body={b!r}"[:500])
check("6 task is in the ledger", "repro six" in ledger())
msgs = all_text(b.get("messages", []))
check("6 receipt and final text are both saved", "Task created: repro six" in msgs and "All done." in msgs)
print("done")
