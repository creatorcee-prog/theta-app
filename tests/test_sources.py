"""Sources UI: stacked site favicons + "Sources" footer + bottom sheet for
web_search receipts. Client-side only: the bridge receipt format is
unchanged, and the footer parses it in the chat script. Unparseable
receipts keep rendering as plain text, exactly as before.
"""
import sys, os
sys.dont_write_bytecode = True
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
INDEX = open(os.path.join(ROOT, "api", "index.py")).read()
BRIDGE = open(os.path.join(ROOT, "api", "tool_bridge.py")).read()


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


# The receipt contract the footer parses (server side, unchanged).
check("bridge still emits the Web search results receipt",
      "Web search results:" in BRIDGE)
check("bridge still appends the Sources line", "Sources: " in BRIDGE)
check("bridge caps the receipt at 5 results", "results[:5]" in BRIDGE)

# Footer parser + sheet live in the chat script, built from DOM nodes.
check("footer parses the receipt", "function parseSources" in INDEX)
check("footer builds the stacked-favicon button", "function sourcesFoot" in INDEX)
check("footer opens the sheet", "function openSources" in INDEX)
check("sheet reuses the existing bottom-sheet dialog", 'dlg.className = "sheet src-dlg"' in INDEX)
check("sheet rows open in a new tab, no opener",
      'a.target = "_blank"; a.rel = "noopener"' in INDEX)
check("favicons come from the site itself, with a letter-tile fallback",
      '/favicon.ico' in INDEX and '"src-tile"' in INDEX)
check("footer is attached to agent messages in render",
      "sourcesFoot(m.text)" in INDEX)
check("receipt's own Sources line is hidden from display only",
      "srcSkip" in INDEX)

# Styles for the footer stack and the sheet rows.
for rule in (".src-foot{", ".src-stack", ".src-ic", ".src-dlg{", ".src-row{",
             ".src-snip{"):
    check("CSS has " + rule, rule in INDEX)

# No dates are invented: the sheet shows host + title + snippet only.
check("sheet shows no date line (results carry no date)",
      "src-row-title" in INDEX and "src-date" not in INDEX)

print("ALL PASS")
