# Handoff: Theta hub and Garage Gym

Read this first in a new session. It covers what exists, how the owner likes
to work, and what's open. Setup steps for the owner live in `TODO.md`;
feature docs live in `README.md`. Nothing here is a secret, and nothing secret
should ever be added.

Last updated: 2026-10-23.

## The two apps

| | Theta (the hub) | Garage Gym |
|---|---|---|
| GitHub | `creatorcee-prog/dashboard-app` (GitHub may show it as `theta-app`; same repo) | `creatorcee-prog/fitness-tracker` |
| Stack | One Python WSGI file, `api/index.py` (~12k lines), on Vercel; Upstash Redis (in-memory store locally) | Next.js + TypeScript on Vercel, Supabase |
| Users | The owner only | The owner's family, so far |
| Tests | `tests/run_all.sh python` (memory and Redis modes); GitHub Actions `.github/workflows/tests.yml` runs it on every PR and push to main | `npm test` (vitest, 309 passing), `npm run typecheck` |

**Theta** is a personal AI hub with a crew of agents in a Discord-style chat:

| Agent | Job |
|---|---|
| Theta | The boss. Runs on Claude when `ANTHROPIC_API_KEY` is set, capped at `MASTER_MONTHLY_CAP_USD` |
| Mistral | The front desk; answers every chat message (`low_brain`) |
| Glass | Budget and stocks |
| Remi | Calendar, reminders, Gmail |
| Lenz | Entertainment: TMDB, MAL, YouTube, Reddit, Twitch, RAWG |
| Charter | Charts |
| James | Garage Gym's coach, mirrored in the hub |
| QWERTY | Watchdog and settings changes, only with approval |
| Red / Blue / Gray | News |

## How the owner works (follow these)

**Honesty and sources**
- Don't just agree. Say so when you disagree, give a rebuttal where there is one, and cite sources for any data.

**Secrets**
- Never ask for keys, tokens or secret links in chat.
- Secrets go only in Vercel → Environment Variables, marked **Sensitive**, then Redeploy.
- The calendar's secret iCal address is a password.

