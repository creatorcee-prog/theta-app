"""Search backend: keyed providers are real, errors are typed, and the
zero-key fallback is labeled — never a silent downgrade.

Regression tests for the search-backend fix (the brief's Phase 5):
provider selection never silently falls back to DuckDuckGo when a
keyed provider is named but unconfigured; HTTP/auth/rate-limit/
timeout/malformed outcomes are distinct SearchError kinds, not empty
results; results are validated; the bridge receipt carries real
results and labels a DuckDuckGo empty honestly; the ACTION path
dispatches web_search to the user-visible receipt (single-pass by
design) and the SEARCH: path supplies results to the second model
turn. HTTP is stubbed (a delegating stub, so the fake store server
still works in redis mode); no live network, both modes.
"""
import importlib.util
import json
import os
import socket
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

sys.dont_write_bytecode = True
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
DB, H = {}, {}


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
        elif op == "HSET":
            d = H.setdefault(k, {})
            for i in range(0, len(a) - 1, 2):
                d[a[i]] = a[i + 1]
            r = 1
        elif op == "HMGET":
            r = [H.get(k, {}).get(f) for f in a]
        elif op == "HGET":
            r = H.get(k, {}).get(a[0])
        else:
            r = None
        self._send(200, {"result": r})


srv = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="mistral:mk", GEMINI_API_KEY="g", GROQ_API_KEY="q",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL=base + "/redis", UPSTASH_REDIS_REST_TOKEN="t")
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "api"))
import index as h


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tools = _load("sb_tools", os.path.join(_here, "..", "api", "tools.py"))
bridge = _load("sb_bridge", os.path.join(_here, "..", "api", "tool_bridge.py"))
bridge.HUB_STORE = lambda: object()


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


class Resp:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


_real_urlopen = urllib.request.urlopen
_provider_bodies = {}


def _delegating_urlopen(req, timeout=None):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    for host, body in _provider_bodies.items():
        if host in url:
            if isinstance(body, Exception):
                raise body
            return Resp(body)
    return _real_urlopen(req, timeout=timeout)


def set_provider(mod, provider, key):
    mod.SEARCH_PROVIDER = provider
    mod.SEARCH_API_KEY = key


def run_search(mod, query="python", num="5"):
    return mod.run_tool(None, {"name": "web_search", "args": {"query": query, "num_results": num}})


TAVILY_OK = json.dumps({"results": [
    {"title": "Python docs", "url": "https://docs.python.org/3/", "content": "The official docs."},
    {"title": "Python.org", "url": "https://www.python.org/", "content": "Welcome to Python."},
    {"title": "Real Python", "url": "https://realpython.com/", "content": "Tutorials."},
]}).encode()
SERPER_OK = json.dumps({"organic": [
    {"title": "Python docs", "link": "https://docs.python.org/3/", "snippet": "The official docs."},
    {"title": "Python.org", "link": "https://www.python.org/", "snippet": "Welcome to Python."},
]}).encode()

