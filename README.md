# Theta — the bot hub, Vercel edition

Theta is the app (named after the crew's High Brain, whose θ is the app
icon). Interim build while Railway is down. Same hub as `../bot-hub` (tiers,
report / escalate / commandeer, dashboard widgets), reworked for
Vercel's serverless model: `api/index.py` is one Python function,
`vercel.json` routes every path to it.

## The app

Five tabs (a sidebar on wide screens, a tab bar on phones): **Home**,
**Chat**, **Calendar** (Remi), **Money** (Glass) and **Settings**, plus
a profile page per agent (`/agent/<id>`) with its latest window,
persona, abilities, model and recent posts.

**Home** shows today at a glance (budget ring, today's events, crew
online, breaking news), then a **window** per agent: its latest output
squeezed to a short title, with a picture. Pictures are real where they
exist: each story's own photo from its outlet's feed, TMDB stills, Apple
Music album art, Charter's charts, and generated tiles for dates and
budgets. Then the top stories and what's trending, as windows too.

Titles are condensed once per round: one small miner-model call turns
up to 30 new headlines into widget titles of 6 words or fewer and names
each one's main subject. Windows with no picture of their own get the
subject's free-licensed photo from Wikipedia (a few lookups per round,
remembered for a week; a failed lookup is retried, not remembered).
The dashboard itself never calls a model: before a round has condensed
a title, it trims it (drops the outlet's name and "BREAKING:", cuts at a
word).

**Look.** Settings has 12 color schemes (Theta, Midnight, Nebula,
Aurora Glass, Graphite, Lobby, Forest, Ember, Ocean, Paper, Sakura,
Terminal). Each has a light and a dark version, and follows the phone's
setting unless you pick Light or Dark. Four Home layouts: **Grid**
(tiles), **Feed** (one big card at a time), **Magazine** (the newest
photo window as a headline, then rows you swipe) and **Compact** (a
list with thumbnails). The choice is saved in a `theta_ui` cookie on
that device, so pages render in it with no flash. Every scheme was
checked for contrast: body text 7:1 or better, secondary text, links
and buttons 4.5:1 or better, in both modes.

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
`POST /api/push/subscribe`, `POST /api/push/test`, the pages `/chat`
(`?ch=<channel>&to=<agent>`), `/money`, `/settings` and `/agent/<id>`,
plus `/ui.css`, `/ui.js`, `/chat.js`, `/avatar/<id>.svg` and the Home
Screen app files `/manifest.webmanifest`, `/sw.js` and icons. Every page
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

Chat works like a Discord server: channels on the left, members and
their status on the right (a sheet on phones), avatars, and messages
grouped by sender. **#all-agents** (the default) is one shared, saved
thread (the last 200 messages); the other channels are views of it:

| Channel | Who's in it | Without an @mention |
|---|---|---|
| #all-agents | everyone | Mistral picks who answers |
| #news | Red, Blue, Gray | all three answer |
| #money | Glass, Charter | Mistral picks between them |
| #family | Remi | Remi |
| #watch-and-listen | Lenz | Lenz |
| #gym | James | James |
| #command | Theta, Mistral, round reports | Mistral picks between them |

A channel shows what was said in it plus its members' own posts (round
jobs post to their home channel); #all-agents shows everything, tagged
with its channel. An @mention works in any channel. There's no separate
one-on-one chat any more: an agent's page has **Message**, which opens
their channel with the @mention typed. With `GET|POST /api/allchat`,
`channel` picks the channel. You post with the dashboard key; bots post with
their own key (`POST /api/allchat {"bot_id", "text"}`, `x-bot-key`) and
read it with `GET /api/allchat?bot_id=…`. @mention agents (`@remi`,
`@james`) and each one named answers once (up to 3 per message), with
the recent thread (of that channel) as context. With no @mention in #all-agents, Mistral picks the 1–2
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
| Mistral | Once a day at `DIGEST_TIME`, the morning digest (calendar, reminders, birthdays, headlines, budget, overnight activity); flags breaking news; answers Low Brain escalations or forwards them to Theta; wiring check on first run and on change | ~1 a day, plus triage |
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
the Home Screen, and tap **Turn on** in Settings. Needs the VAPID keys.
The hub trims pasted spaces, line breaks and quotes from the keys, and
tells you if they're missing, swapped, malformed or not a pair, or if
the push library didn't install. `GET /api/push/health` (public) reports
just the status code and device count, never key material.

