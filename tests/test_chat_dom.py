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

        # Message rows: no avatar column, larger text, right-aligned own bubbles.
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.goto(f"{APP}/chat?key=dk")
        expect(pg.locator("#msgs")).to_contain_text("thread filler 25", timeout=15000)
        bub = pg.evaluate("""() => {
            const mine = document.querySelector('#msgs .msg.mine');
            const body = mine ? mine.querySelector('.mbody') : null;
            const msgs = document.querySelector('#msgs').getBoundingClientRect();
            const r = body ? body.getBoundingClientRect() : null;
            const cs = body ? getComputedStyle(body) : null;
            const agentMeta = document.querySelector('#msgs .msg:not(.mine) .meta');
            const meta = mine ? mine.querySelector('.meta') : null;
            return {noAvcol: !document.querySelector('#msgs .msg .avcol'),
                    agentNameGone: agentMeta ? (!agentMeta.querySelector('.name') && !agentMeta.querySelector('.via') && !!agentMeta.querySelector('time')) : false,
                    font: cs ? cs.fontSize : '', radius: cs ? cs.borderRadius : '',
                    rightGap: r ? Math.round(msgs.right - r.right) : -1,
                    metaHidden: meta ? getComputedStyle(meta).display === 'none' : true}; }""")
        check("no message avatar column", bub["noAvcol"])
        check("agent names are gone from meta (time stays)", bub["agentNameGone"])
        check("chat text renders at 17px", bub["font"] == "17px")
        check("own bubble is rounded and right-aligned", bub["radius"].startswith("20px") and 0 <= bub["rightGap"] <= 40)
        check("own messages hide their You/timestamp meta", bub["metaHidden"])
        pg.screenshot(path=os.path.join(SHOTS, "thread-390.png"))
        pg.close()

        # Glass style swap: Settings toggles the attribute and the real blur.
        pg = browser.new_page(viewport={"width": 1280, "height": 800})
        pg.goto(f"{APP}/settings?key=dk")
        expect(pg.locator('[data-pref="glassstyle"][data-val="liquid"]')).to_be_visible(timeout=15000)
        filters = lambda: pg.evaluate("""() => [...document.querySelectorAll('.glass')].map(e => getComputedStyle(e).backdropFilter)""")
        pg.locator('[data-pref="glassstyle"][data-val="liquid"]').click()
        expect(pg.locator("html")).to_have_attribute("data-glassstyle", "liquid", timeout=5000)
        check("liquid glass applies the stronger blur", any("32px" in (f or "") for f in filters()))
        card = pg.evaluate("""() => {
            const c = document.querySelector('.card');
            if (!c) return {};
            const s = getComputedStyle(c);
            return {blur: s.backdropFilter || '', mask: (s.webkitMaskBoxImage || s.maskBorderSource || '')}; }""")
        check("liquid glass reaches cards", "32px" in (card.get("blur") or ""))
        edge = pg.evaluate("""() => {
            const c = document.querySelector('.card');
            const before = c ? getComputedStyle(c).boxShadow : '';
            document.documentElement.style.setProperty('--shine-x', '1');
            const after = c ? getComputedStyle(c).boxShadow : '';
            document.documentElement.style.removeProperty('--shine-x');
            return {before, after}; }""")
        check("liquid edge light follows the tilt variable",
              edge["after"] != edge["before"] and "2px 1px" in edge["after"])
        check("liquid corners use the squircle mask", (card.get("mask") or "") not in ("", "none"))
        pg.screenshot(path=os.path.join(SHOTS, "glass-liquid.png"))
        pg.locator('[data-pref="glassstyle"][data-val="plus"]').click()
        expect(pg.locator("html")).to_have_attribute("data-glassstyle", "plus", timeout=5000)
        check("glass+ restores the standard blur", any("22px" in (f or "") for f in filters()))
        pg.screenshot(path=os.path.join(SHOTS, "glass-plus.png"))
        pg.close()

        # Backgrounds: Settings swaps the layer live; canvas modes paint.
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.goto(f"{APP}/settings?key=dk")
        expect(pg.locator('[data-pref="bg"][data-val="stars"]')).to_be_visible(timeout=15000)
        layer = lambda: pg.evaluate("""() => {
            const l = document.querySelector('#bg-layer');
            const c = l ? (l.querySelector('canvas[data-engine="webgl"]') || l.querySelector('canvas')) : null;
            return l ? {cls: l.className, w: c ? c.width : 0, h: c ? c.height : 0,
                        bg: getComputedStyle(l).backgroundImage, col: getComputedStyle(l).backgroundColor} : null; }""")
        pg.locator('[data-pref="bg"][data-val="stars"]').click()
        expect(pg.locator("html")).to_have_attribute("data-bg", "stars", timeout=5000)
        pg.wait_for_timeout(600)
        st = layer()
        check("stars background paints a canvas layer", st and st["cls"] == "bg-stars" and st["w"] > 0 and st["h"] > 0)
        check("active background clears the body background",
              pg.evaluate("() => getComputedStyle(document.body).backgroundColor") == "rgba(0, 0, 0, 0)")
        pg.goto(f"{APP}/chat?key=dk")
        expect(pg.locator("#msgs")).to_be_visible(timeout=15000)
        pg.wait_for_timeout(600)
        pg.screenshot(path=os.path.join(SHOTS, "bg-stars-390.png"))
        pg.goto(f"{APP}/settings?key=dk")
        expect(pg.locator('[data-pref="bg"][data-val="shards"]')).to_be_visible(timeout=15000)
        pg.locator('[data-pref="bg"][data-val="shards"]').click()
        expect(pg.locator("html")).to_have_attribute("data-bg", "shards", timeout=5000)
        pg.wait_for_timeout(1200)
        sh = layer()
        check("shards background paints a canvas layer", sh and sh["cls"] == "bg-shards" and sh["w"] > 0 and sh["h"] > 0)
        frag = pg.evaluate("""() => {
            const cv = document.querySelector('#bg-layer canvas[data-engine="webgl"]') || document.querySelector('#bg-layer canvas');
            const tmp = document.createElement('canvas'); tmp.width = cv.width; tmp.height = cv.height;
            tmp.getContext('2d').drawImage(cv, 0, 0);
            const d = tmp.getContext('2d').getImageData(0, 0, tmp.width, tmp.height).data;
            let vis = 0, glint = 0;
            for (let i = 0; i < d.length; i += 16) {
              if (d[i] > 60 || d[i + 1] > 60 || d[i + 2] > 60) vis++;
            }
            for (let i = 0; i < d.length; i += 4) {
              if (d[i] > 200 || d[i + 1] > 200 || d[i + 2] > 200) glint++;
            }
            return {vis: vis, glint: glint}; }""")
        check("shards draw visible glass fragments with glints", frag["vis"] > 50 and frag["glint"] > 3)
        check("shards engage real 3D glass when available", pg.evaluate('() => !!document.querySelector(\'#bg-layer canvas[data-engine="webgl"]\')'))
        check("with a background active, page surfaces turn translucent",
              pg.evaluate("() => { const s = document.querySelector('.sw'); return s ? getComputedStyle(s).backgroundColor : ''; }").endswith("/ 0.45)"))
        pg.goto(f"{APP}/chat?key=dk")
        expect(pg.locator("#msgs")).to_be_visible(timeout=15000)
        pg.wait_for_timeout(600)
        pg.screenshot(path=os.path.join(SHOTS, "bg-shards-390.png"))
        pg.goto(f"{APP}/settings?key=dk")
        expect(pg.locator('[data-pref="bg"][data-val="gemini"]')).to_be_visible(timeout=15000)
        pg.locator('[data-pref="bg"][data-val="gemini"]').click()
        expect(pg.locator("html")).to_have_attribute("data-bg", "gemini", timeout=5000)
        ge = layer()
        check("gemini background shows the aurora gradient", ge and ge["cls"] == "bg-gemini" and "radial-gradient" in pg.evaluate("() => getComputedStyle(document.querySelector('#bg-layer'), '::before').backgroundImage") and "radial-gradient" in pg.evaluate("() => getComputedStyle(document.querySelector('#bg-layer'), '::after').backgroundImage"))
        check("gemini animates without focus and keeps wall-clock phase",
              "geminiBlueEnv" in pg.evaluate("() => getComputedStyle(document.querySelector('#bg-layer'), '::before').animationName")
              and "geminiGoldEnv" in pg.evaluate("() => getComputedStyle(document.querySelector('#bg-layer'), '::after').animationName")
              and pg.evaluate("() => getComputedStyle(document.querySelector('#bg-layer'), '::before').animationDelay").startswith("-"))
        pg.goto(f"{APP}/chat?key=dk")
        expect(pg.locator("#msgs")).to_be_visible(timeout=15000)
        pg.wait_for_timeout(600)
        pg.screenshot(path=os.path.join(SHOTS, "bg-gemini-390.png"))
        pg.locator("#chat-msg").click()
        pg.wait_for_timeout(300)
        check("gemini keeps animating when the chat box is focused",
              "geminiBlueEnv" in pg.evaluate("() => getComputedStyle(document.querySelector('#bg-layer'), '::before').animationName")
              and "geminiGoldEnv" in pg.evaluate("() => getComputedStyle(document.querySelector('#bg-layer'), '::after').animationName"))
        pg.keyboard.type("hello aurora")
        pg.wait_for_timeout(400)
        check("gemini blooms while typing",
              "typing" in (pg.evaluate("() => document.querySelector('#bg-layer').className") or ""))
        pg.wait_for_timeout(2100)
        check("gemini settles after typing pauses",
              "typing" not in (pg.evaluate("() => document.querySelector('#bg-layer').className") or ""))
        pg.goto(f"{APP}/settings?key=dk")
        expect(pg.locator('[data-pref="bg"][data-val="black"]')).to_be_visible(timeout=15000)
        pg.locator('[data-pref="bg"][data-val="black"]').click()
        expect(pg.locator("html")).to_have_attribute("data-bg", "black", timeout=5000)
        bl = layer()
        check("black background is plain black", bl and bl["col"] == "rgb(0, 0, 0)")
        pg.goto(f"{APP}/chat?key=dk")
        expect(pg.locator("#msgs")).to_be_visible(timeout=15000)
        pg.wait_for_timeout(600)
        pg.screenshot(path=os.path.join(SHOTS, "bg-black-390.png"))
        pg.goto(f"{APP}/settings?key=dk")
        expect(pg.locator('[data-pref="bg"][data-val="theme"]')).to_be_visible(timeout=15000)
        pg.locator('[data-pref="bg"][data-val="theme"]').click()
        expect(pg.locator("html")).to_have_attribute("data-bg", "theme", timeout=5000)
        of = layer()
        check("theme background hides the layer", of and of["cls"] == "off")
        pg.close()


        # Long-thread readability: grouping, code cap, remaining avatar images.
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
        names_gone = pg.evaluate("""() => !document.querySelector('#msgs .msg:not(.mine) .meta .name')
            && !document.querySelector('#msgs .msg:not(.mine) .meta .via')
            && !!document.querySelector('#msgs .msg:not(.mine) .meta time')""")
        check("agent names are gone from the thread footer (time stays)", names_gone)

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

        # Attachments (Stage 3c): multi picker, preview strip, removal, send.
        import struct as _st, zlib as _zl, tempfile as _tf
        def _solid_png(w, h, rgb):
            def _chunk(typ, data):
                c = _st.pack(">I", len(data)) + typ + data
                return c + _st.pack(">I", _zl.crc32(typ + data) & 0xFFFFFFFF)
            raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
            return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", _st.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                    + _chunk(b"IDAT", _zl.compress(raw)) + _chunk(b"IEND", b""))
        _png = _solid_png(200, 120, (52, 120, 220))
        _pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
        _tmp = _tf.mkdtemp()
        _png_path = os.path.join(_tmp, "tiny.png"); _pdf_path = os.path.join(_tmp, "notes.pdf")
        open(_png_path, "wb").write(_png); open(_pdf_path, "wb").write(_pdf)
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.goto(f"{APP}/chat?key=dk")
        expect(pg.locator("#chat-msg")).to_be_visible(timeout=15000)
        pg.set_input_files("#chat-file", [_png_path, _pdf_path])
        pg.wait_for_selector("#chat-attach:not([hidden])", timeout=10000)
        check("attach strip shows image thumb + file chip",
              pg.locator("#chat-attach .attp").count() == 1 and pg.locator("#chat-attach .fchip").count() == 1)
        check("file chip names the file and its type",
              "notes.pdf" in (pg.locator("#chat-attach .fchip").first.inner_text() or "")
              and "PDF" in (pg.locator("#chat-attach .fchip").first.inner_text() or ""))
        pg.locator("#chat-attach").screenshot(path=os.path.join(SHOTS, "attach-strip-390.png"))
        pg.locator("#chat-attach .fchip .dx").first.click()
        check("removing a chip takes it out of the strip",
              pg.locator("#chat-attach .fchip").count() == 0 and pg.locator("#chat-attach .attp").count() == 1)
        msg = pg.locator("#chat-msg")
        msg.fill("photo for the crew")
        msg.press("Enter")
        expect(pg.locator("#msgs img.att")).to_be_visible(timeout=60000)
        check("sent image attachment renders in the thread",
              pg.locator("#msgs img.att").count() >= 1)
        check("removed file is not sent with the message",
              pg.locator("#msgs .fchip").count() == 0)
        check("strip clears after send", pg.locator("#chat-attach[hidden]").count() == 1)
        pg.close()

        # Rich messages (Stage 3d): tables, quotes, code copy, doc +
        # config cards, flow, bars, hostile output — all in Theta's
        # own tokens, rendered live.
        _rich = ("Comparison:\n| Model | Replies | Status |\n| :--- | ---: | :---: |\n"
                 "| Opus 5.5 | 128 | On |\n| gpt-oss-120b | 1042 | Off |\n\n"
                 "> A quoted note worth keeping.\n\n"
                 "```python\nprint(\"hello\")\n```\n\n"
                 "```doc\nRelease note\nShip the composer fix and keep the keyboard behavior.\n```\n\n"
                 "```config\nModel strategy\nselect Model strategy: Single primary model | Primary model + specialists\n"
                 "check Browser tests required: on\ncheck Approval required: off\n```\n\n"
                 "```flow\nRequest -> Renderer -> Thread\n```\n\n"
                 "```bars\nOpus: 128\ngpt-oss: 1042\n```\n\n"
                 "```quiz\nWhich view should load first?\n- Home\n- Chat\n```\n\n"
                 "```html\n<p>Hello</p>\n```\n\n"
                 "See https://example.com for details.\n")
        _hostile = "<script>alert(1)</script> and some javascript:evil text"
        _store = h.store()
        _store.add_chat("theta", _rich, channel="all")
        _store.add_chat("theta", _hostile, channel="all")
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.goto(f"{APP}/chat?key=dk")
        expect(pg.locator(".md-table")).to_be_visible(timeout=15000)
        expect(pg.locator(".doccard")).to_be_visible(timeout=15000)
        expect(pg.locator(".cfgcard")).to_be_visible(timeout=15000)
        tbl = pg.evaluate("""() => {
            const ths = [...document.querySelectorAll('.md-table th')];
            const cs = getComputedStyle(document.querySelector('.md-scroll'));
            return {scopes: ths.map(t => t.getAttribute('scope')),
                    aligns: ths.map(t => getComputedStyle(t).textAlign),
                    radius: cs.borderRadius}; }""")
        check("table headers carry scope=col", tbl["scopes"] == ["col", "col", "col"])
        check("table alignment honors the separator row",
              tbl["aligns"] == ["left", "right", "center"])
        check("table container is rounded", tbl["radius"] != "0px")
        check("rich message does not overflow the phone width", no_overflow(pg))
        richmsg = pg.locator("#msgs .msg", has=pg.locator(".md-table"))
        check("code block title is its language, with an icon copy button",
              richmsg.locator(".codeblock .chead .clabel").first.inner_text() == "Python"
              and richmsg.locator(".codeblock .chead button").first.get_attribute("aria-label") == "Copy code")
        check("code boxes have Edit, and HTML code boxes have Preview",
              richmsg.locator(".codeblock").nth(0).locator("button").filter(has_text="Edit").count() == 1
              and richmsg.locator(".codeblock").nth(0).locator("button").filter(has_text="Preview").count() == 0
              and richmsg.locator(".codeblock").nth(1).locator("button").filter(has_text="Preview").count() == 1)
        foot = pg.evaluate("""() => {
            const msg = document.querySelector('#msgs .msg:not(.mine)');
            const body = msg ? msg.querySelector('.mbody') : null;
            const kids = body ? [...body.children].map(c => c.className) : [];
            const acts = body ? [...body.querySelectorAll('.macts button')].map(b => b.getAttribute('aria-label')) : [];
            const lk = document.querySelector('#msgs a[href="https://example.com"]');
            const metaEl = body ? body.querySelector('.meta') : null;
            return {kids, acts,
                    metaName: metaEl ? !!metaEl.querySelector('.name') : false,
                    metaVia: metaEl ? !!metaEl.querySelector('.via') : false,
                    metaTime: metaEl ? !!metaEl.querySelector('time') : false,
                    linkBlank: lk ? (lk.target === '_blank' && (lk.rel || '').includes('noopener')) : false}; }""")
        kids = foot["kids"]
        check("message footer: answer, then actions, then meta",
              "text md" in kids and "mfoot" in kids and "meta" in kids
              and kids.index("text md") < kids.index("mfoot") < kids.index("meta")
              and foot["acts"] == ["Copy message", "Share message", "More actions"]
              and not foot["metaName"] and not foot["metaVia"] and foot["metaTime"])
        check("chat links open in the default browser (new tab)",
              foot["linkBlank"])
        quiz = pg.evaluate("""() => {
            const card = document.querySelector('.quizcard');
            if (!card) return {};
            const radios = card.querySelectorAll('input[type=radio]');
            const sub = [...card.querySelectorAll('button')].find(b => b.textContent === 'Submit');
            const before = sub ? sub.disabled : null;
            if (radios[0]) radios[0].click();
            const enabled = sub ? !sub.disabled : false;
            if (sub) sub.click();
            const disabled = sub ? sub.disabled : false;
            return {n: radios.length, before, enabled, disabled}; }""")
        check("quiz card renders radios with a Submit that enables on choice",
              quiz.get("n") == 2 and quiz.get("before") is True and quiz.get("enabled") is True)
        check("quiz submit disables the card while sending",
              quiz.get("disabled") is True)
        more = pg.evaluate("""() => {
            const msg = document.querySelector('#msgs .msg:not(.mine)');
            const btn = msg ? msg.querySelector('button[aria-label="More actions"]') : null;
            if (btn) btn.click();
            const menu = msg ? msg.querySelector('.mmenu') : null;
            return {open: menu ? !menu.hidden : false,
                    text: menu ? (menu.innerText || '') : ''}; }""")
        check("More opens a menu with Download as Markdown",
              more["open"] and "Download as Markdown" in more["text"])
        glassed = pg.evaluate("""() => {
            const sub = document.querySelector('.cfgcard button');
            const box = document.querySelector('.codeblock');
            const f = e => e ? (getComputedStyle(e).backdropFilter || '') : '';
            return {sub: f(sub), box: f(box)}; }""")
        check("card submit button is glass, not accent",
              "22px" in glassed["sub"])
        check("code box is glass, not dark",
              "22px" in glassed["box"])
        check("blockquote renders", pg.locator(".md-quote").count() >= 1)
        check("doc card has copy + edit",
              pg.locator(".doccard").count() >= 1
              and pg.locator(".doccard button").filter(has_text="Edit").count() == 1)
        check("config card has select, checkboxes, submit",
              pg.locator(".cfgcard select").count() == 1
              and pg.locator(".cfgcard input[type=checkbox]").count() == 2
              and pg.locator(".cfgcard button").filter(has_text="Submit").count() == 1)
        check("flow diagram and bars render",
              pg.locator(".fnode").count() >= 3
              and pg.locator(".bar-fill").count() == 2)
        check("hostile model output stays inert (no script element, text shown)",
              pg.locator("#msgs script").count() == 0
              and "alert(1)" in (pg.locator("#msgs").inner_text() or ""))
        foc = pg.evaluate("""() => {
            let found = false;
            for (const s of document.styleSheets) {
                try { for (const r of s.cssRules) if (r.cssText.includes(':focus-visible')) found = true; }
                catch (e) {}
            }
            const b = document.querySelector('.codeblock .chead button');
            return {rule: found, focusable: b ? b.tabIndex >= 0 : false}; }""")
        check("visible focus rule reaches the page and card buttons are focusable",
              foc["rule"] and foc["focusable"])
        # Table + quote + code live at the top of the rich message;
        # scroll them into view for a dedicated evidence shot.
        pg.locator(".md-table").first.scroll_into_view_if_needed()
        pg.wait_for_timeout(500)
        pg.locator("#msgs").screenshot(path=os.path.join(SHOTS, "rich-table-390.png"))
        # Edit flow: Edit opens a textarea, Cancel restores the card.
        pg.locator(".doccard button").filter(has_text="Edit").click()
        expect(pg.locator(".doccard textarea.field")).to_be_visible(timeout=10000)
        pg.locator(".doccard button").filter(has_text="Cancel").click()
        expect(pg.locator(".doccard button").filter(has_text="Edit")).to_be_visible(timeout=10000)
        check("doc edit cancels back to the card", True)
        # Submit state change: clicking Submit disables the card at
        # once (synchronous). No "Sent" assertion here on purpose:
        # the 6s message poll can re-render the thread mid-flight
        # and detach the card before the POST returns.
        pg.locator(".cfgcard button").filter(has_text="Submit").click()
        pg.wait_for_timeout(1000)
        check("config submit disables the card while sending",
              pg.locator(".cfgcard select:disabled").count() == 1
              and pg.locator(".cfgcard button:disabled").count() >= 1)
        pg.screenshot(path=os.path.join(SHOTS, "rich-390.png"))
        pg.close()
        pg = browser.new_page(viewport={"width": 1280, "height": 800})
        pg.goto(f"{APP}/chat?key=dk")
        expect(pg.locator(".md-table")).to_be_visible(timeout=15000)
        check("rich message does not overflow desktop width", no_overflow(pg))
        pg.screenshot(path=os.path.join(SHOTS, "rich-1280.png"))
        pg.close()
    finally:
        browser.close()

print("done" if not failures else f"FAILURES: {len(failures)}")
sys.exit(1 if failures else 0)
