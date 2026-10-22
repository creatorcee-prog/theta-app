# To-do

## Setup checklist

**Settings → Wiring** shows which of these are working. All keys go in
Vercel → Settings → Environment Variables, marked **Sensitive**, then
**Redeploy** (new values only reach new deployments).

### 1. Merge and redeploy
- [ ] Merge the open pull request, then wait for (or trigger) the Vercel
      production deploy.

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
      where "here" is.
- [ ] Free Adzuna key: developer.adzuna.com → register → `ADZUNA_APP_ID`
      and `ADZUNA_APP_KEY` (`ADZUNA_COUNTRY` if not `us`).
- [ ] Optional, government jobs: developer.usajobs.gov → request an API key
      → `USAJOBS_API_KEY` and `USAJOBS_EMAIL` (the email you used).

### 9. Voices
- [ ] Settings → Voices → **Sound check**, and send me what it shows if
      you hear nothing.

## Planned

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

- [ ] Charter's charts in the current color scheme (they're always light now).
- [ ] Quick actions on Home: log an expense, ask Remi, start a round.
- [ ] Open offline: cache the app's pages like Garage Gym does.
- [ ] Rearrange or pin windows on Home.
