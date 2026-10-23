import sys, json, threading, os, io, time, re
import xml.etree.ElementTree as ET
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta
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
            return self._send(200, {"result": r})
        STATE["last"] = body
        who = body["messages"][0]["content"].split(",")[0].replace("You are ", "")
        if "You route messages" in body["messages"][-1]["content"]:
            return self._send(200, {"choices": [{"message": {"content": "charter"}}]})
        self._send(200, {"choices": [{"message": {"content": f"{who} talking."}}]})
srv = HTTPServer(("127.0.0.1", 0), Fake); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk", GROQ_API_KEY="qk", GEMINI_API_KEY="gk", GLASS_BUDGETS="Groceries:600,Dining:100",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="t")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.CHAT_MODE = "crew"  # these tests cover each agent answering (CHAT_MODE=crew); test_desk.py covers the front desk
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}
from wsgiref.util import setup_testing_defaults
def call(method, path, qs="", headers=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": qs, "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    for k, v in (headers or {}).items(): env["HTTP_" + k.upper().replace("-", "_")] = v
    setup_testing_defaults(env); got = {}
    out = b"".join(h.app(env, lambda s, hd: got.update(s=s, h=hd)))
    return int(got["s"][:3]), (json.loads(out) if out[:1] == b"{" else out), dict(got["h"])
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: sys.exit(1)
K = {"x-dashboard-key": "dk"}
print("mode:", mode)
for amt, cat in ((120, "Groceries"), (130, "Dining"), (15, "Fun")):
    h.add_expense(amt, cat, "x")
check("chart picking", h.pick_chart("chart my spending") == "spending" and h.pick_chart("daily spend graph") == "daily" and h.pick_chart("how busy is my week") == "calendar" and h.pick_chart("who wants pizza") is None)

caption, svg = h._chart_spending()
root = ET.fromstring(svg)
texts = [t.text for t in root.iter("{http://www.w3.org/2000/svg}text")]
check("spending chart is valid SVG with labels, values and budget ticks", "Groceries" in texts and "$120 of $600" in texts and "$130 of $100" in texts and len(list(root.iter("{http://www.w3.org/2000/svg}line"))) == 2)
fills = [r.get("fill") for r in root.iter("{http://www.w3.org/2000/svg}rect")]
check("over-budget bar drawn red", "#b3261e" in fills)
check("caption from real numbers", caption.startswith("Spending by category for ") and "Dining leads at $130.00" in caption and "over budget: Dining" in caption)
bars = [r for r in root.iter("{http://www.w3.org/2000/svg}rect") if r.get("fill") in ("#2f5bd3", "#b3261e")]; widths = dict(zip([x for x in texts if x in ("Groceries", "Dining", "Fun")], [float(r.get("width")) for r in bars]))
check("bars to scale (Groceries budget 600 is the max)", abs(widths["Dining"] / widths["Groceries"] - 130 / 120) < 0.01)
cap, svg = h._chart_daily(); ET.fromstring(svg)
check("daily chart valid, total right", "$265.00 so far" in cap)
cap, svg = h._chart_calendar(); ET.fromstring(svg)
check("calendar chart valid with no calendar", "nothing scheduled" in cap)
check("coverage chart before any round says so", h._chart_coverage()[0].startswith("No story"))
xss = h.bar_chart_svg("<script>alert(1)</script>", [("<b>&", 5)])
ET.fromstring(xss)
check("labels and titles escaped", "<script>" not in xss and "&lt;script&gt;" in xss)

s, d, _ = call("POST", "/api/chat", headers=K, body={"agent": "charter", "messages": [{"role": "user", "content": "chart my spending"}]})
check("1:1: Charter answers with a chart image and real caption, no model call", s == 200 and d["image"].startswith("/chart/") and d["reply"].startswith("Spending by category") and "last" not in STATE)
s, body, hd = call("GET", d["image"], headers={"cookie": "hub_key=dk"})
check("chart served as SVG to the logged-in viewer", s == 200 and hd["Content-Type"] == "image/svg+xml" and body.startswith(b"<svg"))
check("chart needs the key; unknown/odd ids 404", call("GET", d["image"])[0] == 401 and call("GET", "/chart/nope.svg", "key=dk")[0] == 404 and call("GET", "/chart/../x.svg", "key=dk")[0] == 404)
s, d, _ = call("POST", "/api/chat", headers=K, body={"agent": "charter", "messages": [{"role": "user", "content": "chart my workouts"}]})
check("can't chart it: model reply, told what it can chart", d["image"] is None and "can't chart anything else yet" in STATE["last"]["messages"][0]["content"])
s, d, _ = call("POST", "/api/allchat", headers=K, body={"text": "@charter show the daily spend"})
m = d["messages"][-1]
check("All Agents @charter posts the chart image", m["name"] == "Charter" and m["image"].startswith("/chart/") and m["text"].startswith("Daily spending"))
s, d, _ = call("POST", "/api/allchat", headers=K, body={"text": "who wants pizza tonight?"})
check("routed small talk doesn't trigger a chart", d["routed"] == ["Charter"] and "image" not in d["messages"][-1])
s, d, _ = call("POST", "/api/allchat", headers=K, body={"text": "can someone graph our activity"})
check("routed + 'graph' -> activity chart", "image" in d["messages"][-1] and "Messages per agent" in d["messages"][-1]["text"])
for i in range(h.CHART_KEEP + 3): h.save_chart("<svg/>")
check("only the newest charts kept", len(json.loads(h.store().get_meta("charts"))) == h.CHART_KEEP)
real_dt = h.datetime
class Sunday(real_dt):
    @classmethod
    def now(cls, tz=None): return real_dt.now(tz) + timedelta(days=(6 - real_dt.now(tz).weekday()) % 7)
h.datetime = Sunday
r1 = h.run_round(force=True)["ran"]["charter"]; r2 = h.run_round(force=True)["ran"]["charter"]
h.datetime = real_dt
check("Sunday round posts the spending chart once", r1["did"] == "posted the spending chart" and r2["did"] == "no chart due")
check("weekday round: nothing due", real_dt.now(h.hub_tz()).weekday() == 6 or h.run_round(force=True)["ran"]["charter"]["did"] == "no chart due")
