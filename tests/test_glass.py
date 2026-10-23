import sys, json, threading, os, io, time
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, date, timedelta
DB, STATE = {}, {}
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.endswith("/models"): return self._send(200, {"data": [{"id": "openai/gpt-oss-20b"}, {"id": "openai/gpt-oss-120b"}, {"id": "models/gemini-3.8-flash"}]})
        self._send(404, {})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.startswith("/redis"):
            op, k, a = body[0], body[1], body[2:]
            if op == "INCR": DB[k] = DB.get(k, 0) + 1; r = DB[k]
            elif op == "LPUSH": DB.setdefault(k, []).insert(0, a[0]); r = 1
            elif op == "LTRIM": DB[k] = DB.get(k, [])[int(a[0]):int(a[1]) + 1]; r = "OK"
            elif op == "LRANGE":
                l = DB.get(k, []); e = int(a[1]); r = l[int(a[0]):(None if e == -1 else e + 1)]
            elif op == "HSET":
                h_ = DB.setdefault(k, {}); r = sum(1 for x in a[::2] if x not in h_); h_.update(zip(a[::2], a[1::2]))
            elif op == "HGET": r = DB.get(k, {}).get(a[0])
            elif op == "HMGET": r = [DB.get(k, {}).get(x) for x in a]
            elif op == "HGETALL": r = [x for kv in DB.get(k, {}).items() for x in kv]
            elif op == "SMEMBERS": r = []
            elif op == "HDEL": r = sum(1 for x in a if DB.get(k, {}).pop(x, None) is not None)
            return self._send(200, {"result": r})
        STATE["last"] = body
        self._send(200, {"choices": [{"message": {"content": "Glass here."}}]})
srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="lenz:lk", GROQ_API_KEY="qk", GEMINI_API_KEY="gk",
                  GLASS_BUDGETS="Groceries:600,Dining:200,Gas:150,bad:x", GLASS_CATEGORY_MAP="Restaurants:Dining,Coffee:Dining,Groceries & Supermarkets:Groceries",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="t")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.ROUND_POSTS = "agents"  # these tests read each agent's own round post; test_rounds2 covers the summary
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}
from wsgiref.util import setup_testing_defaults
def call(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s)))
    return int(got["s"][:3]), json.loads(out) if out[:1] == b"{" else out
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
K = {"x-dashboard-key": "dk"}
MONTH = datetime.now(h.hub_tz()).strftime("%Y-%m")
print("mode:", mode)

check("budgets parsed, bad value ignored", h.GLASS_BUDGETS == {"Groceries": 600.0, "Dining": 200.0, "Gas": 150.0})
check("parse: amount, budget category, note", h.parse_expense("@glass $42.50 groceries at Costco") == (42.5, "Groceries", "groceries at Costco"))
check("parse: mapped category and thousands", h.parse_expense("$1,200 coffee beans bulk")[:2] == (1200.0, "Dining"))
check("parse: unknown category -> Other", h.parse_expense("$9 parking")[1] == "Other")
check("parse: no $ -> not an expense", h.parse_expense("@glass how much on groceries?") is None and h.parse_expense("I ran 5 miles") is None)

s, d = call("POST", "/api/chat", headers=K, body={"agent": "glass", "messages": [{"role": "user", "content": "$42.50 groceries at Costco"}]})
check("1:1 chat logs it with exact numbers, no model call", s == 200 and d["reply"] == "Logged $42.50 for Groceries (groceries at Costco). Groceries this month: $42.50 of $600." and "last" not in STATE)
s, d = call("POST", "/api/allchat", headers=K, body={"text": "@glass $20 Restaurants with Sam"})
check("All Agents @glass logs too (mapped Restaurants -> Dining)", d["messages"][-1]["text"].startswith("Logged $20.00 for Dining"))
s, d = call("POST", "/api/allchat", headers=K, body={"text": "@glass $20 Restaurants with Sam"})
check("same purchase logged twice counts twice", "Dining this month: $40.00 of $200." in d["messages"][-1]["text"])
s, d = call("POST", "/api/chat", headers=K, body={"agent": "glass", "messages": [{"role": "user", "content": "How am I doing this month?"}]})
sysmsg = STATE["last"]["messages"][0]["content"]
check("questions go to the model with exact month status", s == 200 and "Groceries: $42.50 of $600 (7%)" in sysmsg and "Dining: $40.00 of $200 (20%)" in sysmsg and "never invent numbers" in sysmsg)

