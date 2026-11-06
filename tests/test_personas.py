"""Personas (2026-11-06): swappable sets of who Theta is. A name, what it calls you, a personality in place of
SOUL.md, and a look and sound kept for the phone (voice, voice effect, avatar, and optionally theme and frame).
Swapping changes the prompt the model gets, the name in the chat, and (on the phone) everything else."""
import sys, os, json
sys.dont_write_bytecode = True
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
os.environ.update(DASHBOARD_KEY="dk")
if mode == "memory":
    for k in ("KV_REST_API_URL", "REDIS_URL"):
        os.environ.pop(k, None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h

K = {"x-dashboard-key": "dk"}


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


def call(method, path, body=None, headers=K, query=None):
    s, _, out, *_ = h.handle(method, path, query or {}, headers, json.dumps(body or {}).encode())
    return s, json.loads(out)


check("personas need the key", call("GET", "/api/personas", headers={})[0] == 401)
s, d = call("GET", "/api/personas")
check("none at first: Theta is Theta", s == 200 and d["personas"] == [] and d["active"] == "" and h.persona_name() == "Theta"
      and "You're Theta" in h.soul_text())
s, d = call("POST", "/api/personas", {"name": "Simaris", "address": "Hunter", "soul": "Measured and curious; you collect knowledge.",
                                      "look": {"voice": "fish:abc", "fx": "hologram", "ui": "lattice.dark.grid.holo.theme.frame", "junk": "x"}})
pid = d["persona"]["id"]
check("save one: name, what it calls you, its personality, and its look (only known keys)", d["ok"] and d["persona"]["name"] == "Simaris"
      and d["persona"]["look"] == ["fx", "ui", "voice"])
check("a persona needs a name", call("POST", "/api/personas", {"name": "  "})[1]["error"] == "a persona needs a name")
s, d = call("POST", "/api/personas/activate", {"id": pid})
check("switching hands the phone its look", d["ok"] and d["look"]["voice"] == "fish:abc" and d["look"]["ui"].startswith("lattice"))
soul = h.soul_text()
check("...and the model becomes it: its name, what it calls you, its personality in place of SOUL.md",
      soul.startswith("# Simaris") and 'Call the user "Hunter"' in soul and "collect knowledge" in soul and "You're Theta" not in soul)
check("...every prompt that reads the soul speaks as it", "Your name is Simaris" in h.system_prompt("theta"))
check("...and the chat shows its name", h.persona_name() == "Simaris" and "persona_name()" in open(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "api", "_parts", "home.py")).read())
s, d = call("POST", "/api/personas", {"id": pid, "address": "Tenno"})
check("edit keeps the rest", d["persona"]["address"] == "Tenno" and d["persona"]["name"] == "Simaris" and "fx" in d["persona"]["look"])
check("an empty personality keeps Theta's own, under the persona's name", (call("POST", "/api/personas", {"name": "Plain"})[1]["ok"]
      and call("POST", "/api/personas/activate", {"id": [p for p in h.personas() if p["name"] == "Plain"][0]["id"]})[1]["ok"]
      and h.soul_text().startswith("# Plain") and "You're Theta" in h.soul_text()))
check("pictures too big to keep: everything else still saves", call("POST", "/api/personas", {"name": "Big", "look": {
    "voice": "v", "avimg": "x" * (h.PERSONA_LOOK_MAX + 10)}})[1]["persona"]["look"] == ["voice"])
call("POST", "/api/personas/activate", {"id": ""})
check("back to the original", h.persona_name() == "Theta" and "You're Theta" in h.soul_text())
call("POST", "/api/personas/delete", {"id": pid})
check("delete", not any(p["id"] == pid for p in h.personas()))
check("switching to an unknown one fails", not call("POST", "/api/personas/activate", {"id": "nope"})[1]["ok"])
page = h.handle("GET", "/settings", {}, K, b"")[2].decode()
check("Settings has the Personas card", 'id="personas"' in page and 'id="pa-soul"' in page and 'id="pa-ui"' in page)
head = h.handle("GET", "/head", {}, K, b"")[2].decode()
check("Theta's Voice and tools has a quick switch", head.count('id="pa-pick"') == 1)
check("back to Theta puts its own look back on the phone", '"theta:originalLook"' in h.PERSONA_JS)
# Gen 7 avatars from the Avatar Lab: styles in the app, and a persona can wear one
hj = h._HEAD_JS
check("the four Gen 7 styles are in the app's avatar styles", all(f'<option value="{x}">' in head for x in ("precision", "lumen", "flow", "signal"))
      and "GEN7[AV.style]) { drawGen7(" in hj)
check("...alive: own pace, a shape per state, color inside a state, and moments (got it, working, heads-up)",
      "q.kick" in hj and "SW.thinking" in hj and 'moment("working")' in hj and 'moment("alert", 4000)' in hj and 'moment("success", 2600)' in hj)
check("a persona can pick its own avatar", 'id="pa-av"' in page and '<option value="lumen">Lumen</option>' in page and "av.style = $(\"pa-av\").value" in h.PERSONA_JS)
print("done")
