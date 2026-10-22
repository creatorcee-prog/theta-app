# Bot hub — Vercel edition

Interim build while Railway is down. Same hub as `../bot-hub` (tiers,
report / escalate / commandeer, dashboard widgets), reworked for
Vercel's serverless model: `api/index.py` is one Python function,
`vercel.json` routes every path to it.

## Why it differs from the Railway build

- **No always-on server.** Vercel runs functions per request.
- **No local SQLite.** Serverless filesystems don't persist, so
  storage is **Upstash Redis** (what Vercel KV became) over its REST
  API (stdlib `urllib`, no SDK). Without KV vars the app still runs, but on an in-memory
  store that resets between requests — the dashboard says so in a
  footer banner. Don't rely on memory mode for real bot traffic.

## Deploy on Vercel

1. Push this folder to a GitHub repo (or run `vercel` from it).
2. Vercel dashboard → Add New Project → import the repo.
3. Storage → Create Database → **Upstash for Redis** (Marketplace)
   → connect it to this project. That adds the REST URL and token to
   the project's env vars; either `KV_REST_API_URL` /
   `KV_REST_API_TOKEN` or `UPSTASH_REDIS_REST_URL` /
   `UPSTASH_REDIS_REST_TOKEN` works. **Redeploy afterwards** — env
   vars only reach new deployments. The dashboard footer says
   `Storage: upstash-redis` once it's live.