s, d = call("POST", "/api/glass/expense", headers={"x-bot-key": "lk"}, body={"bot_id": "lenz", "amount": 15.99, "category": "Fun", "note": "movie"})
check("bot logs an expense; event names the bot", s == 200 and d["expense"]["category"] == "Fun" and call("GET", "/api/allchat", "key=dk")[1]["messages"][-1]["text"] == "Glass logged $15.99 for Fun from Lenz")
check("expense validation", call("POST", "/api/glass/expense", headers=K, body={"amount": "x", "category": "a"})[0] == 400 and call("POST", "/api/glass/expense", headers=K, body={"amount": -5, "category": "a"})[0] == 400 and call("POST", "/api/glass/expense", body={"amount": 5, "category": "a"})[0] == 401)

today = datetime.now(h.hub_tz()).date()
d1, d2 = today.strftime("%Y-%m-%d"), (today - timedelta(days=1)).strftime("%m/%d/%Y")
HDR = "Date,Original Date,Account Type,Account Name,Account Number,Institution Name,Name,Custom Name,Amount,Description,Category,Note,Ignored From,Tax Deductible"
CSV = "﻿" + "\n".join([HDR,
  f"{d1},{d1},Credit Card,Visa,1234,Chase,KROGER #12,,85.20,KROGER,Groceries & Supermarkets,,,",
  f"{d1},{d1},Credit Card,Visa,1234,Chase,CHIPOTLE,Lunch w team,14.75,CHIPOTLE,Restaurants,,,",
  f"{d2},{d2},Checking,Main,9999,Chase,ACME PAYROLL,,-2500.00,PAYROLL,Income,,,",
  f"{d2},{d2},Checking,Main,9999,Chase,Transfer to Savings,,500.00,XFER,Internal Transfers,,,",
  f"{d2},{d2},Credit Card,Visa,1234,Chase,AMAZON,,40.00,AMZN,Shopping,,everything,",
  f"{d2},{d2},Credit Card,Visa,1234,Chase,SHELL OIL,,48.10,SHELL,Gas,,,",
  f"{d2},{d2},Credit Card,Visa,1234,Chase,KROGER REFUND,,-10.00,KROGER,Shopping,,,",
  "bad-date,,,,,,X,,1.00,,Gas,,,"])
s, d = call("POST", "/api/glass/import", headers=K, body={"csv": CSV})
check("Rocket Money CSV: 3 expenses, income/transfer/refund/ignored/bad rows skipped", s == 200 and d["added"] == 3 and d["skipped"] == {"income/transfers": 3, "ignored": 1, "unreadable": 1} and d["expenses_were"] == "positive")
check("columns reported; Custom Name preferred", d["columns"] == {"date": "Date", "amount": "Amount", "name": "Custom Name", "category": "Category"})
s, d = call("POST", "/api/glass/import", headers=K, body={"csv": CSV})
check("re-import is safe", d["added"] == 0 and d["duplicates"] == 3)
st = h.month_status(MONTH)
check("imported rows land in mapped budget categories", round(st["Groceries"]["spent"], 2) == 127.70 and round(st["Dining"]["spent"], 2) == 54.75 and round(st["Gas"]["spent"], 2) == 48.10)
neg = "Date,Name,Amount,Category\n" + f"{d1},Gas Station,-30.00,Gas\n{d1},Store,-12.00,Groceries\n{d1},Pay,900.00,Paycheck"
s, d = call("POST", "/api/glass/import", headers=K, body={"csv": neg})
check("negative-expense convention detected", d["added"] == 2 and d["expenses_were"] == "negative" and round(h.month_status(MONTH)["Gas"]["spent"], 2) == 78.10)
s, d = call("POST", "/api/glass/import", headers=K, body={"csv": "Foo,Bar\n1,2"})
check("missing columns: clear error naming what it found", s == 400 and "need Date and Amount" in d["error"] and "Foo" in d["error"])
check("import needs the key", call("POST", "/api/glass/import", body={"csv": CSV})[0] == 401)

