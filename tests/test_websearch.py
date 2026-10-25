"""web_search: success, empty, failure, and unconfigured are distinct.

Regression tests for the "No results" investigation: the DuckDuckGo
fallback used to return a fake result titled "No results" both when the
Instant Answer lookup came back empty AND when the request itself failed,
so a provider failure read as an empty search. Keyed providers already
mapped transport failures to a Search error; this file pins that mapping
for every provider, plus malformed responses, timeouts, rate limits,
genuine empties, the keyless fallback, and page fetching. No live
network: HTTP is stubbed, so these run offline in both modes.
"""
import importlib.util
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from unittest import mock

sys.dont_write_bytecode = True
mode = sys.argv[1]
os.environ.update(DASHBOARD_KEY="dk", BOT_KEYS="lenz:lk", GEMINI_API_KEY="g", GROQ_API_KEY="q",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json",
                  RED_FEEDS="http://127.0.0.1:1/r", BLUE_FEEDS="http://127.0.0.1:1/b", GRAY_FEEDS="http://127.0.0.1:1/g")
if mode == "redis":
    os.environ.update(UPSTASH_REDIS_REST_URL="http://127.0.0.1:1/redis", UPSTASH_REDIS_REST_TOKEN="t")
_here = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tools = _load("ws_tools", os.path.join(_here, "..", "api", "tools.py"))
bridge = _load("ws_bridge", os.path.join(_here, "..", "api", "tool_bridge.py"))
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


def stub_urlopen(body=None, error=None):
    if error is not None:
        return mock.patch.object(urllib.request, "urlopen", side_effect=error)
    return mock.patch.object(urllib.request, "urlopen", return_value=Resp(body))


def set_provider(mod, provider, key):
    mod.SEARCH_PROVIDER = provider
    mod.SEARCH_API_KEY = key


def run_search(mod, query="python"):
    return mod.run_tool(None, {"name": "web_search", "args": {"query": query, "num_results": "5"}})


# --- DuckDuckGo fallback: success, genuine empty, failure are distinct ---
DDG_OK = json.dumps({
    "Heading": "Python", "AbstractText": "Python is a programming language.",
    "AbstractURL": "https://en.wikipedia.org/wiki/Python",
    "RelatedTopics": [{"Text": "NumPy - a library", "FirstURL": "https://numpy.org"}],
}).encode()
DDG_EMPTY = b'{"AbstractText": "", "RelatedTopics": []}'

set_provider(tools, "duckduckgo", "")
with stub_urlopen(body=DDG_OK):
    env = run_search(tools)
check("DDG success returns results with titles and urls",
      env["status"] == "ok" and len(env["data"]) == 2
      and env["data"][0]["title"] == "Python" and env["sources"][0].startswith("https://"))
with stub_urlopen(body=DDG_EMPTY):
    env = run_search(tools)
check("DDG genuine empty returns an empty list, not a fake result",
      env["status"] == "ok" and env["data"] == [] and env["sources"] == [])
with stub_urlopen(error=urllib.error.HTTPError("https://api.duckduckgo.com/", 500, "Server Error", {}, None)):
    env = run_search(tools)
check("DDG HTTP failure is an error, not No results",
      env["status"] == "error" and "500" in (env["error"] or ""))
with stub_urlopen(body=b"<html>not json</html>"):
    env = run_search(tools)
check("DDG malformed body is an error, not No results",
      env["status"] == "error")
with stub_urlopen(body=b'["not", "an", "object"]'):
    env = run_search(tools)
check("DDG non-object JSON is an error, not No results",
      env["status"] == "error" and "malformed" in (env["error"] or ""))

# --- Keyed providers: auth, rate limit, timeout, malformed, empty, success ---
SERPER_OK = json.dumps({"organic": [{"title": "Python", "link": "https://python.org",
                                     "snippet": "The Python language"}]}).encode()
TAVILY_OK = json.dumps({"results": [{"title": "Python", "url": "https://python.org",
                                     "content": "The Python language"}]}).encode()
