"""Native tool calling for the single head (2026-11-03): Theta gets its tools
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


check("native tool calling is on by default", h.HEAD_NATIVE)

# ---- a plain answer: tools offered, none used
BODIES.clear(); SCRIPT[:] = ["Hey! What's up?"]
post("hey")
who, body = BODIES[0]
names = [t["function"]["name"] for t in body["tools"]]
check("tools sent as function tools", who == "deepseek" and "remind" in names and "calendar" in names and "focus" in names
      and body["tool_choice"] == "auto")
check("each tool takes one text input", all(t["function"]["parameters"]["required"] == ["input"] for t in body["tools"]))
check("no ACTION syntax in the prompt", "ACTION: remind" not in body["messages"][0]["content"])
check("the writing rule is in the prompt", "signs of AI writing" in body["messages"][0]["content"]
      and "delve" in body["messages"][0]["content"])
check("plain answer", last_reply()["text"] == "Hey! What's up?")

# ---- a multi-step job: a lookup, then actions, then the answer
BODIES.clear()
SCRIPT[:] = [{"text": "", "calls": [call("budget", "this month", "c1")]},
             {"text": "", "calls": [call("remind", "tomorrow 9am call the bank", "c2"), call("spend", "$12 lunch", "c3")]},
             "You're fine on money. Reminder's set and lunch is logged."]
post("check my budget, remind me to call the bank tomorrow at 9 and log $12 lunch")
r = last_reply()["text"]
check("three model turns", len(BODIES) == 3)
second = BODIES[1][1]["messages"]
check("the lookup's result came back to the model", any(m["role"] == "tool" and m["tool_call_id"] == "c1"
                                                        and "Budgets this month" in m["content"] for m in second))
third = BODIES[2][1]["messages"]
check("both actions ran and came back", any(m["role"] == "tool" and m["tool_call_id"] == "c2" and m["content"].startswith("done:")
                                            for m in third) and any(m.get("tool_call_id") == "c3" for m in third))
check("the answer, then receipts for what changed (not the lookup)", r.startswith("You're fine on money.")
      and "✓ Reminder set" in r and "✓ Logged $12.00" in r and "Budgets this month" not in r)
check("the reminder really exists", any("call the bank" in x["what"] for x in h.reminders()))

# ---- a failure goes back to the model, which fixes its input
BODIES.clear()
SCRIPT[:] = [{"text": "", "calls": [call("remind", "sometime call mom", "d1")]},
             {"text": "", "calls": [call("remind", "6pm call mom", "d2")]}, "Done, 6 tonight."]
post("could you make sure I call mom tonight")
fail = [m for m in BODIES[1][1]["messages"] if m.get("tool_call_id") == "d1"][0]
check("a failed tool tells the model why", fail["content"].startswith("failed: remind:"))
r = last_reply()["text"]
check("it tried again and the second worked", "✓ Reminder set" in r and "✗" in r)

# ---- the same call twice runs once
n = len(h.reminders())
SCRIPT[:] = [{"text": "", "calls": [call("remind", "7pm stretch", "e1"), call("remind", "7pm stretch", "e2")]}, "Set."]
post("help me not forget to stretch at 7")
check("duplicate calls run once", len(h.reminders()) == n + 1)

# ---- a step budget: after HEAD_TASK_STEPS rounds, it must answer
BODIES.clear()
SCRIPT[:] = [{"text": "", "calls": [call("budget", f"this month {i}", f"f{i}")]} for i in range(h.HEAD_TASK_STEPS)] + ["Here's what I found."]
post("dig into my money")
check("step budget: the last call forbids tools", BODIES[-1][1]["tool_choice"] == "none"
      and len(BODIES) == h.HEAD_TASK_STEPS + 1 and last_reply()["text"] == "Here's what I found.")

# ---- an old habit: ACTION lines in the text still run
SCRIPT[:] = ["Logged it.\nACTION: spend | $5 coffee"]
post("log the coffee from earlier, five bucks")
check("ACTION lines in a native answer still run", "✓ Logged $5.00" in last_reply()["text"])

# ---- a model that refuses tools: the ACTION-line way answers
STATE["refuse_tools"] = True
BODIES.clear(); SCRIPT[:] = ["Still here, the old way."]
post("you there?")
check("refused tools: falls back", last_reply()["text"] == "Still here, the old way."
      and any(not b.get("tools") for _, b in BODIES) and "ACTION:" in [b for _, b in BODIES if not b.get("tools")][0]["messages"][0]["content"])
STATE["refuse_tools"] = False

# ---- DeepSeek writes its tool calls as text (its DSML markup): they run, and the user never sees the markup
DSML = ('Let me look.\n<\uff5cDSML\uff5cfunction_calls>\n<\uff5cDSML\uff5cinvoke name="budget">\n'
        '<\uff5cDSML\uff5cparameter name="input" string="true">this month</\uff5cDSML\uff5cparameter>\n'
        '</\uff5cDSML\uff5cinvoke>\n</\uff5cDSML\uff5cfunction_calls>')
BODIES.clear(); SCRIPT[:] = [DSML, "Money's fine this month."]
post("how's my money")
r = last_reply()["text"]
check("text-form tool calls run as real ones", len(BODIES) == 2 and any(m["role"] == "tool" and "Budgets this month" in m["content"]
                                                                       for m in BODIES[1][1]["messages"]))
check("the markup never reaches the chat", "DSML" not in r and r.startswith("Money's fine"))
check("markup with plain bars and spaces is caught too", h.dsml_calls(DSML.replace("\uff5c", "| ").replace("</", "< /"))[0][0]["function"]["name"] == "budget")
check("ordinary text with pipes is left alone", h.dsml_calls("a | b")[1] == "a | b" and not h.dsml_calls("a | b")[0])
# out of rounds: it's told so outright, and markup in that last answer is stripped
steps = h.HEAD_TASK_STEPS
BODIES.clear(); SCRIPT[:] = [{"text": "", "calls": [call("budget", f"month {i}", f"z{i}")]} for i in range(steps)] + ["Here's what I have." + DSML]
post("dig through every month")
r = last_reply()["text"]
last_msgs = BODIES[-1][1]["messages"]
check("the last round says no more tools", BODIES[-1][1].get("tool_choice") == "none" and last_msgs[-1]["role"] == "user"
      and last_msgs[-1]["content"] == h.HEAD_LAST_ROUND)
check("and its stray markup is stripped", "DSML" not in r and r.startswith("Here's what I have."))

# ---- every head_chat call carries the writing rule
BODIES.clear(); SCRIPT[:] = ["fine"]
h.head_chat([{"role": "user", "content": "summarize this"}], 100)
check("head_chat adds the writing rule", "signs of AI writing" in BODIES[0][1]["messages"][0]["content"])
check("every agent's prompt has it", all(h.WRITING_RULE in h.system_prompt(a) for a in h.AGENTS))
check("no em dash in the writing rule itself", "—" not in h.WRITING_RULE)
print("done")
