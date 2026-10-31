"""Obsidian vault via a private GitHub repo: Memory.md and each agent's note
are read into prompts (cached), self_note writes to Theta/Agents, remember
copies to Theta/Inbox, and GitHub trouble never costs a reply. A fake
GitHub contents API stands in; no live network."""
import sys, json, os, io, time, base64, threading
sys.dont_write_bytecode = True
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
FILES, LOG, STATE = {}, [], {"down": False, "conflict": 0}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _path(self):
        pre = "/repos/me/theta-vault/contents/"
        return unquote(self.path[len(pre):]) if self.path.startswith(pre) else None
    def do_GET(self):
        LOG.append(("GET", self._path()))
        if self.headers.get("Authorization") != "Bearer vt": return self._send(401, {})
        if STATE["down"]: return self._send(503, {})
        f = FILES.get(self._path())
        if not f: return self._send(404, {"message": "Not Found"})
        self._send(200, {"content": base64.b64encode(f["text"].encode()).decode(), "sha": f["sha"]})
    def do_PUT(self):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n))
        p = self._path(); LOG.append(("PUT", p))
        if STATE["conflict"]:
            STATE["conflict"] -= 1
            FILES[p] = {"text": FILES.get(p, {}).get("text", "") + "- added in Obsidian meanwhile\n", "sha": "s-obs"}
            return self._send(409, {"message": "sha mismatch"})
        if p in FILES and body.get("sha") != FILES[p]["sha"]: return self._send(409, {})
        sha = f"s{len(LOG)}"
        FILES[p] = {"text": base64.b64decode(body["content"]).decode(), "sha": sha}
        self._send(200, {"content": {"sha": sha}})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ.update(DASHBOARD_KEY="dk", OBSIDIAN_REPO="me/theta-vault", OBSIDIAN_TOKEN="vt",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h  # memory store in both modes: nothing here depends on Redis
from wsgiref.util import setup_testing_defaults
h.VAULT_API = f"http://127.0.0.1:{srv.server_address[1]}"
h.tmdb_trending = lambda: []
h._list_models = lambda p: {"models": ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "gemini-3.8-flash"]}


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


def clear_cache():
    for k in list(FILES) + ["Theta/Memory.md"] + [f"Theta/Agents/{a['name']}.md" for a in h.AGENTS.values()]:
        h.store().set_meta("vault:" + k.removeprefix("Theta/"), "null")


print("mode:", mode)
FILES["Theta/Memory.md"] = {"text": "- Home is Saint George, UT\n- Budget week starts Monday\n", "sha": "m1"}
FILES["Theta/Agents/Glass.md"] = {"text": "- Round totals to the dollar\n", "sha": "g1"}
clear_cache()
p = h.system_prompt("glass")
check("Memory.md is in every agent's prompt", "From the user's notes (their Obsidian vault, Memory.md" in p
      and "Budget week starts Monday" in p and "Budget week starts Monday" in h.system_prompt("remi"))
check("an agent's own vault note is in its prompt only", "Round totals to the dollar" in p
      and "Round totals to the dollar" not in h.system_prompt("remi"))
LOG.clear(); h.system_prompt("glass"); h.system_prompt("glass")
check("reads are cached (no GitHub call per message)", not LOG)
FILES["Theta/Memory.md"]["text"] += "- New fact\n"
check("...for VAULT_CACHE_SECONDS: an edit shows after the cache expires", "New fact" not in h.system_prompt("glass"))
h.store().set_meta("vault:Memory.md", json.dumps(dict(h._meta_json("vault:Memory.md", {}), at=time.time() - 400)))
check("...and then it does", "New fact" in h.system_prompt("glass"))
FILES["Theta/Memory.md"]["text"] = "x" * 5000
clear_cache()
check("a huge Memory.md is cut, with a note why", "keep Memory.md under 4000 characters" in h.system_prompt("glass"))
FILES["Theta/Memory.md"]["text"] = "- Home is Saint George, UT\n"

# ---- GitHub down: the reply still goes out, from the last copy
clear_cache(); h.system_prompt("glass")
STATE["down"] = True
h.store().set_meta("vault:Memory.md", json.dumps(dict(h._meta_json("vault:Memory.md", {}), at=0)))
check("GitHub down: the last copy is used", "Saint George" in h.system_prompt("glass"))
STATE["down"] = False

# ---- self_note writes to the vault
out = h.run_actions("remi", "ACTION: self_note | the user likes reminders 15 minutes early")
check("self_note goes to Theta/Agents/<Name>.md", "in your vault: Theta/Agents/Remi.md" in out
      and FILES["Theta/Agents/Remi.md"]["text"] == "- the user likes reminders 15 minutes early\n")
check("...not to the hub's own notes", not h.seat_notes("remi"))
check("...and Remi reads it back at once (cache updated by the write)", "15 minutes early" in h.system_prompt("remi"))
h.run_actions("remi", "ACTION: self_note | The user likes reminders 15 minutes early")
check("the same note isn't added twice", FILES["Theta/Agents/Remi.md"]["text"].count("15 minutes") == 1)
STATE["conflict"] = 1
h.run_actions("remi", "ACTION: self_note | no reminders after 10pm")
check("Obsidian synced at the same moment: re-read and kept both", "added in Obsidian meanwhile" in FILES["Theta/Agents/Remi.md"]["text"]
      and "no reminders after 10pm" in FILES["Theta/Agents/Remi.md"]["text"])
STATE["down"] = True
out = h.run_actions("lenz", "ACTION: self_note | user skips horror")
check("GitHub down: the note is kept in the hub instead, not lost", "Noted for myself: user skips horror" in out
      and h.seat_notes("lenz")[0]["text"] == "user skips horror")
STATE["down"] = False

# ---- remember copies to the Inbox
out = h.run_actions("glass", "ACTION: remember | Dentist is Dr. Lee")
inbox = [k for k in FILES if k.startswith("Theta/Inbox/")]
check("remember is copied to Theta/Inbox/<date>.md", "copied to your vault's Inbox" in out and len(inbox) == 1
      and "- Dentist is Dr. Lee (Glass," in FILES[inbox[0]]["text"])
check("...and still saved for the crew as before", any(m["text"] == "Dentist is Dr. Lee" for m in h.memory()))

# ---- Diagnostics, Settings, unlinked
row = next(r for r in h.wiring(fresh=True) if r["agent"] == "vault")
check("Diagnostics: the vault is readable, with counts", row["state"] == "ok" and "Memory.md:" in row["note"]
      and "agent note(s)" in row["note"] and "just now" in row["note"])
os.environ["OBSIDIAN_TOKEN"] = "bad"
row = next(r for r in h.wiring(fresh=True) if r["agent"] == "vault")
check("a bad token is named", row["state"] == "bad" and "OBSIDIAN_TOKEN" in row["note"])
os.environ["OBSIDIAN_TOKEN"] = "vt"
env = {"REQUEST_METHOD": "GET", "PATH_INFO": "/settings", "QUERY_STRING": "key=dk", "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO()}
setup_testing_defaults(env)
page = b"".join(h.app(env, lambda s, hd: None)).decode()
check("Settings says the vault is linked and what goes where", "Your Obsidian vault (me/theta-vault) is linked" in page)
h.OBSIDIAN_REPO = ""
check("unlinked: nothing from the vault, no calls", h.vault_prompt("glass") == "" and
      next(r for r in h.wiring() if r["agent"] == "vault")["state"] == "off")
print("ALL PASS")
