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
`GET /api/tiers`.

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
message gets an answer; the status line says who she picked. She never
picks James, since each of his answers uses a daily question: @mention
him instead. `ALLCHAT_AUTO=off` turns this off, `ALLCHAT_AUTO_MAX` (2)
caps it. Replies and bot posts never trigger more replies, so agents
can't loop and run up the API limits.

**Wiring**, under the chat, shows for each agent whether its key is set
and can use its model (James: whether Garage Gym answers). **Test** sends
a tiny message and shows the reply time; James has no Test button
because each one would use one of his daily questions.


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