# round: alerts
call("POST", "/api/glass/expense", headers=K, body={"amount": 70, "category": "Gas"})  # Gas 148.10 / 150 -> 98%
r = h.run_round(force=True)["ran"]["glass"]
alerts = [m["text"] for m in call("GET", "/api/allchat", "key=dk")[1]["messages"] if m["name"] == "Glass" and m["text"].startswith(("Heads up", "Gas is over"))]
check("90% alert once", r["ok"] and "Gas alert" in r["did"] and alerts[-1] == "Heads up: Gas is at 99% of its budget ($148.10 of $150).")
check("no repeat on the next round", "Gas alert" not in h.run_round(force=True)["ran"]["glass"]["did"])
call("POST", "/api/glass/expense", headers=K, body={"amount": 5, "category": "Gas"})
h.run_round(force=True)
check("100% alert once", [m["text"] for m in call("GET", "/api/allchat", "key=dk")[1]["messages"] if m["name"] == "Glass"][-1] == "Gas is over budget: $153.10 of $150.")
real_dt = h.datetime
class Sunday(real_dt):
    @classmethod
    def now(cls, tz=None): return real_dt.now(tz) + timedelta(days=(6 - real_dt.now(tz).weekday()) % 7)
h.datetime = Sunday
r = h.run_round(force=True)["ran"]["glass"]
h.datetime = real_dt
review = [m["text"] for m in call("GET", "/api/allchat", "key=dk")[1]["messages"] if m["name"] == "Glass"][-1]
check("Sunday: week in review with categories and month status", "posted the week in review" in r["did"] and review.startswith("Week in review") and "Month so far:" in review and "- Gas: $153.10 of $150 (102%)" in review)
s, page = call("GET", "/money", "key=dk"); page = page.decode()
check("money page: bars, over-budget bar, import control", "<h2>Budgets</h2>" in page and "$153.10 <span class=\"muted\">of $150" in page and 'class="bad"' in page and 'id="csv-import"' in page)
s, d = call("GET", "/api/glass", "key=dk")
check("/api/glass returns month status and expenses", s == 200 and d["status"]["Gas"]["budget"] == 150.0 and len(d["expenses"]) >= 8)

# only plain purchases log at once; everything else goes to the desk
for t in ("@glass $42 groceries", "spent $12 on lunch", "paid $80 for gas", "@Glass $9.50 coffee"):
    check(f"a purchase logs at once: {t}", h.looks_like_purchase(t))
for t in ("I'll just tell you what occurred: I attempted to have @Glass set the current balance to $0 but he didn't understand it.",
          "@Glass set the balance to $0", "@glass $254.05 deposit", "@glass got my paycheck, $1,200", "@glass $0 coffee",
          "@glass what did I spend on dining? last time it was $40"):
    check(f"not logged as spending: {t[:50]}", not h.looks_like_purchase(t))
check("$0 never parses as an expense", h.parse_expense("$0 coffee") is None)
n = len(h.store().list_expenses(MONTH))
s, d = call("POST", "/api/allchat", headers=K, body={"text": "@Glass set the balance to $0"})
check("a balance message isn't logged", len(h.store().list_expenses(MONTH)) == n)
s, d = call("POST", "/api/allchat", headers=K, body={"text": "@glass $7.25 snacks"})
check("a plain purchase still logs", len(h.store().list_expenses(MONTH)) == n + 1)
s, d = call("POST", "/api/allchat", headers=K, body={"text": "@glass undo"})
undo = [m for m in d["messages"] if m["from"] == "glass"][-1]["text"]
check("'@glass undo' removes the last chat entry", len(h.store().list_expenses(MONTH)) == n and undo.startswith("Removed $7.25"))
k, e = next(iter(h.store().expense_items(MONTH).items()))
s, page = call("GET", "/money", "key=dk")
check("Money page: a Remove button on each recent expense", f'data-exp-rm="{MONTH}:'.encode() in page)
s, d = call("POST", "/api/glass/remove", headers=K, body={"month": MONTH, "id": k})
check("Remove deletes that one expense", s == 200 and k not in h.store().expense_items(MONTH))
check("removing it again says it's gone", call("POST", "/api/glass/remove", headers=K, body={"month": MONTH, "id": k})[0] == 404)
check("removing needs the key", call("POST", "/api/glass/remove", body={"month": MONTH, "id": "x"})[0] == 401)
check("the crew sees when things were said", h.chat_line({"from": "you", "text": "hi", "at": "2026-10-23 15:13:00"}).startswith("[Oct 23 ")
      and "] You: hi" in h.chat_line({"from": "you", "text": "hi", "at": "2026-10-23 15:13:00"}))
check("every agent knows QWERTY can't change keys", "QWERTY can't set or rotate them" in h.hub_rules("theta")
      and "QWERTY can't set or rotate them" in h.hub_rules("qwerty"))
