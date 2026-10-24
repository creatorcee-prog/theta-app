# To-do

## Stage 1c: Security/Health + Speed into Diagnostics (branch stage1c/diagnostics-security-speed, PR unmerged, base main 4f787089; independent of open PR #50)
- Diagnostics is now the canonical home for system health. The
  Settings Security and health section (id="security", QWERTY hero,
  security_rows()) and speed_card() (id="speed") move to Diagnostics
  by call site — no reimplementation, no new endpoints, no new
  metrics. Both panels are server-rendered: neither has JavaScript,
  event handlers, or its own endpoint, so there is nothing to
  rewire and no duplicate initialization to guard against (verified
  by inspection, asserted in tests).
- Layout: Crew's table is unchanged but its container goes
  full-width; Storage + Speed share a grid2 (Speed immediately right
  of Storage at >=1000px via the existing .grid2 media query,
  stacked below it on narrow screens; .grid2 > .card min-width:0
  from Stage 1a keeps long strings from blowing the cards out).
  Security and health is appended after Models & providers with its
  id="security" preserved, so direct links keep working.
- Settings cleanup: the Security section and the speed_card() call
  are removed; passkeys/Face ID, devices, Gmail, memory/notes,
  Siri, Rounds, Wiring, Bench, Standing orders, escalations,
  reports, and About are untouched. All five /settings#security
  pointers (two watchdog notifications, Home watchdog window href +
  "Open Security" link) now point at /diagnostics#security; the hub
  map no longer lists Security under Settings. Note: that hub-map
  line is also touched by PR #50 (different substring, Wiring) —
  if both merge, the owner takes both removals.
- Out of scope, unchanged: storage meter (Storage still shows only
  the mode label), release calendar (still Lenz page), agent rows,
  Glass+, chat title/top-bar, chat themes, attachments.
