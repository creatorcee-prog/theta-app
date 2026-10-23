import os, sys
sys.dont_write_bytecode = True
os.environ.update(DASHBOARD_KEY="dk")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: sys.exit(1)
good = "sk-ant-api03-" + "A" * 95
os.environ["ANTHROPIC_API_KEY"] = good + "\n"
check("pasted line break flagged", "line break" in h.anthropic_key_hint())
os.environ["ANTHROPIC_API_KEY"] = f'"{good}"'
check("quotes flagged", "quotes" in h.anthropic_key_hint())
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-admin01-" + "A" * 90
check("admin key flagged", "Admin API key" in h.anthropic_key_hint())
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-usr01-" + "B" * 95
check("personal (sk-ant-usr) key accepted as a real key shape", "expired" in h.anthropic_key_hint() and "wrong value" not in h.anthropic_key_hint())
os.environ["ANTHROPIC_API_KEY"] = "my theta key"
check("non-key value flagged", "doesn't start with sk-ant-" in h.anthropic_key_hint())
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-api03-abc"
check("truncated key flagged", "cut off" in h.anthropic_key_hint())
os.environ["ANTHROPIC_API_KEY"] = good
check("good shape: expired, disabled or deleted", "expired or been disabled" in h.anthropic_key_hint())
check("hint never contains the key", good not in h.anthropic_key_hint() and "AAAA" not in h.anthropic_key_hint())
import types
anthropic = types.ModuleType("anthropic")
class AuthenticationError(Exception): pass
class APIStatusError(Exception):
    def __init__(self, message, status_code=400): super().__init__(message); self.message, self.status_code = message, status_code
class PermissionDeniedError(Exception): pass
anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.omit = AuthenticationError, PermissionDeniedError, None
anthropic.APIStatusError = APIStatusError
for n in ("RateLimitError", "APIConnectionError", "APITimeoutError", "BadRequestError", "NotFoundError", "InternalServerError", "APIError"):
    setattr(anthropic, n, type(n, (Exception,), {}))
seen = {}
class Fake:
    def __init__(self, api_key=None, default_headers=None, **kw): seen["key"], seen["hd"] = api_key, default_headers
    @property
    def beta(self): return self
    @property
    def messages(self): return self
    def create(self, **kw): raise seen.get("raise") or AuthenticationError("bad")
anthropic.Anthropic = Fake
sys.modules["anthropic"] = anthropic
os.environ["ANTHROPIC_API_KEY"] = " " + good + "\n"
try:
    h.claude_chat([{"role": "user", "content": "hi"}], 100); ok = False
except h.LLMError as e:
    ok = "line break" in str(e) and "platform.claude.com/settings/keys" in str(e)
check("client gets the cleaned key; error explains", seen["key"] == good and ok)
check("no workspace header unless set", seen["hd"] is None)
os.environ["ANTHROPIC_WORKSPACE_ID"] = " wrkspc_01ABC\n"
seen["raise"] = APIStatusError("This API key is not scoped to a workspace, so this request must include the anthropic-workspace-id header with the ID of the workspace to use.")
try:
    h.claude_chat([{"role": "user", "content": "hi"}], 100); msg = ""
except h.LLMError as e:
    msg = str(e)
check("workspace ID sent (cleaned) when set", seen["hd"] == {"anthropic-workspace-id": "wrkspc_01ABC"})
check("missing-workspace error explains ANTHROPIC_WORKSPACE_ID", "ANTHROPIC_WORKSPACE_ID" in msg and "scoped to a workspace" in msg)
print("ALL PASS")
