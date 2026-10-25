"""Browser tests for the chat page (Stage 0, Work item A).

Drives real Chromium (Playwright) against the real served app on localhost,
with the same fake-provider setup the in-process suite uses. The model's
words are canned by the fake; what is genuinely verified here is the DOM:
layout at widths, composer interaction, the submission guard, generating /
disabled / error / completed states, long-thread readability, avatar
rendering, and the agent tool-receipt path through the UI.

Run via tests/run_browser.sh (never via run_all.sh directly in CI: run_all
runs first, before Playwright is installed, so this file SKIPs there).
Usage: python tests/test_chat_dom.py [memory]  (redis mode SKIPs: the
browser matrix runs once, against the in-memory store).

check() records failures and continues instead of exiting on the first
one, so one run reports the whole matrix. Screenshots go to
tests/chat-dom-shots/ (review artifacts; not committed).

What this does NOT verify: physical-device behavior. A virtual keyboard
resizing the viewport, iOS Safari 100dvh / safe-area quirks, and real tap
feel cannot be emulated by Chromium and remain manual checks.
"""

import sys, os, io, json, threading, time
sys.dont_write_bytecode = True

mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
if mode == "redis":
    print("SKIP browser tests run in memory mode only")
    sys.exit(0)
try:
    from playwright.sync_api import sync_playwright, expect
except ImportError:
    if os.environ.get("BROWSER_STRICT") == "1":
        print("FAIL playwright not installed (pip install -r requirements-test.txt)")
        sys.exit(1)
    print("SKIP playwright not installed (pip install -r requirements-test.txt)")
    sys.exit(0)

from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

SLOW = [False]
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat-dom-shots")
os.makedirs(SHOTS, exist_ok=True)

failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


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

    def do_GET(self):
        # Provider model listings; anything else gets an empty listing.
        self._send(200, {"data": [{"id": "openai/gpt-oss-20b"}, {"id": "gemini-3.8-flash"}]})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else {}
        if SLOW[0]:
            time.sleep(4)
        msgs = body.get("messages", []) or []
        last = msgs[-1].get("content", "") if msgs else ""
        if "You route messages" in last:
            # Router call: name one agent, as the in-process fake does.
            return self._send(200, {"choices": [{"message": {"content": "mistral"}}]})
        user_text = " ".join(m.get("content", "") for m in msgs if m.get("role") == "user")
        if "remember my home is" in user_text:
            # The tool-use case: the agent's canned reply carries a real
            # ACTION line, executed by the real dispatcher, receipted
            # into the real thread. Only the model's words are canned.
            return self._send(200, {"choices": [{"message": {"content": "Got it.\nACTION: remember | Home: Testville"}}]})
        who = msgs[0]["content"].split(",")[0].replace("You are ", "") if msgs else "agent"
        self._send(200, {"choices": [{"message": {"content": f"{who} here."}}]})


srv = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"

os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="lenz:lk", GEMINI_API_KEY="dummy", GROQ_API_KEY="dummy",
                  GARAGE_GYM_URL=base + "/gym", GARAGE_GYM_SECRET="dummy",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
h.CHAT_MODE = "crew"  # agents answer directly, as in test_allchat.py
h.PROVIDERS = {"groq": (base + "/groq", "GROQ_API_KEY"), "gemini": (base + "/gemini", "GEMINI_API_KEY")}

# The app server must be threaded: the browser polls /api/chat/working
# every 1.5s while a slow /api/allchat POST is in flight.
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


app_srv = make_server("127.0.0.1", 0, h.app, server_class=ThreadingWSGIServer)
threading.Thread(target=app_srv.serve_forever, daemon=True).start()
APP = f"http://127.0.0.1:{app_srv.server_address[1]}"


def no_overflow(page):
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def seed_thread():
    store = h.store()
    store.add_chat("you", "hello from the browser test", channel="all")
    store.add_chat("theta", "Hi! I can help with your crew, calendar, and money.", channel="all")
    store.add_chat("theta", "Here is a list:\n- first item\n- second item", channel="all")
    store.add_chat("charter", "And a code block:\n```python\n" + "\n".join(f"line {i}" for i in range(40)) + "\n```", channel="all")
    for i in range(26):
        store.add_chat("you" if i % 2 == 0 else "theta", f"thread filler {i}", channel="all")