- Tests: tests/test_stage1c.py (both modes) covers panels present
  in Diagnostics / absent from Settings, preserved Settings
  sections, Speed placement + stacking rules at CSS/source level,
  the server-rendered nature (no security/speed JS anywhere),
  security_rows() error fallback, Speed "nothing measured yet"
  then real rows after a recorded load, no panel leakage without
  the dashboard key, and scope guards (no meter, no release move,
  no Glass+, Stage 1a intact; this branch is main + 1c only, so it
  does NOT assert 1b's wiring consolidation).
  No browser/DOM harness exists, so layout is verified at
  source/CSS level, not screenshots.

## Stage 1a: chat submission hardening + Diagnostics clipping (branch stage1a/chat-submit-diagnostics, PR unmerged)
- Main composer (_CHAT_JS): explicit `sending` in-flight guard in
  form.onsubmit (set synchronously after the empty check, released
  in a finally). Button clicks and keyboard Enter both funnel
  through onsubmit, so one guard covers rapid taps, repeated Enter,
  and overlapping handlers; Shift+Enter newline, mobile multiline,
  image attach, optimistic display, rid, working poll, and failure
  restore are untouched.
- Mini bar (_UI_JS_SRC, runs on every page): Send now POSTs to
  /api/allchat with {text, channel: "all", rid} and its own guard +
  finally release; success clears the input and shows "Sent — see
  it in Chat" (or the command result for "/" input); failure
  restores the text and shows the error. The pending rid is set so
  chat can resume the working indicator, and cleared on failure.
  Without JS the form still GETs to /chat with ?say= as a draft.
  Suggestion chips are unchanged (drafts, not sends).
- Diagnostics clipping (_BASE_CSS only, no global layout change):
  `.grid2 > .card{min-width:0}` (grid blowout: .card had no
  min-width), `.tbl td` and `.card li` get
  `overflow-wrap:break-word` for long identifiers/URLs; tables
  stay in their existing .scrollx scrollers. Pre-existing nit
  found, not fixed here (belongs to 1b consolidation): the
  Diagnostics link to /settings#wiring is a dead anchor — the
  Settings wiring section has no id="wiring" (its table is
  #wiring-rows).
- Tests: tests/test_stage1a.py (26 checks, both modes) covers the
  shipped /chat.js guard, /ui.js mini bar handler, home markup,
  the real /api/allchat payload path, served CSS rules,
  diagnostics table/scroller structure, and scope guards proving
  wiring consolidation, Security/Speed moves, and the release
  calendar move are NOT in this PR. No browser/DOM harness exists,
  so click/tap behavior is verified by shipped-source + WSGI
  checks, not by driving a browser — stated in the PR, not claimed.

## Bridge hub reference (fix/bridge-hub-ref, PR unmerged)
- Fragility: tool_bridge.py's _store() did a plain `import index`,
  which only works if the hub module happens to be importable under
  that name. Under Vercel's file-path loading it may not be (tools
  fail) or it may load a SECOND copy of the hub with its own store
  (a task created through the bridge lands in a different store
  than the hub reads). The nopath test did not catch this because it
  registers the loaded module as "index" in sys.modules.
- Fix: index.py's loader hands the bridge its own store()
  (_tb.HUB_STORE = _bridge_store; the lookup is deferred to call
  time, after store() is defined, so no circular import and no
  second copy). _store() now prefers HUB_STORE, then an
  already-imported "index" in sys.modules (same object, never a
  fresh import), then a plain import as a last resort for standalone
  bridge use (first copy, not a second one).
- Regression test tests/test_bridge_hubref.py: clean subprocess
  loads index.py by path under a non-"index" name, api/ scrubbed
  from sys.path, "index" never in sys.modules; requires the injected
  reference to be the hub's own function returning the hub's own
  store, no "index" module appearing before or after tool runs, a
  real task_create + task_list through run_actions, and tools_diag
  healthy. Negative control with the old bridge fails the same
  setup. Memory store in the child (loading, not storage, is under
  test), so identical in both run_all.sh modes.
- Base note: this branch is current main, which now includes PR #47
  (merged fb43b5a1); the battery below therefore also runs
  test_internal_error.

## Internal-error diagnosis (fix/internal-error-diag, PR unmerged)
- Symptom, on deployed main 923011e1 (PR #46 merged): a task_create
  request failed with "internal error". Evidence first: that literal
  string comes from exactly one place, app()'s top-level catch, so an
  exception escaped handle(). The tool path itself is envelope-safe
  (bridge -> ValueError -> receipt; malformed ACTION lines match
  nothing; provider errors -> LLMError -> errors dict), so the failure
  must be an exception outside the narrow (LLMError, ValueError,
  KeyError) tuples: a store RuntimeError/TimeoutError/URLError at an
  unguarded point, or a non-ValueError tool exception. working(),
  working_final(), activity(), crew_facts() and reply_extra() were
  checked and are safe (they catch internally or are pure).
- Demonstrated pre-fix, both modes: dispatcher RuntimeError -> 500
  "internal error"; reply-save failure -> 500 "internal error" even
  though the task was already in the ledger.
- Fix: _diag() helper (request id from the frontend rid or a fresh
  per-request id; only stage names, tool names, counts, durations,
  exception classes and truncated messages — never prompts, user text,
  keys or headers); stage lines for allchat start/replies, model calls
  (provider, model, elapsed, outcome, HTTP status where available),
  tools parsed/done/skipped/applied (results go to the user-visible
  reply, not back to the model: single pass by design), and
  persist/view failures; app() catch logs stage= request.failed with
  the exception class. run_actions catches Exception per action ->
  receipt; desk_replies catches Exception per agent -> errors dict;
  the desk save loop returns a specific 502 naming that the tools may
  already have run; the view step has its own 502. Deadline and tool
  architecture preserved.
- Regression test tests/test_internal_error.py: all six mocked
  scenarios (valid, malformed, dispatcher raises, provider error,
  persistence fails, tool call + final response). Scenarios 3 and 5
  FAIL on pre-fix code (500 "internal error") and PASS with the fix.
- Incidental: test_desk.py asserted the OLD timeout copy ("went
  through, but the reply took too long"), which the merged retry
  warning in PR #46 had already replaced; the assertion now pins the
  current copy. That failure predated this change (the old substring
  is absent from deployed main).
- Known residuals, same class, deliberately not changed here: the crew
  path's save loop and /api/chat's proposal save are still unguarded;
  tools.py task_create falls back to process memory when a Redis write
  fails (a task "created" that way is lost on the next cold start).

## Retry-warning follow-on on fix/reply-deadline (same PR #46, still unmerged)
- The chat error messages told the user to resend without warning that
  a retry re-runs the whole chain: anything the lost reply already did
  (a task created before a kill) would happen twice. Both messages now
  say so plainly: the server-error message says to check what already
  happened before sending again; the dropped-connection message no
  longer promises the reply will show up, and says not to resend it if
  it does show up, and to check first if it does not.

## Reply deadline (fix/reply-deadline, PR unmerged)
- Stall investigated after the Phase 4 tool test: Mistral offered to
  begin the test, then the chat showed "your message went through, but
  the reply took too long to load". Root cause is NOT the tools and NOT
  a missing heartbeat: the tools are fast (task_create/task_list 0.00s,
  web_search 1.42s, combined 3-action reply 0.65s, desk_reply 0.69s with
  a stubbed model) and bounded (8-15s), while the desk path's model
  chain is unbounded (Claude 40s + SDK retry, then Gemini/Groq
  fallbacks, then Theta takeover / SEARCH second call, and sequential
  replies for each @mentioned agent). Past Vercel's 60s maxDuration the
  function is killed, the reply is never saved, and the frontend — which
  has no fetch timeout of its own — shows the timeout message when the
  connection drops. The 1.5s working poll is progress reporting, not the
  cause, and it stops when the fetch dies; the 6s message poll can only
  deliver replies that were actually saved. A 62s model delay completes
  locally (no internal cap), proving the kill mechanism.
- Fix: app() sets _REQ.deadline (50s default) for /api/allchat and
  /api/chat; _llm_call and claude_request cap their timeouts by the
  time left (Claude gets no SDK retry under a deadline); run_actions
  skips tools with less than 16s left and says so. A reply that runs
  out of budget now returns an honest error ("couldn't reply") instead
  of a lost reply. The chat catch also tells a fast server error apart
  from a dropped connection.
- Regression test tests/test_reply_deadline.py: a fake provider that
  sleeps 30s, a 6s deadline, llm_chat fails in ~6s with a deadline
  error (not 25s x chain), and app() wires the deadline for /api/allchat.
- If replies ever legitimately need minutes (long Claude thinking),
  the durable route is a job-status endpoint + the existing cron
  rounds as executor; a heartbeat alone cannot fix a killed function.

## Follow-on fix on fix/mistral-tools-prompt (same PR #45, still unmerged)
- Follow-on gap, caught before merge: tool_bridge.py still did a plain
  `import tools` off sys.path, so the tools could register yet fail at
  execution ("tool layer not available") in the same deployment case.
- Fix: tool_bridge.py now loads tools.py by path next to itself
  (importlib), mirroring the index.py bridge load. tools.py is
  stdlib-only, so there is no deeper local chain.
- The loader now also verifies the tools module itself loaded: an old
  bridge without TOOLS_LAYER_ERROR can no longer report "ok" by
  default, and a failed bridge import marks the layer failed too.
- /diagnostics Tools card gains a "Tool layer (tools.py)" line fed by
  tools_diag()["tools_layer"].
- Regression test: tests/test_bridge_nopath.py spawns a clean
  subprocess with api/ scrubbed from sys.path, loads index.py by file
  path, and requires an ACTUAL task_create + task_list execution with
  receipts (not just registration). Negative control verified: with
  the old tool_bridge it fails with tools_layer "tools module did
  not load". Passes in both run_all.sh modes.
- Vercel preview note: PR #43, #44 and #45 heads all report Vercel
  status "Canceled by Ignored Build Step" (success state). The ignore
  is NOT in vercel.json or the repo; it is a dashboard Project
  Settings -> Git -> Ignored Build Step on project dashboard-app that
  skips preview builds broadly (code changes were still ignored).
  Production deploys from main still work. GitHub Actions
  (.github/workflows/tests.yml) still runs the full suite on every
  PR, so automated test validation happens; only a clickable preview
  URL is unavailable unless the dashboard setting is narrowed.

## Fixed on fix/mistral-tools-prompt (PR pending, not merged)
- Root cause of "Mistral only reports the original tools": the Phase 4
  bridge import relied on sys.path, and its `except ImportError:
  BRIDGE_TOOLS = {}` fallback silently dropped all six tools while the
  original tools kept working. Reproduced locally by importing the app
  without tool_bridge.py: Mistral's prompt kept the originals, lost all
  six, and run_actions rejected them as "not a tool I have".
- Fix: tool_bridge.py is now loaded by path next to api/index.py
  (importlib, not sys.path), and any failure is recorded in
  BRIDGE_IMPORT_ERROR instead of being swallowed.
- /diagnostics gains a server-rendered Tools card (key-gated, no secrets
  or conversations): deployed commit (VERCEL_GIT_COMMIT_SHA), bridge
  file present/missing, import state, registered bridge tools, and
  per-tool inclusion in Mistral's prompt. If the card still shows a
  missing bridge or an old commit after a redeploy, the cause is the
  deployment/packaging, not the prompt.
- Regression test: tests/test_mistral_tools.py (25 checks memory,
  23 redis) proves tools_prompt("mistral"), desk_system("mistral"),
  run_actions execution, and the diagnostics card all include the six
  tools. No approval gates removed, no security protections loosened.

## Shipped on redesign/mobile-nav-diagnostics (PR pending, not merged)
- [x] Bottom bar with three primary destinations (Home, Diagnostics,
      Settings); Chat, Calendar and Money keep their routes, reached from
      the sidebar Sections list, Home quick actions and the chat bar.
- [x] Persistent chat bar above the bottom bar on every main section
      except Chat itself; a typed draft or a section suggestion travels as
      `?say=` into the real composer, nothing is sent from the bar.
- [x] Home: a Needs-attention section (over/near-budget categories, today's
      events, failed rounds) shown only when there is something to flag,
      plus quick actions to Chat, Calendar, Money and Diagnostics.
- [x] Diagnostics page (`/diagnostics`): crew status, storage mode,
      scheduled work (round jobs, 5-minute tick), recent failures and
      errors, Claude monthly spend, and the live wiring check. Gemini/Groq
      per-model token totals are labeled "not tracked yet", not healthy.
- [x] Money: a spending donut of actual spending by category, reconciling
      with the month's total; budgets stay limits, never spending.
- [x] Working indicator: notes keep their first-seen time and a final
      state; the chat shows elapsed time, a stale note ("still working"),
      and completed / failed / waiting-for-approval states, and resumes
      after a refresh. Unknown request ids still return exactly `{"ok": true}`.
- [x] `api/tools.py`: page fetch refuses private/loopback/link-local/
      reserved/multicast hosts and redirects to them (SSRF guard); tool
      results use `{status, data, sources, error, duration_ms}`; the task
      ledger records agent, status, steps, results, sources, blockers and
      approvals. Covered by `tests/test_toolbox.py`.
- [x] Wired `api/tools.py` into `api/index.py` via the existing ACTION
      bridge (Phase 4, branch `feature/phase4-tool-layer`): agents can use
      `web_search`, `fetch_page` (SSRF-guarded), and the task ledger
      (`task_create` / `task_list` / `task_complete` / `task_note`) in chat.
      Results come back as ✓/✗ receipts. Covered by `tests/test_tool_bridge.py`
      and the existing `tests/test_toolbox.py`. Consequential actions
      (settings, purchases, messages) still go through the existing approval
      gate; these new tools are read-only or internal ledger only.
- [ ] Still to do: a browser worker for operating websites. It needs an
      always-on host, not Vercel serverless, and must stay read-only
      without approval for consequential actions. Nothing here claims
      agents can operate arbitrary websites yet.
- [ ] Still to do (Phase 4 follow-ups): richer task UI on Diagnostics/Home,
      optional multi-round tool loop (currently one ACTION batch per reply,
      same as before), and any write tools behind the same Approve flow.

## Setup checklist

**Settings → Wiring** shows which of these are working. All keys go in
Vercel → Settings → Environment Variables, marked **Sensitive**, then
**Redeploy** (new values only reach new deployments).

### 1. Merge and redeploy
- [ ] Merge the open pull request, then wait for (or trigger) the Vercel
      production deploy.

### 1b. Devices (after this deploy)
- [ ] Open Theta on each of your devices once, then check Settings →
      **Devices**: every one should be yours. Sign out anything that isn't.
- [ ] Then change `DASHBOARD_KEY` in Vercel (a new long random string) and
      redeploy. That cuts off anything still on the old sign-in. Sign back
      in with Face ID, or a link with the new key.
- [ ] Face ID still failing? Settings → Devices → Recent Face ID failures
      shows the reason; a passkey made on another address needs adding again.

### 1c. Let QWERTY apply approved changes (optional)
- [ ] Vercel → Account Settings → Tokens → create a token → `VERCEL_TOKEN`
      (Sensitive). It can change any of your Vercel projects, so treat it
      like a password; QWERTY only uses it for approved, non-secret settings.
- [ ] `VERCEL_PROJECT`: the project's name (or ID) from its Settings page.
      `VERCEL_TEAM_ID` too if the project belongs to a team.
- [ ] Project → Settings → Git → Deploy Hooks → create one for `main` →
      `VERCEL_DEPLOY_HOOK` (Sensitive) so approved changes redeploy on their own.
- [ ] Redeploy, then ask: "@QWERTY add https://www.youtube.com/@veritasium to my YouTube channels".

### 2. Schedules (Supabase SQL editor; any Supabase project)
- [ ] `CRON_SECRET` in Vercel (any long random string), redeploy.
- [ ] Run `supabase/cron.sql.example` with your hub address and secret
      filled in. It creates `bot-hub-rounds` (agent rounds, 3 a day) and
      `bot-hub-tick` (every 5 minutes: reminders and the morning digest).
      Wiring → **Rounds** and **Reminders and digest** turn green once
      they've run.

### 3. Sign-in
- [ ] Settings → **Sign in with Face ID** → Add this device.
- [ ] Remove the Home Screen icon and add it again from a link without
      `?key=`.

### 4. Gmail for Remi (on a computer, ~10 minutes)
- [ ] console.cloud.google.com → create a project (e.g. "Theta").
- [ ] APIs & Services → Library → **Gmail API** → Enable.
- [ ] Google Auth Platform → Branding: app name Theta, your email. Audience:
      **External**, then **Publish app** (In production). Testing mode
      signs Remi out every 7 days. Google will show "unverified app" when
      you connect; that's expected for your own app: Advanced → Go to Theta.
- [ ] Clients → Create client → **Web application**. Authorized redirect
      URI: the address shown in Settings → Gmail
      (`https://<your-hub>/api/gmail/callback`).
- [ ] Vercel: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`; redeploy.
- [ ] Settings → Gmail → **Connect Gmail**. Optional:
      `GMAIL_IMPORTANT` (default `family,friends,work`),
      `GMAIL_ARCHIVE=newsletters`.

### 5. Glass's stocks
- [ ] Free key at finnhub.io → `FINNHUB_API_KEY`.
- [ ] `GLASS_HOLDINGS` (`AAPL:10,VTI:25`) and/or `GLASS_WATCHLIST`
      (`NVDA,MSFT`). Optional: `GLASS_MOVE_ALERT` (5), `GLASS_BENCHMARK`
      (`SPY`).

### 6. Lenz
- [ ] `TMDB_API_KEY` (themoviedb.org → Settings → API).
- [ ] `LENZ_DOC_URL`: your entertainment log Google Doc, shared "anyone
      with the link can view".
- [ ] `MAL_CLIENT_ID` (myanimelist.net → API → create an app) and
      `MAL_USERNAME`; your MAL list must be public.

- [ ] Optional, games in the release calendar: free key at rawg.io/apidocs →
      `RAWG_API_KEY`.

### 7. Remi's calendar and the rest
- [ ] Google Calendar on a computer: Settings → your calendar → Integrate
      calendar → **Secret address in iCal format** → `REMI_CALENDAR_URLS`.
      Treat it like a password.
- [ ] `BIRTHDAYS` (`Sam:03-14,Grandma:11-02`).
- [ ] `GLASS_BUDGETS` (`Groceries:600,Dining:200`); Rocket Money export
      (computer: Transactions → Export) → Money tab → Import.
- [ ] Optional: `DIGEST_TIME` (default `07:00`), `GITHUB_TOKEN`
      (fine-grained, Issues read/write on this repo) for QWERTY's `/issue`.

### 8. Projects
- [ ] `HOME_LOCATION` (like `Denver, CO`) so "find me a job here" knows
      where "here" is. Or just tell any agent "remember my home is
      Saint George, UT" (look for the ✓).
- [ ] Free Adzuna key: developer.adzuna.com → register (for "website", use
      your hub's address, `https://<project>.vercel.app`) → `ADZUNA_APP_ID`
      and `ADZUNA_APP_KEY` (`ADZUNA_COUNTRY` if not `us`).
- [ ] Government jobs (USAJOBS): developer.usajobs.gov → request an API key
      → `USAJOBS_API_KEY` and `USAJOBS_EMAIL` (the email you used).

### 9. Lenz's channels, Siri and James
- [ ] `LENZ_YOUTUBE`: comma-separated channel links (`https://www.youtube.com/@name`),
      `@handles` or `UC…` ids; links and handles need `YOUTUBE_API_KEY`,
      `LENZ_SUBREDDITS` (like `Silksong,anime`), `LENZ_TWITCH` (logins) with
      `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` (dev.twitch.tv → Your
      Console → Register Your Application; any OAuth redirect, category
      Website Integration).
- [ ] `ASK_KEY` (a long random string), then build the "Ask Theta" Shortcut
      from Settings → Voice commands.
- [ ] Merge and deploy Garage Gym's hub-commands change so James can log.

### 10. High brain (Theta on Claude)
- [ ] platform.claude.com/settings/keys → Create key → Vercel
      `ANTHROPIC_API_KEY` (Sensitive), redeploy. A personal key
      (`sk-ant-usr…`, Linked account: you) works. If the key isn't scoped to
      one workspace, also set `ANTHROPIC_WORKSPACE_ID` (the `wrkspc_…` ID
      on the Console's Workspaces page). Wiring says what's wrong if it fails.
- [ ] Console → Limits → set a $15 monthly spend limit (the hub also
      stops at `MASTER_MONTHLY_CAP_USD`, 15 by default).
- [ ] Settings → Wiring → Theta should read "connected".


## Planned

- [ ] Wiring's **Recheck** button that actually checks. Today it only
      reloads the saved status, so rows that can't be tested stay grey
      even when the job behind them is set up. Rounds reads "No round has
      run yet" until its first scheduled run (00, 12 or 18 UTC: 6 pm, 6 am
      or noon MDT), even though the job is scheduled. Recheck should test
      what it can live and say "scheduled, first run at …" instead of
      "not set up".
- [ ] Get Remi's calendar and Gmail working (setup steps 7 and 4).
- [ ] Get the job boards working: Adzuna and USAJOBS (setup step 8).
- [ ] Token use you can see (asked 2026-10-23; checked: doable).
      - **In chat:** each reply shows its tokens next to the name, tag and
        time (e.g. "17.6k in · 240 out"). Gemini and Groq return `usage`
        on every reply, and Claude returns `usage` too, so the call that
        answered records it on the message.
      - **In Settings:** per model, tokens and calls today and this
        month, and when each limit resets:
        - Claude: the hub's own monthly cap, resets on the 1st.
        - Gemini: daily quota resets at midnight Pacific
          ([Google](https://ai.google.dev/gemini-api/docs/rate-limits)).
          Google doesn't send what's left, so show what we used.
        - Groq: sends what's left and when it resets in its
          `x-ratelimit-*` headers
          ([Groq](https://console.groq.com/docs/rate-limits)), so show
          those.
      - Cost: none for the counting; a few small writes per reply.
- [ ] Two new bots, to be defined later: a habit tracker and a video
      player bot.
- [ ] Scriptable widgets: Home Screen and Lock Screen. Build on a JSON
      version of the Home windows (`/api/windows`), so the widget shows
      the same short titles and pictures.
- [ ] Discord: webhook mirror, then slash commands, then Remi's
      auto-moderation (needs an always-on host, not Vercel).
- [ ] Paid model for Theta.
- [ ] Sending texts on your behalf: SMS via Twilio only if worth the 10DLC
      registration and per-text fees; iMessage only through an iPhone
      Shortcut you run.
- [ ] Glass with practice money (Alpaca paper trading), only if you want it.
- [ ] Lenz writes ratings and status back to MyAnimeList (needs MAL's
      sign-in flow, not just the client ID).

## Ideas (not built yet)

- [ ] **One-tap merge** (a consideration, not needed yet; worth it once
      more updates are automated and checking them by hand takes too long).
      - The 5-minute tick checks both repos for open PRs from the owner's own
        branches only (never forks: `fitness-tracker` is public, so anyone
        can open a PR there), waits for tests to pass, then pushes "PR #N:
        title. Merge / Not now". Merge merges it; Vercel deploys as usual.
      - Not a merge-everything bot: that would ship unreviewed code, or a
        stranger's, straight to production.
      - Needs a fine-grained GitHub token limited to the two repos (pull
        requests and contents: read and write), set in Vercel as Sensitive.
- [ ] **World news + a translator bot.**
      - World news: feeds from outlets in other countries and languages,
        translated, so the news crew isn't only US sources.
      - Translator: translate anything in chat on request; maybe language
        teaching too (daily words, short quizzes, correcting what you write).
      - Decide: one new bot, or give it to Red/Blue/Gray plus a tutor.
- [ ] **Searcher miners** (miner tier: cheap models doing legwork).
      - Searcher: runs longer web searches for the crew and hands back sources.
      - Buyer: finds the best price for something you want. It must never
        pay on its own: it proposes, you approve each purchase (like QWERTY),
        with a spending cap. It would need no card details until that's
        designed properly.
- [ ] Dark (Tor-only search): can't run on Vercel (no Tor there), so it
        needs an always-on host with Tor. Risks to settle first: illegal or
        scam content, malware in fetched pages, and keeping it away from
        Buyer entirely. Read-only search results, never downloads.
- [ ] Video and image rippers: grab a page's main image for reference.
      Downloading videos breaks most sites' terms and is too heavy for
      Vercel, so links only for now.

- [ ] Charter's charts in the current color scheme (they're always light now).
- [ ] Quick actions on Home: log an expense, ask Remi, start a round.
- [ ] Open offline: cache the app's pages like Garage Gym does.
- [ ] Rearrange or pin windows on Home.
