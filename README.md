# Bot hub — Vercel edition

Interim build while Railway is down. Same hub as `../bot-hub` (tiers,
report / escalate / commandeer, dashboard widgets), reworked for
Vercel's serverless model: `api/index.py` is one Python function,
`vercel.json` routes every path to it.

## Why it differs from the Railway build

- **No always-on server.** Vercel runs functions per request.
- **No local SQLite.** Serverless filesystems don't persist, so
  storage is **Vercel KV** over its REST API (stdlib `urllib`, no
  SDK). Without KV vars the app still runs, but on an in-memory
  store that resets between requests — the dashboard says so in a
  footer banner. Don't rely on memory mode for real bot traffic.

## Deploy on Vercel

1. Push this folder to a GitHub repo (or run `vercel` from it).
2. Vercel dashboard → Add New Project → import the repo.
3. Storage → Create Database → **KV** → connect it to the project.
   This adds `KV_REST_API_URL` and `KV_REST_API_TOKEN` to the
   project's env vars automatically.
4. Settings → Environment Variables — set:
   - `BOT_KEYS` — `bot-id:key,...` (one key per bot; bots never hold
     the paid-model key)
   - `BOT_ROLES` — `bot-id:miner|manager|low_brain|master,...`
   - `BOT_NAMES` — `bot-id:@name,...` (rename bots here any time)
   - `DASHBOARD_KEY` — recommended: the dashboard is public on the
     Vercel domain without it
   - `NEWS_FEEDS`, `ENTERTAINMENT_FEEDS` — comma-separated feed URLs
     (defaults already work); `FITNESS_APP_URL` defaults to the
     deployed fitness app
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
`KV_REST_API_TOKEN` as well to test against a real KV store.

## Endpoints

Same as the Railway build: `POST /api/report`, `POST /api/escalate`,
`POST /api/commandeer`, `POST /api/orders/<id>/ack`,
`POST /api/fitness`, `GET /` (dashboard), `GET /api/feed`,
`GET /api/orders`, `GET /api/escalations`, `GET /api/widgets`,
`GET /api/fitness`, `GET /api/bots`, `GET /api/tiers`.
