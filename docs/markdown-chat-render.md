# Safe markdown rendering for chat

## Problem
The current `richText` function in `api/index.py` only turns URLs into links and `@mentions` into styled spans. Agents (and you) can post tables, task lists, code blocks and images, but the chat UI shows them as plain text.

## Solution
Replace the `richText` function with a pure-DOM markdown subset that still **never** uses `innerHTML` (keeps the XSS safety you already have).

Supported:
- Tables (`| col | col |` + separator row)
- Task lists (`- [ ]` / `- [x]`)
- Fenced code blocks (```)
- `**bold**`, `*italic*`, `` `code` ``
- `![alt](url)` images
- Existing links and `@mentions`

Also adds a few CSS rules so tables and checkboxes look decent in both light and dark schemes.

## How to apply
1. Open `api/index.py`
2. Find the comment `// Text with links and @mentions, built from nodes (never innerHTML).`
3. Replace the entire `richText` function with the version below.
4. After the existing `.text{color:var(--text);font-size:15px;line-height:1.5}` CSS rule, add the extra styles below.
5. Deploy.

See the PR description for the full replacement code (it is also in the conversation with Grok).