with mock.patch.object(urllib.request, "urlopen", _delegating_urlopen):
    # --- Keyed success: multiple real results, bounded count, schema ---
    set_provider(tools, "tavily", "dummy-test-key")
    _provider_bodies["api.tavily.com"] = TAVILY_OK
    env = run_search(tools)
    check("tavily success returns multiple results with titles, urls, snippets",
          env["status"] == "ok" and len(env["data"]) == 3
          and env["data"][0]["url"] == "https://docs.python.org/3/"
          and env["data"][0]["snippet"] == "The official docs."
          and env["sources"][0] == "https://docs.python.org/3/"
          and env["provider"] == "tavily")
    env = run_search(tools, num="2")
    check("tavily result count is bounded by num_results",
          env["status"] == "ok" and len(env["data"]) == 2)
    set_provider(tools, "serper", "dummy-test-key")
    _provider_bodies["google.serper.dev"] = SERPER_OK
    env = run_search(tools)
    check("serper success returns results with link mapped to url",
          env["status"] == "ok" and len(env["data"]) == 2
          and env["data"][1]["url"] == "https://www.python.org/"
          and env["provider"] == "serper")

    # --- Genuine zero results stay empty, not errors ---
    set_provider(tools, "tavily", "dummy-test-key")
    _provider_bodies["api.tavily.com"] = b'{"results": []}'
    env = run_search(tools)
    check("keyed genuine empty is ok with an empty list",
          env["status"] == "ok" and env["data"] == [] and env["sources"] == [])
    set_provider(tools, "duckduckgo", "")
    _provider_bodies["api.duckduckgo.com"] = b'{"AbstractText": "", "RelatedTopics": []}'
    env = run_search(tools)
    check("duckduckgo genuine empty is ok with an empty list",
          env["status"] == "ok" and env["data"] == [] and env["provider"] == "duckduckgo")

    # --- Missing credentials: no HTTP call at all ---
    for provider in ("tavily", "serper"):
        set_provider(tools, provider, "")
        _provider_bodies["api.tavily.com"] = Exception("must not call provider")
        _provider_bodies["google.serper.dev"] = Exception("must not call provider")
        env = run_search(tools)
        check("%s without a key errors without calling the provider" % provider,
              env["status"] == "error" and "not_configured" in (env["error"] or ""))
    set_provider(tools, "no-such-provider", "")
    env = run_search(tools)
    check("unknown provider name errors",
          env["status"] == "error" and "unknown_provider" in (env["error"] or ""))

    # --- Error kinds are distinct ---
    set_provider(tools, "serper", "dummy-test-key")
    for code, kind in ((401, "auth"), (403, "auth"), (429, "rate_limit"),
                       (500, "provider_error"), (503, "provider_error")):
        _provider_bodies["google.serper.dev"] = urllib.error.HTTPError(
            "https://google.serper.dev/search", code, "Error", {}, None)
        env = run_search(tools)
        check("serper HTTP %d maps to %s, not empty" % (code, kind),
              env["status"] == "error" and kind in (env["error"] or "")
              and str(code) in (env["error"] or ""))
    _provider_bodies["google.serper.dev"] = urllib.error.URLError("timed out")
    env = run_search(tools)
    check("serper timeout maps to timeout", env["status"] == "error" and "timeout" in (env["error"] or ""))
    _provider_bodies["google.serper.dev"] = TimeoutError("timed out")
    env = run_search(tools)
    check("serper TimeoutError maps to timeout", env["status"] == "error" and "timeout" in (env["error"] or ""))
    _provider_bodies["google.serper.dev"] = urllib.error.URLError("connection refused")
    env = run_search(tools)
    check("serper network failure maps to network, not empty",
          env["status"] == "error" and "network" in (env["error"] or ""))

    # --- Malformed bodies are errors, not empties ---
    set_provider(tools, "tavily", "dummy-test-key")
    for body, label in ((b"<html>not json</html>", "non-JSON body"),
                        (b'["not", "an", "object"]', "non-object JSON"),
                        (b'{"unexpected": true}', "missing results key"),
                        (b'{"results": {"a": 1}}', "results as an object"),
                        (b'{"results": "nope"}', "results as a string")):
        _provider_bodies["api.tavily.com"] = body
        env = run_search(tools)
        check("tavily %s is a malformed error" % label,
              env["status"] == "error" and "malformed" in (env["error"] or ""))

    # --- Missing optional fields: kept when usable, dropped when not ---
    set_provider(tools, "tavily", "dummy-test-key")
    _provider_bodies["api.tavily.com"] = json.dumps({"results": [
        {"title": "No snippet here", "url": "https://example.com/nosnip"},
        {"url": "https://example.com/notitle", "content": "Snippet but no title."},
        {"title": "", "content": ""},
        "not a dict",
        {"title": "Bad scheme", "url": "javascript:alert(1)", "content": "evil"},
        {"title": "Null list member", "url": None, "content": "Kept without a URL."},
    ]}).encode()
    env = run_search(tools)
    check("missing optional fields: usable kept, contentless/bad-scheme dropped",
          env["status"] == "ok" and len(env["data"]) == 3
          and env["data"][0]["snippet"] == ""
          and env["data"][1]["title"] == ""
          and env["data"][1]["snippet"] == "Snippet but no title."
          and env["data"][2]["url"] == "")

    # --- DuckDuckGo nested category topics are collected ---
    set_provider(tools, "duckduckgo", "")
    _provider_bodies["api.duckduckgo.com"] = json.dumps({
        "Heading": "", "AbstractText": "", "AbstractURL": "",
        "RelatedTopics": [{"Name": "Category", "Topics": [
            {"Text": "Nested result", "FirstURL": "https://example.com/nested"}]}],
    }).encode()
    env = run_search(tools)
    check("duckduckgo nested category topics are collected",
          env["status"] == "ok" and len(env["data"]) == 1
          and env["data"][0]["url"] == "https://example.com/nested")

    # --- Bridge: real results in the receipt; empty labeled by backend ---
    set_provider(bridge.agent_tools, "tavily", "dummy-test-key")
    _provider_bodies["api.tavily.com"] = TAVILY_OK
    receipt = bridge.tool_web_search("python docs", "mistral")
    check("bridge receipt carries real results and a Sources line",
          receipt.startswith("Web search results:") and "Python docs" in receipt
          and "https://docs.python.org/3/" in receipt and "Sources:" in receipt)
    set_provider(bridge.agent_tools, "duckduckgo", "")
    _provider_bodies["api.duckduckgo.com"] = b'{"AbstractText": "", "RelatedTopics": []}'
    receipt = bridge.tool_web_search("python docs", "mistral")
    check("bridge labels a duckduckgo empty with the Instant Answer limit",
          receipt.startswith("No results") and "Instant Answer" in receipt)
    set_provider(bridge.agent_tools, "serper", "dummy-test-key")
    _provider_bodies["google.serper.dev"] = b'{"organic": []}'
    receipt = bridge.tool_web_search("python docs", "mistral")
    check("bridge keyed empty stays bare No results", receipt == "No results")
    set_provider(bridge.agent_tools, "serper", "")
    try:
        bridge.tool_web_search("python docs", "mistral")
        raised = None
    except ValueError as e:
        raised = str(e)
    check("bridge raises not_configured instead of a silent fallback",
          raised is not None and "not_configured" in raised)

    # --- ACTION path: the model call is dispatched, receipt carries results ---
    h._tb.agent_tools.SEARCH_PROVIDER = "tavily"
    h._tb.agent_tools.SEARCH_API_KEY = "dummy-test-key"
    _provider_bodies["api.tavily.com"] = TAVILY_OK
    r = h.run_actions("mistral", "ACTION: web_search | python docs")
    check("ACTION web_search receipt carries the provider results",
          "✓" in str(r) and "Python docs" in str(r) and "https://docs.python.org/3/" in str(r))

