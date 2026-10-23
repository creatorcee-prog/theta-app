import os, sys, json, time, types
sys.dont_write_bytecode = True
os.environ.update(DASHBOARD_KEY="dk", GROQ_API_KEY="", GEMINI_API_KEY="")
anthropic = types.ModuleType("anthropic")
class APIStatusError(Exception):
    def __init__(self, message, status_code=400): super().__init__(message); self.message, self.status_code = message, status_code
class AuthenticationError(APIStatusError): pass
class NotFoundError(APIStatusError): pass
class APIConnectionError(Exception): pass
for n, c in dict(APIStatusError=APIStatusError, AuthenticationError=AuthenticationError, NotFoundError=NotFoundError,
                 APIConnectionError=APIConnectionError).items(): setattr(anthropic, n, c)
CALLS, PLAN = [], {"raise": None}
class Models:
    def retrieve(self, mid):
        CALLS.append(mid)
        if PLAN["raise"]: raise PLAN["raise"]
        return {"id": mid}
class Client:
    def __init__(self, **kw): self.models = Models()
anthropic.Anthropic = Client
sys.modules["anthropic"] = anthropic
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
def check(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: sys.exit(1)
key1 = "sk-ant-usr01-" + "A" * 90
os.environ["ANTHROPIC_API_KEY"] = key1
PLAN["raise"] = AuthenticationError("invalid x-api-key", 401)
ok, d = h.claude_key_check()
check("rejected key: Anthropic's words plus the hint", ok is False and "it said: invalid x-api-key" in d and "expired" in d)
check("no key material saved", key1 not in json.dumps(h._meta_json("claude:check", {})))
n = len(CALLS); h.claude_key_check()
check("cached: no second lookup within 10 minutes", len(CALLS) == n)
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-usr01-" + "B" * 90
PLAN["raise"] = None
ok, d = h.claude_key_check()
check("a new key is checked at once and passes", ok is True and len(CALLS) == n + 1 and CALLS[-1] == h.MASTER_MODEL_ID)
# Wiring: stale saved error no longer shown when the live check passes
h.store().set_meta("claude:last_error", json.dumps({"at": time.time() - 3600, "error": "old: doesn't start with sk-ant-api"}))
row = {r["agent"]: r for r in h.wiring()}["theta"]
check("old saved error (from an older key or version) hidden once the key checks out", row["state"] == "ok" and "sk-ant-api" not in row["note"])
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-usr01-" + "C" * 90
PLAN["raise"] = AuthenticationError("invalid x-api-key", 401)
row = {r["agent"]: r for r in h.wiring()}["theta"]
check("live rejection shown in Wiring", row["state"] == "bad" and "isn't connected" in row["note"] and "checked just now" in row["note"])
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-usr01-" + "D" * 90
PLAN["raise"] = APIStatusError("This API key is not scoped to a workspace, so this request must include the anthropic-workspace-id header", 400)
ok, d = h.claude_key_check()
check("missing workspace explained", ok is False and "ANTHROPIC_WORKSPACE_ID" in d)
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-usr01-" + "E" * 90
PLAN["raise"] = APIConnectionError("down")
ok, d = h.claude_key_check()
check("unreachable: unknown, not cached", ok is None and h._meta_json("claude:check", {}).get("ok") is False)
e = AuthenticationError("Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error', 'message': 'invalid x-api-key'}}", 401)
check("raw SDK wrapping stripped (no body)", h._anthropic_said(e).startswith("{'type'") is True or "Error code" not in h._anthropic_said(e))
e.body = {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}
check("Anthropic's own message taken from the body", h._anthropic_said(e) == "invalid x-api-key")
print("ALL PASS")