for provider, ok_body, empty_body in (
        ("serper", SERPER_OK, b'{"organic": []}'),
        ("tavily", TAVILY_OK, b'{"results": []}')):
    set_provider(tools, provider, "dummy-test-key")
    with stub_urlopen(body=ok_body):
        env = run_search(tools)
    check("%s success returns results" % provider,
          env["status"] == "ok" and len(env["data"]) == 1 and env["data"][0]["url"] == "https://python.org")
    with stub_urlopen(body=empty_body):
        env = run_search(tools)
    check("%s genuine empty returns an empty list" % provider,
          env["status"] == "ok" and env["data"] == [])
    for code in (401, 429):
        err = urllib.error.HTTPError("https://x", code, "Error", {}, None)
        with stub_urlopen(error=err):
            env = run_search(tools)
        check("%s HTTP %d is an error" % (provider, code),
              env["status"] == "error" and str(code) in (env["error"] or ""))
    with stub_urlopen(error=urllib.error.URLError("timed out")):
        env = run_search(tools)
    check("%s timeout is an error" % provider, env["status"] == "error")
    with stub_urlopen(body=b'{"unexpected": true}'):
        env = run_search(tools)
    check("%s 200 without the results key is malformed, not empty" % provider,
          env["status"] == "error" and "malformed" in (env["error"] or ""))
    with stub_urlopen(body=b'{"organic": null, "results": null}'):
        env = run_search(tools)
    check("%s null results list is empty, not a crash" % provider,
          env["status"] == "ok" and env["data"] == [])

# --- Provider selection: a keyed provider without a key falls back to DDG ---
set_provider(tools, "serper", "")
with stub_urlopen(body=DDG_OK):
    env = run_search(tools)
check("serper without a key falls back to the DuckDuckGo path",
      env["status"] == "ok" and len(env["data"]) == 2)
set_provider(tools, "unknown-provider", "")
with stub_urlopen(body=DDG_OK):
    env = run_search(tools)
check("unknown provider name falls back to the DuckDuckGo path",
      env["status"] == "ok" and len(env["data"]) == 2)

# --- Empty query is an empty result, not an error ---
check("empty query returns an empty list",
      tools.tool_web_search("") == [])

# --- Bridge: receipts carry real results; empty is bare No results;
#     errors raise; a missing tool layer is reported as unavailable ---
set_provider(bridge.agent_tools, "duckduckgo", "")
with stub_urlopen(body=DDG_OK):
    receipt = bridge.tool_web_search("python", "mistral")
check("bridge receipt carries the actual results",
      receipt.startswith("Web search results:") and "Python" in receipt
      and "https://en.wikipedia.org/wiki/Python" in receipt)
with stub_urlopen(body=DDG_EMPTY):
    receipt = bridge.tool_web_search("python", "mistral")
check("bridge reports a genuine empty as bare No results", receipt == "No results")
set_provider(bridge.agent_tools, "serper", "dummy-test-key")
with stub_urlopen(error=urllib.error.HTTPError("https://x", 401, "Unauthorized", {}, None)):
    try:
        bridge.tool_web_search("python", "mistral")
        raised = None
    except ValueError as e:
        raised = str(e)
check("bridge raises the provider error instead of No results",
      raised is not None and "401" in raised)
_saved = bridge.agent_tools
bridge.agent_tools = None
try:
    bridge.tool_web_search("python", "mistral")
    raised = None
except ValueError as e:
    raised = str(e)
finally:
    bridge.agent_tools = _saved
check("bridge reports a missing tool layer as unavailable",
      raised is not None and "not available" in raised)

# --- Page fetch, separate from search (stubbed DNS + HTTP) ---
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
    # build_opener stub returns Resp; wrap its open to return FakeFetchResp
    orig_open = FakeOpener.open

    def _open(self, req, timeout=None):
        return FakeFetchResp(self._body)
    with mock.patch.object(FakeOpener, "open", _open):
        fetched = tools.tool_fetch_page("https://www.python.org")
check("fetch returns title and text for a public page",
      fetched["title"] == "Python.org" and "Welcome to Python" in fetched["text"]
      and fetched["url"] == "https://www.python.org/")
with mock.patch.object(socket, "getaddrinfo", fake_getaddrinfo_public), \
        mock.patch.object(urllib.request, "build_opener",
                          return_value=FakeOpener(error=urllib.error.URLError("timed out"))):
    env = tools.run_tool(None, {"name": "fetch_page", "args": {"url": "https://www.python.org"}})
check("fetch failure is an error, not empty content",
      env["status"] == "error" and "Fetch failed" in (env["error"] or ""))
with mock.patch.object(socket, "getaddrinfo", fake_getaddrinfo_private):
    env = tools.run_tool(None, {"name": "fetch_page", "args": {"url": "http://127.0.0.1/admin"}})
check("fetch to a non-public host is blocked (SSRF guard intact)",
      env["status"] == "error" and "not public" in (env["error"] or ""))

print("websearch: all checks passed")