with sync_playwright() as p:
    browser = p.chromium.launch()
    try:
        # Empty state first, before seeding, at phone width.
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.goto(f"{APP}/chat?key=dk")
        expect(pg.locator("#chat-msg")).to_be_visible(timeout=15000)
        pg.screenshot(path=os.path.join(SHOTS, "empty-390.png"))
        check("empty state renders with composer", pg.locator("#chat-msg").is_visible()
              and pg.locator("#chat-send").is_visible())
        pg.close()

        seed_thread()

        # Layout matrix: widths, overflow, columns, pinned composer.
        for w, hgt, members_visible in ((390, 844, False), (768, 1024, False), (1280, 800, True), (1920, 1080, True)):
            pg = browser.new_page(viewport={"width": w, "height": hgt})
            pg.goto(f"{APP}/chat?key=dk")
            expect(pg.locator("#chat-msg")).to_be_visible(timeout=15000)
            expect(pg.locator("#msgs")).to_contain_text("hello from the browser test", timeout=15000)
            check(f"{w}px: no horizontal overflow", no_overflow(pg))
            box = pg.locator(".composer").bounding_box()
            check(f"{w}px: composer pinned and visible without scrolling",
                  box is not None and box["y"] + box["height"] <= hgt + 1)
            mem = pg.locator("#members")
            check(f"{w}px: members column {'visible' if members_visible else 'hidden'}",
                  mem.is_visible() == members_visible)
            if w == 390:
                pg.screenshot(path=os.path.join(SHOTS, "thread-390.png"))
            if w == 1280:
                pg.screenshot(path=os.path.join(SHOTS, "thread-1280.png"))
            pg.close()

        # Long-thread readability: grouping, code cap, avatar images.
        pg = browser.new_page(viewport={"width": 1280, "height": 800})
        pg.goto(f"{APP}/chat?key=dk")
        expect(pg.locator("#msgs")).to_contain_text("thread filler 25", timeout=15000)
        capped = pg.evaluate("""() => {
            const pre = document.querySelector('#msgs pre');
            return pre ? pre.scrollHeight > pre.clientHeight : false; }""")
        check("long code block is capped and scrollable", capped)
        imgs_ok = pg.evaluate("""() => [...document.querySelectorAll('img')]
            .filter(i => i.src.includes('/avatar/'))
            .every(i => i.complete && i.naturalWidth > 0)""")
        check("avatar images resolve", imgs_ok)
        names_ok = pg.evaluate("""() => document.querySelector('#msgs').innerText.includes('Theta')""")
        check("agent names render in the thread", names_ok)

        # Composer: multiline grow + Shift+Enter newline (no send).
        msg = pg.locator("#chat-msg")
        msg.fill("line one")
        msg.press("Shift+Enter")
        check("Shift+Enter inserts a newline without sending",
              "\n" in (msg.input_value() or ""))
        msg.fill("\n".join(f"grow line {i}" for i in range(25)))
        height = pg.evaluate("document.querySelector('#chat-msg').style.height")
        check("composer grows to its 168px cap", height == "168px")
        msg.fill("")

        # Submission guard: two rapid Enters must produce exactly one POST.
        posts = []
        pg.on("request", lambda r: posts.append(r.url) if r.method == "POST" and "/api/allchat" in r.url else None)
        msg.fill("guard probe message")
        msg.press("Enter")
        msg.press("Enter")
        expect(pg.locator("#msgs")).to_contain_text("guard probe message", timeout=30000)
        sent = [u for u in posts if "/api/allchat" in u]
        check("double Enter sends exactly once", len(sent) == 1)
        # The save round-trips: the message survives a reload.
        pg.reload()
        expect(pg.locator("#msgs")).to_contain_text("guard probe message", timeout=15000)
        check("sent message persists server-side after reload", True)

        # Generating + disabled + completed states, via a slow provider.
        SLOW[0] = True
        try:
            msg = pg.locator("#chat-msg")
            msg.fill("slow reply probe")
            msg.press("Enter")
            expect(pg.locator("#chat-working")).to_be_visible(timeout=15000)
            check("generating state shows the working indicator", True)
            check("send is disabled while a send is in flight",
                  pg.locator("#chat-send").is_disabled())
            expect(pg.locator("#msgs")).to_contain_text("slow reply probe", timeout=60000)
            expect(pg.locator("#chat-working")).to_be_hidden(timeout=30000)
            check("completed state clears the working indicator", True)
            check("send is enabled again after completion",
                  pg.locator("#chat-send").is_enabled())
        finally:
            SLOW[0] = False

        # Error state: aborting the POST must restore the text, not lose it.
        def abort_post(route):
            if route.request.method == "POST":
                route.abort()
            else:
                route.continue_()
        pg.route("**/api/allchat", abort_post)
        try:
            msg = pg.locator("#chat-msg")
            msg.fill("error probe message")
            pg.locator("#chat-send").click()
            expect(pg.locator("#chat-msg")).to_have_value("error probe message", timeout=15000)
            check("failed send restores the text into the composer", True)
            status_cls = pg.locator("#chat-status").get_attribute("class") or ""
            check("failed send marks the status as an error", "is-error" in status_cls)
        finally:
            pg.unroute("**/api/allchat")

        # Agent tool use through the UI, with a screenshot of the receipt.
        msg = pg.locator("#chat-msg")
        msg.fill("@mistral remember my home is Testville")
        msg.press("Enter")
        expect(pg.locator("#msgs")).to_contain_text("Remembered", timeout=60000)
        # Resize first: resizing reflows layout and can move the receipt
        # back below the fold, so scroll into view only after resizing.
        pg.set_viewport_size({"width": 390, "height": 844})
        receipt_visible = pg.evaluate("""() => {
            const el = [...document.querySelectorAll('#msgs .msg')]
                .find(m => m.innerText.includes('Remembered'));
            if (!el) return false;
            el.scrollIntoView({block: 'center'});
            const r = el.getBoundingClientRect();
            return r.top >= 0 && r.bottom <= window.innerHeight; }""")
        check("agent tool receipt renders in the thread", receipt_visible)
        raw_action = pg.evaluate("""() => {
            const el = [...document.querySelectorAll('#msgs .msg')]
                .find(m => m.innerText.includes('Remembered'));
            return el ? el.innerText.includes('ACTION:') : true; }""")
        check("receipt replaces the ACTION line (no raw ACTION shown)", not raw_action)
        pg.screenshot(path=os.path.join(SHOTS, "tool-receipt-390.png"))
        pg.close()
    finally:
        browser.close()

print("done" if not failures else f"FAILURES: {len(failures)}")
sys.exit(1 if failures else 0)
