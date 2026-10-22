> **Status (applied):** applied in `api/index.py`; see `docs/markdown-chat-render.md` for what changed from this draft.

# Fix: Safe markdown rendering in chat (`richText`)

**Status:** The live `richText` in `api/index.py` still only handles links + @mentions.
That is why tables from Charter (and any checklist / code / image) still appear as plain text.

This document contains the **exact** replacement that must be applied.

---

## 1. Replace the entire `richText` function

Find this comment and the whole function that follows it:

```js
  // Text with links and @mentions, built from nodes (never innerHTML).
  function richText(text) { ... }
```

Replace it with the version in `docs/richtext-new.js` (or the block below).

The new function:
- Still builds everything from DOM nodes (no `innerHTML`)
- Adds tables, task lists (`- [ ]` / `- [x]`), fenced code, **bold**, *italic*, `code`, images
- Keeps existing link + @mention behaviour

## 2. Add the CSS

Right after the existing rule:

```css
.text{color:var(--text);font-size:15px;line-height:1.5}
```

add the rules in `docs/richtext-css.css`.

## 3. Deploy

After the change is in `api/index.py`, push / merge so Vercel redeploys.

---

## Why this was still broken

Previous PRs either:
- Only added documentation, or
- Failed to land the large `index.py` change cleanly.

This PR isolates the exact patch so QWERTY (or anyone) can apply it in one focused edit.

## Making agents more reliable (follow-up)

Once tables render, the next reliability wins are:

1. **Stop agents from stealing each other's work**  
   When the user @mentions multiple agents, each should only answer *their* part.

2. **Shorter default replies**  
   Persona / system prompt pressure toward concise answers unless the user asks for detail.

3. **Clearer tool use**  
   Once the tool scaffolding is wired, agents should prefer `TOOL: ...` when they need search or tasks instead of inventing answers.

I can open a follow-up PR for the routing + brevity rules as soon as this render fix is live.