**Branches and pushes**
- Each session is given its own branch name. Use the one the session gives you, in both repos.
- The last two branches were `claude/brave-lovelace-5tuqeg` (PRs #36–#39, GG #18–#20) and `claude/gracious-albattani-ubrura` (this handoff update only).
- If your branch's PR is already merged, restart the branch from `origin/main`.
- Batch your work: **one push per finished change**. See "Deploy limit" below.

**Commits**
- End every commit with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: <this session's link>
  ```
- Don't put model names in commits, PRs or code.

**PRs**
- Open one only when asked. The owner reviews and merges.
- Body: `## Why`, then short sections with bold lead-ins and bullets, then `## Tests`.
- End the body with "🤖 Generated with [Claude Code](https://claude.com/claude-code)" and the session link.

**QWERTY limits**
- QWERTY may never set secrets.
- It may only propose settings on the `SETTABLE` allowlist, and nothing is applied until the owner taps Approve.

**Garage Gym questions sent to the hub** (`/api/gym/ask`)
- Never touch the owner's personal data.
- Mistral only: no tools, no Claude spend, and a daily cap.

**Writing for the owner**
- Plain language and short replies.
- **Always give a link** when there is one: GitHub files, Vercel and Supabase dashboard pages, docs.
- Times in **MDT** (UTC−6), not UTC.
- They use an iPhone (iOS 26.x) Home Screen web app. Test layouts at phone width and in dark mode.

## Hub architecture you need to know

**Request scope**
- `_REQ` is thread-local per request: cookies, session, meta cache, call count, `ch` (current chat channel).
- Executor threads can't see it. Read on the main thread instead (`shared_fetch_many`).

**Storage**
- Use the batched reads and writes: `get_meta_many` / `set_meta_many` and `_HOT_META`, with a 3 s cache.
- Big values (`upload:`, `chart:`, `vision:`, `snap:`) are kept out of the batch.

**Shared snapshots**
- `shared_fetch(name, ttl, fetch)` caches an outside fetch.
- When a snapshot is stale, the page calls `/api/refresh`.
- A failed fetch keeps the old snapshot (`SNAP_KEEP_ON_FAILURE`) and sets a `failed` flag, which shows on Wiring.

**Chat**
- **Default `CHAT_MODE=desk`:**
  - `desk_shortcut` runs plain commands (`$42 groceries`, `remind me…`) with no model call.
  - Everything else goes to `desk_reply`: Mistral, with every agent's facts from `crew_facts()` and every tool.
  - Mistral's `ESCALATE:` hands hard questions to Theta. `SEARCH:` runs a web search.
- `CHAT_MODE=crew` brings back the old per-agent answers. Tests for crew behavior set `h.CHAT_MODE = "crew"`.
- **Display:** every agent message shows as Theta, with a `.via` tag naming the real sender.
- **Activity lines:** `activity(sender, text)` posts kind=event lines into `_REQ.ch`.

**Prompts and tools**
- **Prompts:** `HUB_GUIDE` and `hub_rules(agent)` go only into chat prompts, through `system_prompt(agent, tools=True)`. They stop agents from inventing pages and features.
- **Tools:** the `TOOLS` dict, run by `run_actions`, which returns `{"text","buttons"}`.
- **Unbacked claims:** `_PROMISE_RE` and `_CLAIM_RE` add a note when a reply promises or claims an action without having used a tool.

**QWERTY proposals**
- `_tool_propose` creates a proposal. `/api/chat/press` handles the `qp:<id>:yes|no` buttons.
- `apply_proposal` sets the value with `vercel_set_env`, then calls `vercel_redeploy` through the deploy hook.
- This needs `VERCEL_TOKEN`, `VERCEL_PROJECT` and `VERCEL_DEPLOY_HOOK`.

**Other features**
- **Devices:**
  - Sessions use the `hub_sess` cookie; only its hash is stored.
  - `/api/devices/hello` pairs a push subscription with its session.
  - Sessions expire after 45 idle days.
- **Home:** the Smart Stack (`stack_cards`, `stack_html`) replaced the KPI tiles. Dots are in `ui.js`.
- **Speed card:** `perf_record` and `perf_rows`.

**`/api/gym/ask`**
- Requires the `x-hub-secret` header to equal `GARAGE_GYM_SECRET`. Wrong values count toward the wrong-key lockout.
- `gym_ask` uses `low_brain` and a Gemini search only.
- Capped by `GYM_ASK_DAILY` (40): 429 past the cap, 502 when the models fail.

**Garage Gym side**
- Code: `src/lib/ai/ask.ts`.
- When James answers `ASK_HUB: <q>`, `askHub()` sends the question to the hub, then a second model call writes his answer.
- Only https sources are kept.
- The feature is off until `HUB_URL` and `HUB_SECRET` are both set.

## Gotchas (each has bitten before)

- **Page scripts inside Python strings** (`_PUSH_JS` and others):
  - A raw `"\n"` in them breaks the JS and silently killed notifications once. Escape it as `\\n`.
  - `tests/test_jssyntax.py` checks for this.
- **String building:** watch for `+ +` slips, and for clashing JS variable names in `ui.js`.
- **No PR events reach the session:** the Claude GitHub App isn't installed on these repos. Check CI by reading the PR's check runs.
- **Wording-sensitive tests:** some tests assert on UI wording. Update them together with the copy.
- **Lockouts:** only keys that were actually presented count. A cleared cookie after a 401 must not count.

## Deploy limit (important right now)

**The limit**
- Vercel's Hobby plan allows **100 deployments per day per account**, shared by both projects ([vercel.com/docs/limits](https://vercel.com/docs/limits)).
- Every branch push makes a preview deployment in each linked project.

**Current status (checked through the Vercel connector, 2026-10-23 ~05:40 UTC)**
- The limit was hit around 04:47 UTC. Hub PR #39's preview was refused.
- **Hub #39 is NOT live.** The GitHub status on merge commit `2417a49` says "Deployment rate limited — retry in 24 hours" (04:59 UTC).
- Hub production is still **#38** (`76aa770`). A second production deploy of that same #38 commit was made at 05:06 UTC, probably a Redeploy of the old production deployment. Redeploying an old deployment rebuilds *its* commit, not `main`.
- **Garage Gym #20 is NOT live either.** `main` is `3ff39fc` (#20), but GG production is still #19 (`4c8165f`).
- Preview builds were going through again by 05:22 UTC, so the limit may already be clearing.
- **Update, ~06:05 UTC (12:05 AM MDT): hub #39 (`2417a49`) is live** (owner used Create Deployment → `main`). Garage Gym's deploy was refused by `api-deployments-free-per-day` right after; retry after ~3:05 AM MDT.
- **First thing to do:** list production deployments in both projects. If `2417a49` (hub) and `3ff39fc` (GG) are still missing, get them built. Easiest: the owner opens Deployments, finds the newest deployment *of that commit* (a preview is fine) and uses Redeploy → Production. Or ask the owner before triggering a deploy through the connector.
- **Quick way to tell from the app:** if one chat message gets a single reply, shown as Theta with a "Mistral" tag, #39 is live.

**Planned fix**
- Set Project → Settings → Git → **Ignored Build Step** to "Only build production", or as a custom command:
  ```
  [ "$VERCEL_ENV" != "production" ]
  ```
- Do this in both projects so branch pushes stop using up the quota.
- Not yet confirmed as of 2026-10-23 ~05:40 UTC. The connector's project summary doesn't show this setting, so ask the owner.

**Vercel access for Claude**
- **The Vercel connector is linked** (2026-10-23). New sessions get `mcp__Vercel__*` tools.
- It is **not read-only**: it has about 200 tools, including deploy, env var, domain and project changes. It acts with the owner's full access.
- **It can't deploy or read runtime logs yet.** Both return 403 for scope `cee-5458`; `authorize_team_access` is refused ("This token cannot request SSO authorization for a team"). Listing projects and deployments works. Likely fix (untested): owner reconnects the connector at claude.ai/customize/connectors and picks the `cee-5458` scope.
- Rule: **read freely, change nothing without asking the owner first**, every time. Env var changes still go through QWERTY's approval flow, and Claude never sets secrets.
- IDs (not secrets):
  - Account scope: `team_XOyKnNUHANr6xVl6wVZzQ6jU` (slug `cee-5458`). `list_teams` returns empty; pass this as `teamId` if a call needs scope.
  - Hub project: `dashboard-app`, `prj_G7Khk8Wn6JRW4t4lXDhGKHM6gYvx`, at `dashboard-app-five-theta.vercel.app`.
  - Garage Gym project: `fitness-tracker`, `prj_iwiG889gkExJsmBWxus9BjZmfx7k`, at `fitness-tracker-snowy-seven-83.vercel.app`.
- Useful reads: `list_deployments` (with `projectId`, `target: production`), `get_deployment`, `list_deployment_events` for build logs, `get_runtime_errors` then `get_runtime_logs` for production errors.
- Vercel Authentication (SSO protection) is on for previews, so preview URLs need the owner's sign-in.

## Schedules (Supabase Cron, in Garage Gym's Supabase project)

- Jobs: `fitness-reminders` (GG, every minute), `bot-hub-rounds` (hub, 00/12/18 UTC), `bot-hub-tick` (hub, every 5 min).
- 2026-10-23: the hub jobs were first saved with the `YOUR-HUB` placeholder still in the address (404s). Fixed with `cron.alter_job(... replace(command, 'YOUR-HUB', 'dashboard-app-five-theta'))`; all 200 since. The secret is in the job command, so never ask the owner to show `command` in full.
- In `net._http_response`, GG's replies look like `{"due":…,"sent":…,"skipped":…}`; the hub's don't. Don't mix them up.

## Recent history

| PR | What |
|---|---|
| Hub #38 | Hub map and firm rules, QWERTY proposals with Approve/Decline, tickable checklists |
| Hub #39 | Front desk; every reply shown as Theta; tests in repo plus GitHub Actions; activity lines; `/api/gym/ask` |
| GG #20 | James asks the hub (`ASK_HUB`) |

Earlier: per-device sessions, Face ID fixes, notification fixes, personal `sk-ant-usr` keys, readable tables, speed work, Smart Stack, simpler Devices card.

## Open items

**Owner setup** (details in `TODO.md`)
- Get GG #20 (`3ff39fc`) into production (hub #39 is live). Set GG's `HUB_URL` to `https://dashboard-app-five-theta.vercel.app` before that deploy.
- Ignored Build Step: owner says it's set in both projects; the next branch push should show as Canceled/skipped in Vercel. Confirm then.
- Set Ignored Build Step in both projects.
- Optional, for QWERTY: `VERCEL_TOKEN`, `VERCEL_PROJECT`, `VERCEL_DEPLOY_HOOK`.
- Keys: `YOUTUBE_API_KEY` (needed for channel links and handles), `RAWG_API_KEY` (the owner has the key, but it may not be in Vercel yet), Adzuna keys.
- Send a new Speed card screenshot after the deploy.
- Test: ask James in Garage Gym something general, like "Is creatine safe to take every day?" He should say he checked with his crew and list sources.

**Ideas offered but not started**
- **Spotify for Lenz plus concerts near you.** Discussed and feasible:
  - Spotify's top and followed artists, then a Ticketmaster Discovery API search near `HOME_LOCATION`.
  - Not started. The owner hasn't said go.
- **An `ask_james` tool for the desk:** ask James in hub chat, with full Garage Gym logs.
- **A Lenz Channels section:** the owner said wait.
- **A Haiku reviewer:** declined for now.
- More ideas are in `TODO.md` under Planned and Ideas.
