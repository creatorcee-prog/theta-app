"""Phase F1: follows record + agent tools.

Through the real agent path (run_actions -> bridge -> tools.py), no
stubs: create (verified by read-back), duplicate suppression, list,
cancel (record kept), invalid input, remember-vs-follow honesty, and
persistence across a store reload (redis mode only: the memory store
is documented as not persistent, so that check is skipped there).
"""
import sys, json, threading, os, re
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer

mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
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
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else []
        op, k, a = body[0], body[1], body[2:]
        if op == "GET":
            r = DB.get(k)
        elif op == "SET":
            DB[k] = a[0]
            r = "OK"
        else:
            r = None
        self._send(200, {"result": r})


srv = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="lenz:lk", GEMINI_API_KEY="g", GROQ_API_KEY="q",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="t")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


# Create: verified record, honest receipt (checks are NOT live until F2).
r = h.run_actions("lenz", "ACTION: follow_create | Godzilla Minus Zero | movie")
check("follow_create receipt states title, state, frequency, verification",
      "✓" in r and "Following: Godzilla Minus Zero" in r and "active" in r
      and "checks daily" in r and "Record verified" in r)
check("follow_create receipt is honest that checks are not live yet",
      "not live yet" in r and "nothing will notify" in r)
m = re.search(r"\(id (f\d+)", r)
check("follow_create receipt carries the record id", bool(m))
fid = m.group(1)

# Duplicate: same normalized title + kind returns the existing record.
r = h.run_actions("lenz", "ACTION: follow_create | godzilla  minus zero | movie")
check("duplicate follow returns the existing record, no new one",
      "Already following" in r and fid in r)
r = h.run_actions("lenz", "ACTION: follow_list | active")
check("follow_list shows the one active follow",
      "Godzilla Minus Zero" in r and r.count("Godzilla Minus Zero") == 1)

# Invalid input is an error, never a silent record.
r = h.run_actions("lenz", "ACTION: follow_create | ")
check("empty title is an error", "✗" in r and "need a title" in r)
r = h.run_actions("lenz", "ACTION: follow_create | Some Thing | movie | fortnightly")
check("bad frequency is an error", "✗" in r and "unknown frequency" in r)
r = h.run_actions("lenz", "ACTION: follow_create | Some Thing | movie | daily | both | carrier-pigeon")
check("bad source is an error", "✗" in r and "unknown source" in r)
r = h.run_actions("lenz", "ACTION: follow_cancel | f0000000000")
check("canceling an unknown follow is an error", "✗" in r and "follow not found" in r)

# Cancel: state flips, record kept, cancel again is idempotent.
r = h.run_actions("lenz", f"ACTION: follow_cancel | {fid}")
check("follow_cancel receipt", "✓" in r and "Follow canceled" in r and "kept as canceled" in r)
r = h.run_actions("lenz", f"ACTION: follow_cancel | {fid}")
check("canceling again is idempotent", "Already canceled" in r)
r = h.run_actions("lenz", "ACTION: follow_list | all")
check("canceled record is still listed under all",
      "Godzilla Minus Zero" in r and "canceled" in r)
r = h.run_actions("lenz", "ACTION: follow_list | active")
check("canceled follow leaves the active list", "Godzilla Minus Zero" not in r)

# A saved note is not a follow: remember says so, and creates no record.
r = h.run_actions("lenz", "ACTION: remember | Likes Godzilla Minus Zero")
check("remember receipt says it is not monitoring", "not monitoring" in r)
r = h.run_actions("lenz", "ACTION: follow_list | all")
check("remember created no follow record", "Likes Godzilla Minus Zero" not in r)

# Persistence across a store reload (simulated restart).
if mode == "redis":
    h._STORE = None
    fresh = h.store()
    raw = fresh._cmd("GET", "hub:follows")
    items = json.loads(raw) if raw else []
    check("follow record survives a store reload (redis)",
          any(f.get("id") == fid and f.get("state") == "canceled" for f in items))
else:
    print("SKIP restart persistence in memory mode (store is not persistent)")

print("ALL PASS")