# --- SEARCH: path: results are supplied to the second model turn ---
CAPTURED = []


def canned_second(msgs):
    CAPTURED.append(msgs)
    return "Answer from search [1]."


h.desk_chat = canned_second
h.llm_chat = lambda tier, msgs, **kw: canned_second(msgs)


def gemini_ok(prompt, timeout=30):
    return ("Gemini says: display glasses exist.",
            [(0, 10, "https://example.com/gemini", "Gemini Glass")], 1)


h.gemini_search = gemini_ok
CAPTURED.clear()
r = h.answer_with_search("mistral", "System prompt", "Find glasses", "prescription glasses display")
prompt_text = "\n".join(m.get("content", "") for m in CAPTURED[-1] if isinstance(m, dict))
check("SEARCH: second turn receives the search results",
      "Gemini says: display glasses exist." in prompt_text)
check("SEARCH: reply cites the real source and invents no other link",
      "https://example.com/gemini" in r and "example.com/other" not in r)

# --- fetch_page, separate from search (stubbed DNS + HTTP) ---
HTML = b"<html><head><title>Python.org</title></head><body><p>Welcome to Python.</p></body></html>"


class FakeOpener:
    def __init__(self, body=None, error=None):
        self._body = body
        self._error = error

    def open(self, req, timeout=None):
        if self._error is not None:
            raise self._error
        return Resp(self._body)


class FakeFetchResp(Resp):
    def geturl(self):
        return "https://www.python.org/"


def fake_getaddrinfo_public(host, *a, **k):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def fake_getaddrinfo_private(host, *a, **k):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]


with mock.patch.object(socket, "getaddrinfo", fake_getaddrinfo_public), \
        mock.patch.object(urllib.request, "build_opener",
                          return_value=FakeOpener(body=HTML)):
    def _open(self, req, timeout=None):
        return FakeFetchResp(self._body)
    with mock.patch.object(FakeOpener, "open", _open):
        fetched = tools.tool_fetch_page("https://www.python.org")
check("fetch returns title and text for a valid public URL",
      fetched["title"] == "Python.org" and "Welcome to Python" in fetched["text"])
with mock.patch.object(socket, "getaddrinfo", fake_getaddrinfo_private):
    env = tools.run_tool(None, {"name": "fetch_page", "args": {"url": "http://127.0.0.1/admin"}})
check("fetch rejects a private destination (SSRF guard intact)",
      env["status"] == "error" and "not public" in (env["error"] or ""))
env = tools.run_tool(None, {"name": "fetch_page", "args": {"url": "not-a-url"}})
check("fetch rejects a non-http URL",
      env["status"] == "error" and "Invalid URL" in (env["error"] or ""))

print("search-backend: all checks passed")
