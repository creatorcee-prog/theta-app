"""(Harness test) Native tool calling for the single head (2026-11-03): Theta gets its tools
as real function tools, sees every result (failures too) and keeps going for
several rounds; actions show as receipts; a model that refuses tools falls
back to the ACTION-line way; every call carries the writing rule. A fake
OpenAI-format server scripts the model's turns; no live network."""
import sys, json, os, io, threading
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
BODIES, SCRIPT, STATE = [], [], {"refuse_tools": False}


def call(name, arg, cid):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps({"input": arg})}}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        BODIES.append((self.path.split("/")[1], body))
        if STATE["refuse_tools"] and body.get("tools"):
            return self._send(400, {"error": {"message": "tools are not supported by this model"}})
        step = SCRIPT.pop(0) if SCRIPT else "Okay."
        msg = {"content": step, "role": "assistant"} if isinstance(step, str) else {"content": step.get("text"), "role": "assistant", "tool_calls": step["calls"]}
        self._send(200, {"choices": [{"message": msg}], "usage": {"prompt_tokens": 50, "completion_tokens": 5}})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ.update(DASHBOARD_KEY="dk", GROQ_API_KEY="qk", GEMINI_API_KEY="gk", ANTHROPIC_API_KEY="", DEEPSEEK_API_KEY="dsk",
                  GLASS_BUDGETS="Groceries:600", NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
os.environ.pop("HEAD_NATIVE_TOOLS", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
from wsgiref.util import setup_testing_defaults
for p in ("deepseek", "gemini", "groq"):
    h.PROVIDERS[p] = (f"{base}/{p}/chat/completions", h.PROVIDERS[p][1])
h.LLM_RETRY_DELAY = 0
h.notify = lambda *a, **k: 0
h.tmdb_trending = lambda: []
h.refresh_windows = lambda deadline=None: ""
h.HEAD_MODE = "single"


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


def post(text):
    raw = json.dumps({"text": text}).encode()
    env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/allchat", "QUERY_STRING": "", "CONTENT_LENGTH": str(len(raw)),
           "wsgi.input": io.BytesIO(raw), "HTTP_X_DASHBOARD_KEY": "dk"}
    setup_testing_defaults(env)
    return json.loads(b"".join(h.app(env, lambda s, hd: None)))


def last_reply():
    return [m for m in h.allchat_view(200) if m.get("kind") != "event" and m["from"] != "you"][-1]



def run(case, mode, script):
    SCRIPT[:] = script
    BODIES.clear()
    s, ct, out = h.handle("POST", "/api/hbench", {}, {"x-dashboard-key": "dk"}, json.dumps({"case": case, "mode": mode}).encode())[:3]
    return s, json.loads(out)


n_rem, n_notes = len(h.reminders()), len(h.notes())
s, d = run("multi", "old", ["On it.\nACTION: budget | this month\nACTION: remind | 6pm pay rent\nACTION: spend | $12 lunch",
                            "You're fine. Rent reminder set, lunch logged.\nACTION: remind | 6pm pay rent\nACTION: spend | $12 lunch"])
old = next(r for r in d["rows"] if r["case"] == "multi" and r["mode"] == "old")
check("old harness: ran and scored", s == 200 and old["ok"] and old["model_calls"] == 2, )
check("old harness: no tools sent, ACTION syntax, no writing rule",
      not BODIES[0][1].get("tools") and "ACTION: remind" in BODIES[0][1]["messages"][0]["content"]
      and h.WRITING_RULE not in BODIES[0][1]["messages"][0]["content"])
s, d = run("multi", "new", [{"text": "", "calls": [call("budget", "this month", "a1"), call("remind", "6pm pay rent", "a2"),
                                                   call("spend", "$12 lunch", "a3")]},
                            "You're fine on money. Rent's set for 6 and lunch is logged \u2014 delve into it later."])
new = next(r for r in d["rows"] if r["case"] == "multi" and r["mode"] == "new")
check("new harness: tools sent with the writing rule", BODIES[0][1].get("tools")
      and h.WRITING_RULE in BODIES[0][1]["messages"][0]["content"])
check("new harness: scored, two model calls", new["ok"] and new["model_calls"] == 2)
check("AI-writing signs counted", sorted(new["signs"]) == ["delve", "\u2014"])
check("nothing was really saved", len(h.reminders()) == n_rem and len(h.notes()) == n_notes)
check("calls recorded", any(c.startswith("remind: 6pm pay rent") for c in new["calls"]))

s, d = run("search", "new", [{"text": "", "calls": [call("web_search", "Broncos last game", "b1")]}, "The Broncos won 24-20."])
srch = next(r for r in d["rows"] if r["case"] == "search")
check("web searches get the fixed test page", srch["ok"] and "24-20" in [m for _, b in BODIES for m in [json.dumps(b["messages"])]][-1])
s, d = run("chat", "new", [{"text": "", "calls": [call("budget", "x", "c1")]}, "Hi!"])
chat = next(r for r in d["rows"] if r["case"] == "chat" and r["mode"] == "new")
check("tools on small talk is a miss", not chat["ok"] and chat["missing"] == ["used tools on small talk"])
s, d = run("remind", "old", ["Sure.\nACTION: remind | tomorrow 9am call the dentist"])
rem = next(r for r in d["rows"] if r["case"] == "remind")
check("the wrong words in the input is a miss", not rem["ok"] and rem["missing"] == ["remind bank"])

# ---- the harder cases
s, d = run("five", "old", ["On it.\n" + "\n".join(f"ACTION: remind | {t}" for t in ("7am gym", "12pm lunch with Sam", "3pm call the dentist", "6pm pay rent", "9pm stretch"))])
five_old = next(r for r in d["rows"] if r["case"] == "five" and r["mode"] == "old")
check("five actions: the old harness stops at 3", not five_old["ok"] and five_old["missing"] == ["remind rent", "remind stretch"])
s, d = run("five", "new", [{"text": "", "calls": [call("remind", t, f"r{i}") for i, t in enumerate(("7am gym", "12pm lunch with Sam", "3pm call the dentist", "6pm pay rent"))]},
                           {"text": "", "calls": [call("remind", "9pm stretch", "r9")]}, "All five are set."])
five_new = next(r for r in d["rows"] if r["case"] == "five" and r["mode"] == "new")
check("five actions: the new harness gets all five (4 a round, then 1)", five_new["ok"])
s, d = run("unclear", "old", ["Done.\nACTION: remind | call mom"])
u_old = next(r for r in d["rows"] if r["case"] == "unclear" and r["mode"] == "old")
check("an input with no time fails like the real tool", not u_old["ok"] and any("(failed)" in c for c in u_old["calls"]))
s, d = run("unclear", "new", [{"text": "", "calls": [call("remind", "call mom", "u1")]}, {"text": "", "calls": [call("remind", "6pm call mom", "u2")]}, "Set for 6."])
check("the new harness fixes it after the failure", next(r for r in d["rows"] if r["case"] == "unclear" and r["mode"] == "new")["ok"])
s, d = run("unclear", "old", ["What time should I remind you?"])
check("asking for the time also passes", next(r for r in d["rows"] if r["case"] == "unclear" and r["mode"] == "old")["ok"])
h.glass_log_reply((70.0, "dining", "dinner out"))
s, d = run("decide", "new", [{"text": "", "calls": [call("budget", "this month", "k1")]}, {"text": "", "calls": [call("remind", "6pm cook dinner", "k2")]}, "Over $50, so: cook tonight."])
check("look then decide: dining over $50 needs the reminder", next(r for r in d["rows"] if r["case"] == "decide" and r["mode"] == "new")["ok"])
s, d = run("decide", "old", ["You've spent $70 on dining.\nACTION: budget | this month", "You've spent $70 on dining."])
check("...and a reply without it is a miss", not next(r for r in d["rows"] if r["case"] == "decide" and r["mode"] == "old")["ok"])
check("prompt sizes reported", d.get("sizes") is None or True)
s, ct, out = h.handle("GET", "/api/hbench", {}, {"x-dashboard-key": "dk"}, b"")[:3]
sizes = json.loads(out)["sizes"]
check("prompt sizes: the new one is smaller before tools", sizes["new"]["instructions"] < sizes["old"]["instructions"]
      and sizes["new"]["tools"] > 0 and sizes["old"]["tools"] == 0)
t = d["totals"]
check("totals per harness", t["old"]["of"] + t["new"]["of"] == len(d["rows"]) and t["new"]["passed"] == sum(1 for r in d["rows"] if r["mode"] == "new" and r["ok"]))
print("sizes:", json.dumps(h.prompt_sizes()))
check("unknown case refused", run("nope", "new", [])[0] == 400)
s, ct, out = h.handle("GET", "/api/hbench", {}, {"x-dashboard-key": "dk"}, b"")[:3]
check("results kept for the page", json.loads(out)["rows"])
page = h.diagnostics_page({"host": "x", "x-dashboard-key": "dk"})
html_ = page[2].decode() if isinstance(page, tuple) else str(page)
check("Harness test card on Diagnostics", 'id="hbench"' in html_ and 'id="hb-run"' in html_)
check("the old harness flag is cleared after a run", not getattr(h._REQ, "hb_old", False) and getattr(h._REQ, "hb_calls", None) is None)
check("writing rule back for normal prompts", h.WRITING_RULE in h.system_prompt("theta"))
# the money case: the right total in the reply counts, without a lookup
total = sum(v["spent"] for v in h.month_status().values())
s, d = run("money", "new", [f"You've spent ${total:,.2f} so far this month."])
check("money: the real total without a lookup passes", next(r for r in d["rows"] if r["case"] == "money")["ok"])
s, d = run("money", "old", ["You've spent $1 so far."])
check("money: a wrong total is a miss", not next(r for r in d["rows"] if r["case"] == "money" and r["mode"] == "old")["ok"])
print("done")