**Remi's calendar** is its own tab (`/calendar`): a month grid (dots on
phones) and a day-by-day list from your Google Calendar, plus `BIRTHDAYS`. Remi's chat
answers from the same calendar.

**QWERTY, the watchdog** (#dev-and-security; Settings → Security and health).
Each round he checks every agent's wiring, failed round jobs, busy models
that fell back, dead feeds, push errors, storage, the dashboard key's
strength and `CRON_SECRET`, and posts only when what he sees changes
(pushing new "fix now" findings). Weekly he checks every installed Python
package against Google's OSV vulnerability database.
- Wrong keys are counted per address; `SEC_MAX_FAILS` (10) in 15 minutes
  locks that address out for `SEC_LOCK_MINUTES` (30), even with the right
  key, and pushes you an alert.
- Every response carries security headers (no framing, no MIME sniffing,
  a strict referrer policy), and the key is wiped from the address bar
  once the login cookie is set.
- API keys, tokens, private keys and your own secrets pasted into chat are
  hidden before they're saved or sent to any model, and he tells you to
  rotate them.
- Code help: ask him in his channel (he knows how the hub is built), or
  `/issue <title> - <details>` and he writes up a GitHub issue with a
  suggested fix, filed when `GITHUB_TOKEN` (fine-grained, Issues: read and
  write on this repo only) is set; `GITHUB_REPO` picks the repo. He never
  changes or deploys code himself. `/security` posts what he sees now.
- **Face ID sign-in** (Settings → Face ID sign-in → Add this device).
  A passkey: your phone checks your face and signs a one-time challenge;
  the hub only ever sees a public key and the signature, never your face
  or a picture. Once added, opening the app signed out shows a "Sign in
  with Face ID" page, so you no longer need `?key=` in links or Home
  Screen icons. Passkeys belong to the address you added them on (a
  preview deployment's URL needs its own). Remove a lost device in the
  same card; the dashboard key still works as a fallback.

**Article briefs.** Before Red, Blue and Gray take the round's story, the
hub reads the article itself and one small model call writes a neutral
brief: 2-3 sentences, at most two exact quotes, and one line on how the
piece frames it (loaded words, whose voices lead, what's left out). Every
quote is checked word for word against the article; a sentence quoting
anything the article doesn't say is dropped. Every author is credited
(from the page's structured data, author tags or "By ..." line). Gray
posts the brief with his take; Red and Blue argue from it. Lenz's news on
what you follow gets the same treatment, and story sheets on Home show the
brief. Only the brief, short quotes and the link are kept; the article
text is used once and dropped. The hub reads as itself
(`Theta-dashboard/1.0`); sites that refuse automated readers (The Hill
and the New York Times do) are respected, and the brief comes from the
outlet's own feed summary instead, saying so.

**Remi's reminders.** `/remind 8am every day take my meds until done`,
`in 20 min check the oven`, `fri 6pm pay rent weekly`, or tell Remi "remind
me ...". Daily, weekday and weekly repeats in `HUB_TIMEZONE`. "Until done"
ones re-send every `REMINDER_NAG_MINUTES` (15), up to `REMINDER_NAG_MAX`
(4) times, until you tap Done on the Calendar tab or tell Remi "done" or
"took them". `POST /api/tick` sends what's due; run it every 5 minutes with
the `bot-hub-tick` job in `supabase/cron.sql.example`. No model calls.
Add one from anywhere: tap Remi's window on Home (the sheet has an add box
and Done buttons), her page, or the Calendar tab. A reminder you haven't
marked done takes over her window, and tapping its notification opens her
page. Today's reminders are also listed in Mistral's morning digest.

**Remi's email** (Settings → Gmail → Connect; the Email page at `/mail`).
Each round she reads your inbox (last 2 weeks) and labels new threads in
Gmail under **Theta/Family, Friends, Work, Bills, Shopping, Newsletters,
Other**. She tracks what's waiting on your reply and drafts replies for
the unimportant ones (not family, friends or work; change with
`GMAIL_IMPORTANT`). Drafts are real Gmail drafts too. On the Email page
you edit, then **Send** (a threaded reply from your Gmail) or **Skip**;
nothing is ever sent without that tap. Important emails are listed; tap
**Draft a reply** if you want her help. New senders appear under "Who are
these?" so you can correct her guess once. `GMAIL_ARCHIVE=newsletters`
also moves those out of the inbox. Emails go to the models as data with
an instruction to ignore anything inside them; the worst a hostile email
can do is produce a bad draft you then don't send. Needs
`GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` (a Google Cloud OAuth
client; its sign-in is stored encrypted with a key from your dashboard
key, so changing that key means reconnecting).

**Glass, analyst** (Money tab → Stocks). With `FINNHUB_API_KEY` (free at
finnhub.io), `GLASS_HOLDINGS` (`AAPL:10,VTI:25`) and/or `GLASS_WATCHLIST`
(`NVDA,MSFT`), each of her rounds saves prices, posts and pushes a move of
`GLASS_MOVE_ALERT`% (5) or more once, flags earnings within a week, and
on Sundays posts the week: your holdings against the S&P 500
(`GLASS_BENCHMARK`, default `SPY`), the biggest movers and a headline
each. The Money tab charts holdings against the S&P 500, both indexed to
the first day she has prices for. She reports and explains; she never
trades or advises buying or selling.

**Voices.** Settings → Voices: **Babble** (game-style sounds as replies type
out, a pitch and timbre per agent; offline), **AI voices** (Gemini speaks
as each agent with a voice and manner chosen for them, via `POST
/api/voice`; `GEMINI_TTS_MODEL` picks the model; falls back to phone
voices on any error), or **Phone voices**.

**Projects** (`/commandeer find me a job here`, or `/project ...`). An
order that starts like a task (find, search, look for, research, compare,
get me, list...) becomes a project: Theta splits it into up to 4 parts
and gives each to the agent it suits; each agent searches the web for
their part (Gemini with Google Search, your `GEMINI_API_KEY`); only leads
the search results back are kept, each with its source link, and leads
two agents found are posted once. Results go to #command, Theta sums up,
and your phone gets a push. Each day Theta's round reruns active projects
and posts only new leads, until the order expires (`ORDER_DAYS`) or
`/stopproject <n>`. "Here" / "near me" uses `HOME_LOCATION` (like
`Denver, CO`).

Job hunts (a goal that mentions a job, role, position, hiring...) go to
the job boards first: Adzuna (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`,
`ADZUNA_COUNTRY`, default `us`; free at developer.adzuna.com) and USAJOBS
(`USAJOBS_API_KEY` and the `USAJOBS_EMAIL` you registered with; free at
developer.usajobs.gov), with pay, company, place and dates. Every link,
from the boards or the web, is opened first: a 404/410, a site that
doesn't exist, or a "no longer accepting applications" page is dropped;
sites that refuse robots are kept (we can't tell). The web search only
runs when fewer than `JOB_MIN_LEADS` (8) live board leads turn up, or
for projects that aren't job hunts. Searches are counted against `SEARCH_MONTHLY_CAP` (4000;
Gemini's free tier includes 5,000 a month); `GEMINI_SEARCH_MODEL` picks
the model.

**Sound check** (Settings → Voices) plays one line in the chosen style and
shows what the phone reports: the style, whether replies are read aloud,
the sound engine's state, phone voices, the silent-switch override, and
the last voice error.

**Morning digest time.** The tick sends Mistral's digest at `DIGEST_TIME`
(default `07:00`, hub time), so it no longer waits for a round. Without
the tick job, it goes out with the first round after that time.

**Lenz's library** (`/lenz`; his Home window opens it): what you're on,
up next (by tier), waiting on new seasons, finished (with your 1-10
ratings), your rankings, a taste file and news about what you follow.
- Import your log by pasting its text, or set `LENZ_DOC_URL` (a Google
  Doc shared "anyone with the link can view") and Lenz re-reads it daily.
  It understands Current / In Queue / Waiting / Rankings / Overall
  Rankings / Most beloved, type codes like (AN) (G) (MW), "w/" names,
  episode and chapter progress, tiers and "2x" rewatches. What you change
  in the hub (finished, started, ratings) is never undone by a re-import.
- MyAnimeList: set `MAL_CLIENT_ID` (create one at myanimelist.net/apiconfig)
  and `MAL_USERNAME`; your anime and manga lists sync in daily (the list
  must be public). Updating MAL from here would need MAL's sign-in flow;
  not built yet.
- Each round Lenz finds posters and genres for a few titles (Jikan for
  anime and manga, TMDB for film and TV, Wikipedia for the rest), posts
  news from `LENZ_NEWS_FEEDS` (MyAnimeList, IGN, GameSpot, Polygon) that
  names something you follow (a push for titles you're waiting on), and
  on Sundays a taste report: what you finished, how you rated it, and how
  your averages and top genres moved.
- "I finished Frieren, 9/10" to Lenz logs it; "Watched it" on any of his
  windows does the same.

**Glass's budget.** Log spending with "@glass $42 groceries" (in his
chat or All Agents; confirmed with exact numbers, no model call),
`POST /api/glass/expense`, or import a Rocket Money export on the Money
tab. Rocket Money has no public API: export CSV from Transactions on a
computer. The importer finds the columns by header, works out whether
expenses are positive or negative, skips income, transfers, card
payments, refunds and ignored rows, and is safe to re-run.

**Charter's charts** are SVG images drawn from hub data: spending by
category against budgets, daily spending, calendar busyness, news
coverage by side, and All Agents activity. Ask "@charter chart my
spending".

A failed job doesn't count as run, so it's retried next round. Run one
from Home (**Run a round**) or Settings, or on a schedule:
set `CRON_SECRET` in Vercel, then run `supabase/cron.sql.example` in the
Supabase SQL editor (3 times a day by default). `ROUND_MIN_GAP_MINUTES`
(120) stops a job from running twice too close together.

**Slash commands and mentions.** In the chat box, `@` lists the agents
and `/` at the start lists commands, like Discord:
type to filter, arrows and Enter/Tab to pick, Esc to close, or tap.
Commands run on demand and post into All Agents:
`/commandeer [@agent ...] <order>`, `/orders`, `/done <number>`, `/round`,
`/digest`, `/agenda [tomorrow]`, `/spend $42 groceries`, `/budget`,
`/chart spending|daily|calendar|coverage|activity`, `/news`,
`/trending`, `/summary`, `/status`, `/help`. Add one by appending to
`COMMANDS` in `api/index.py`. Bots posting "/..." just post text.

**Orders.** `/commandeer` gives a standing order to the whole crew, or
to the agents you @mention. Named agents acknowledge it in All Agents,
saying what they'll do and what's outside their abilities (Theta answers
for crew-wide orders). Until it's closed with `/done <number>` or expires
after `ORDER_DAYS` (7), the order sits in each addressed agent's prompt,
so it shapes their chat and round writing. Templated jobs (budget
alerts, agendas, charts) don't change. Every agent's prompt also lists
what it can actually do, so they don't promise what they can't. Bots
get their own and crew-wide orders from `/api/orders`.

**Wiring**, in Settings, shows for each agent whether its key is set
and can use its model (James: whether Garage Gym answers). **Test** sends
a tiny message and shows the reply time.


Talking to one agent outside the shared thread (Wiring's **Test** uses
this) goes over the API; history is whatever you send:

```sh
curl -X POST https://<project>.vercel.app/api/chat \
  -H "x-dashboard-key: $DASHBOARD_KEY" -H "Content-Type: application/json" \
  -d '{"agent": "mistral", "messages": [{"role": "user", "content": "hi"}]}'
```

`POST /api/summary` asks Theta (on the low brain's model for now)
to summarize unprocessed reports, and marks them processed only when
the call succeeds.