4. Settings → Environment Variables — set:
   - `BOT_KEYS` — `bot-id:key,...` (one key per bot; bots never hold
     model keys). Use an agent's id (`theta`, `mistral`, `glass`,
     `remi`, `lenz`, `red`, `blue`, `gray`, `charter`) as its bot-id and
     it gets that agent's tier and name automatically
   - `BOT_ROLES` — `bot-id:miner|manager|low_brain|master,...` (only
     needed for bots that aren't agents, or to override one)
   - `BOT_NAMES` — `bot-id:@name,...` (override a display name)
   - `DASHBOARD_KEY` — recommended: the dashboard is public on the
     Vercel domain without it
   - `GEMINI_API_KEY` — the low brain's model, Gemini (from
     aistudio.google.com → Get API key). Until the paid high-brain
     model is wired, it also runs Theta: chat, `/api/summary` and
     `master_work()`
   - `GROQ_API_KEY` — managers and miners (from console.groq.com)
   - Optional model overrides: `MINER_MODEL` (default
     `openai/gpt-oss-20b`), `MANAGER_MODEL` (`openai/gpt-oss-120b`),
     `LOW_BRAIN_MODEL` (`gemini-3.8-flash`). Providers retire models:
     when chat says a model doesn't exist, open `/api/models` (dashboard
     key) to see what your keys can use and set the override.
     `GEMINI_REASONING_EFFORT` and `GROQ_REASONING_EFFORT` (both `low`;
     Groq sends it to gpt-oss models only; empty sends nothing) keep
     thinking from using up the reply. An agent whose key is missing
     answers chat with "…_API_KEY is not set" instead of failing
   - `NEWS_FEEDS` — comma-separated RSS URLs; the default is 10 outlets
     across the spectrum. `NEWS_TOP` (8), `NEWS_BREAKING_MAX` (2) and
     `NEWS_BREAKING_MINUTES` (90) shape the News section
   - `ENTERTAINMENT_FEEDS` — comma-separated feed URLs; `FITNESS_APP_URL`
     defaults to the deployed fitness app
   - `AGENT_ONLINE_SECONDS` (600) — how recently a bot must have called
     the hub to show as online
   - `GARAGE_GYM_URL` (defaults to `FITNESS_APP_URL`) and
     `GARAGE_GYM_SECRET` — links James. The secret must equal
     `HUB_SECRET` in Garage Gym, where `HUB_USER_ID` picks whose
     training James sees (see Garage Gym's README, "Bot hub link")
   - Agent jobs (each optional; the Wiring panel shows what's set up):
     - `CRON_SECRET` — lets Supabase Cron run rounds (see Rounds)
     - `REMI_CALENDAR_URLS` — Google Calendar "Secret address in iCal
       format" (Settings → your calendar → Integrate calendar), comma-
       separated; treat like a password. `BIRTHDAYS` — `Name:MM-DD,...`.
       `HUB_TIMEZONE` (`America/Denver`) for times
     - `RED_FEEDS`, `BLUE_FEEDS`, `GRAY_FEEDS` — override each news
       miner's outlets
     - `TMDB_API_KEY` — Lenz's trending movies and shows (themoviedb.org,
       free for personal use; v3 key or v4 read token)
     - `GLASS_BUDGETS` — `Groceries:600,Dining:200,...` monthly limits;
       `GLASS_CATEGORY_MAP` — `Restaurants:Dining,...` renames
     - `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` — phone notifications;
       open `/api/push/new-keys` (signed in) for a pair. `VAPID_SUBJECT`
       optional (defaults to the dashboard's own address)
5. Deploy. The dashboard is at `https://<project>.vercel.app`, and
   bots point at `https://<project>.vercel.app/api/report`.

## Run locally (memory store)

```sh
BOT_KEYS="miner-1:key1,master-1:mkey" \
BOT_ROLES="miner-1:miner,master-1:master" \
BOT_NAMES="miner-1:@cine_miner,master-1:@big_brain" \
PORT=8770 python3 api/index.py
```

Then open http://localhost:8770. Set `KV_REST_API_URL` /
`KV_REST_API_TOKEN` (or the `UPSTASH_REDIS_REST_*` pair) as well to
test against a real Redis store.

## Endpoints

Same as the Railway build: `POST /api/report`, `POST /api/escalate`,
`POST /api/commandeer`, `POST /api/orders/<id>/ack`,
`POST /api/fitness`, `POST /api/summary` (dashboard key),
`POST /api/chat` (dashboard key), `POST /api/status`, `GET /`
(dashboard), `GET /api/feed`, `GET /api/orders`, `GET /api/escalations`,
`GET /api/widgets`, `GET /api/fitness`, `GET /api/agents` (dashboard
key), `GET /api/models` (dashboard key), `GET /api/wiring` (dashboard
key), `GET|POST /api/allchat` (dashboard key or bot key), `GET /api/bots`,
`GET /api/tiers`, `POST /api/round` (CRON_SECRET or dashboard key),
`GET /calendar` (Remi's tab), `GET /api/glass`, `POST /api/glass/expense`
(dashboard or bot key), `POST /api/glass/import` (`{"csv": ...}`),
`GET /chart/<id>.svg`, `GET /api/push/key`, `GET /api/push/new-keys`,
`POST /api/push/subscribe`, `POST /api/push/test`, plus the Home Screen
app files `/manifest.webmanifest`, `/sw.js` and icons. Every page
accepts the dashboard key once as `?key=` and then remembers it in a
cookie.

## Agents

Named personas, like James in Garage Gym: the name is the persona,
the model comes from the agent's tier. Edit `AGENTS` in
`api/index.py` to change a name or role. Personalities are the keyword
sets in `PERSONAS`, picked in the Crew Files page
(https://claude.ai/artifact/UCNdEUqtBDUNN5VAekSMuS); "concise" also
asks the agent for short answers.

| Agent | Tier | Role |
|---|---|---|
| Theta | High Brain (master) | Final say, planning, commandeer orders |
| Mistral | Low Brain | Triages escalations, summarizes reports |
| Glass | Manager | Accountant and general manager |
| Remi | Manager | Family reminders, calendar, Discord auto-mod |
| Lenz | Miner | Entertainment |
| Red / Blue / Gray | Miner | News: Republican / Democratic / independent take |
| Charter | Miner | Makes charts on request |
| James | Manager | Fitness coach; lives in Garage Gym |

**James** is the real coach from Garage Gym, not a persona copied here.
Chatting with him calls Garage Gym's `/api/hub`, so he answers with
his own prompt, your training data and his daily question limit, and
the Fitness card shows the training summary he reads before answering.
He shows online whenever Garage Gym answered in the last
`AGENT_ONLINE_SECONDS`. Changes he proposes have to be applied in the
app.

So far the other agents are each a chat persona plus a status line. Their jobs
(Remi's calendar and moderation, Charter's charts, the news miners'
searches) need their own bots or tools and aren't built yet.

**Status.** A bot is online when it has called the hub in the last
`AGENT_ONLINE_SECONDS`. Any authenticated call counts; to say what it
is doing:

```sh
curl -X POST https://<project>.vercel.app/api/status -H "x-bot-key: $KEY" \
  -d '{"bot_id": "remi", "activity": "checking the calendar"}'
```

## Chat

**All Agents** (first in the chat picker) is one shared, saved thread
(the last 200 messages). You post with the dashboard key; bots post with
their own key (`POST /api/allchat {"bot_id", "text"}`, `x-bot-key`) and
read it with `GET /api/allchat?bot_id=…`. @mention agents (`@remi`,
`@james`) and each one named answers once (up to 3 per message), with
the recent thread as context. With no @mention, Mistral picks the 1–2
agents whose job fits best (just herself for small talk), so every
message gets an answer; the status line says who she picked.
`ALLCHAT_AUTO=off` turns this off, `ALLCHAT_AUTO_MAX` (2)
caps it. Replies and bot posts never trigger more replies, so agents
can't loop and run up the API limits.

**Events.** What agents do shows up in All Agents as gray, templated
lines (no tokens): reports, escalations, commandeer orders and acks,
fitness summaries, and status changes. Agents see them as `[event]`
lines in their context.

**Rounds.** `POST /api/round` runs each agent's own job and posts what
it did. Every job works from real data only; with nothing to work from
an agent says so instead of inventing work.

| Agent | Each round | Tokens |
|---|---|---|
| Theta | Summarizes new reports; decides escalations that reach him (`ORDER:` replies issue a commandeer order); Sundays, a weekly review from the week's real facts | only when there's something to do |
| Mistral | Once a day, the morning digest (calendar, birthdays, headlines, budget, overnight activity); flags breaking news; answers Low Brain escalations or forwards them to Theta; wiring check on first run and on change | ~1 a day, plus triage |
| Remi | Once a day, today's agenda from the family calendar; an update when today's plans change; birthdays 7 days, 1 day and the day of | 1 a day |
| Glass | Budget alerts at 90% and 100% (once per category per month); Sundays, the week in review | none |
| Red, Blue, Gray | Each takes the same new top story, grounded in how their own outlets covered it, or noting they haven't | 3 small calls |
| Lenz | Pitches a new trending title from TMDB's real synopsis, date and rating (feeds without a key) | 1 small call |
| Charter | Sundays, the month's spending chart | none |
| James | Refreshes your Garage Gym summary; notes when it changed | none |

**Phone notifications.** Mistral pushes the digest one-liner, breaking
news, Remi's birthday reminders, Glass's budget alerts, wiring problems,
escalations to Theta and Theta's decisions. On iPhone (iOS 16.4+):
open the dashboard in Safari, Share → Add to Home Screen, open it from
the Home Screen, and tap **Turn on** under Agents. Needs the VAPID keys.

**Remi's calendar** is its own tab (`/calendar`): a month grid and a
day-by-day list from your Google Calendar, plus `BIRTHDAYS`. Remi's chat
answers from the same calendar.

**Glass's budget.** Log spending with "@glass $42 groceries" (in his
chat or All Agents; confirmed with exact numbers, no model call),
`POST /api/glass/expense`, or import a Rocket Money export on the Budget
card. Rocket Money has no public API: export CSV from Transactions on a
computer. The importer finds the columns by header, works out whether
expenses are positive or negative, skips income, transfers, card
payments, refunds and ignored rows, and is safe to re-run.

**Charter's charts** are SVG images drawn from hub data: spending by
category against budgets, daily spending, calendar busyness, news
coverage by side, and All Agents activity. Ask "@charter chart my
spending".

A failed job doesn't count as run, so it's retried next round. Run one
from the dashboard (**Run a round now**, under Agents) or on a schedule:
set `CRON_SECRET` in Vercel, then run `supabase/cron.sql.example` in the
Supabase SQL editor (3 times a day by default). `ROUND_MIN_GAP_MINUTES`
(120) stops a job from running twice too close together.

**Slash commands and mentions.** In the chat box, `@` lists the agents
(All Agents only) and `/` at the start lists commands, like Discord:
type to filter, arrows and Enter/Tab to pick, Esc to close, or tap.
Commands run on demand and post into All Agents:
`/commandeer <order>` (an order to the crew from you), `/round`,
`/digest`, `/agenda [tomorrow]`, `/spend $42 groceries`, `/budget`,
`/chart spending|daily|calendar|coverage|activity`, `/news`,
`/trending`, `/summary`, `/status`, `/help`. Add one by appending to
`COMMANDS` in `api/index.py`. Bots posting "/..." just post text.

**Wiring**, under the chat, shows for each agent whether its key is set
and can use its model (James: whether Garage Gym answers). **Test** sends
a tiny message and shows the reply time.


The dashboard has a chat box: pick an agent and talk to it.
History lives in the page (reload clears it). The same thing over
the API:

```sh
curl -X POST https://<project>.vercel.app/api/chat \
  -H "x-dashboard-key: $DASHBOARD_KEY" -H "Content-Type: application/json" \
  -d '{"agent": "mistral", "messages": [{"role": "user", "content": "hi"}]}'
```

`POST /api/summary` asks Theta (on the low brain's model for now)
to summarize unprocessed reports, and marks them processed only when
the call succeeds.
