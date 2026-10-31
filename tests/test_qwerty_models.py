"""QWERTY's model settings follow route(): he proposes ROUTE_DESK_MODEL /
ROUTE_LOW_BRAIN_MODEL, and Approve sets the provider + model pair (and the
matching legacy var) in one Vercel call. DESK_MODEL is only the desk's
on/off switch. No live network: Vercel's API and model lists are stubbed."""
import sys, json, os, io
sys.dont_write_bytecode = True
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
os.environ.update(DASHBOARD_KEY="dk", ANTHROPIC_API_KEY="ak", GROQ_API_KEY="qk", GEMINI_API_KEY="gk")
for k in ("ROUTE_DESK_PROVIDER", "ROUTE_DESK_MODEL", "ROUTE_LOW_BRAIN_PROVIDER", "ROUTE_LOW_BRAIN_MODEL"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h  # memory store in both modes: nothing here depends on Redis
h.notify = lambda *a, **k: 0


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


MODELS = {"gemini": ["gemini-3.8-flash", "gemini-3.9-pro"], "groq": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]}
h.list_models = lambda p: {"models": MODELS[p]}
SENT = []


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake_urlopen(req, timeout=None):
    SENT.append((req.full_url, json.loads(req.data)))
    return Resp(b"{}")


h.urllib.request.urlopen = fake_urlopen
h.VERCEL_TOKEN, h.VERCEL_PROJECT, h.VERCEL_DEPLOY_HOOK = "vt", "theta", ""


def propose(arg):
    out = h.run_actions("qwerty", f"ACTION: propose | {arg}")
    text = out["text"] if isinstance(out, dict) else out
    pid = out["buttons"][0]["id"].split(":")[1] if isinstance(out, dict) else None
    return text, pid


print("mode:", mode)
check("QWERTY can propose route()'s model settings", {"ROUTE_DESK_MODEL", "ROUTE_LOW_BRAIN_MODEL"} <= h.SETTABLE)
check("...and no longer the legacy LOW_BRAIN_MODEL", "LOW_BRAIN_MODEL" not in h.SETTABLE)
check("his prompt lists them", "ROUTE_DESK_MODEL" in h.qwerty_context())

text, pid = propose("ROUTE_DESK_MODEL = claude-sonnet-5-5")
p = h.proposals()[pid]
check("a desk model proposal sets the whole pair, plus DESK_MODEL to match",
      p["sets"] == {"ROUTE_DESK_PROVIDER": "anthropic", "ROUTE_DESK_MODEL": "claude-sonnet-5-5", "DESK_MODEL": "claude-sonnet-5-5"})
check("...and says so before you approve", "ROUTE_DESK_PROVIDER=anthropic" in text and "Nothing changes until you tap Approve" in text)
line = h.apply_proposal(pid, True)
check("Approve sets all three in ONE Vercel call (no half pair)", len(SENT) == 1 and isinstance(SENT[0][1], list)
      and {e["key"]: e["value"] for e in SENT[0][1]} == p["sets"] and "upsert=true" in SENT[0][0])
check("...and reports every name it set", line.startswith("✓ Set ROUTE_DESK_PROVIDER, ROUTE_DESK_MODEL, DESK_MODEL."))

text, _ = propose("ROUTE_DESK_MODEL = claude-made-up-9")
check("an unknown Claude model is refused (the cap couldn't price it)", "✗ propose" in text and "Claude model" in text)
text, _ = propose("ROUTE_DESK_MODEL = gemini-3.9-pro")
check("the desk model must be Claude (desk_chat calls Claude)", "✗ propose" in text)

SENT.clear()
text, pid = propose("ROUTE_LOW_BRAIN_MODEL = gemini-3.9-pro")
check("a Gemini low brain sets the pair and LOW_BRAIN_MODEL to match",
      h.proposals()[pid]["sets"] == {"ROUTE_LOW_BRAIN_PROVIDER": "gemini", "ROUTE_LOW_BRAIN_MODEL": "gemini-3.9-pro",
                                     "LOW_BRAIN_MODEL": "gemini-3.9-pro"})
text, pid = propose("ROUTE_LOW_BRAIN_MODEL = openai/gpt-oss-120b")
check("a Groq low brain sets only the pair (the legacy low brain is Gemini-only)",
      h.proposals()[pid]["sets"] == {"ROUTE_LOW_BRAIN_PROVIDER": "groq", "ROUTE_LOW_BRAIN_MODEL": "openai/gpt-oss-120b"})
text, _ = propose("ROUTE_LOW_BRAIN_MODEL = gemini-9-imaginary")
check("a model the key can't use is refused", "✗ propose" in text and "isn't a model your gemini key can use" in text)
text, _ = propose("LOW_BRAIN_MODEL = gemini-3.9-pro")
check("the legacy name is refused, pointing at the new one", "✗ propose" in text and "ROUTE_LOW_BRAIN_MODEL" in text)
text, _ = propose("ROUTE_DESK_MODEL += claude-sonnet-5-5")
check("+= makes no sense for a model", "✗ propose" in text and "not +=" in text)

text, pid = propose("DESK_MODEL = off")
check("DESK_MODEL still turns the desk off", pid and h.proposals()[pid]["value"] == "off" and "sets" not in h.proposals()[pid])
text, _ = propose("DESK_MODEL = claude-sonnet-5-5")
check("...but no longer picks the model", "✗ propose" in text and "ROUTE_DESK_MODEL" in text)
SENT.clear()
h.apply_proposal(pid, True)
check("a plain setting still goes as one object", len(SENT) == 1 and SENT[0][1]["key"] == "DESK_MODEL")

os.environ.update(ROUTE_DESK_PROVIDER="anthropic", ROUTE_DESK_MODEL="claude-sonnet-5-5")
check("Mistral's listed model follows route()", h.agent_model(h.DESK).startswith("claude-sonnet-5-5 (Anthropic)"))
print("ALL PASS")
