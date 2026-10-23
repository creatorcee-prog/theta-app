# To-do

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
- [ ] Optional, government jobs: developer.usajobs.gov → request an API key
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
- [ ] Get the job boards working: Adzuna, and optionally USAJOBS (setup step 8).
- [ ] Consider moving Mistral (`low_brain`) from Gemini to Haiku. Before
      deciding:
      - Mistral answers every chat message, so Haiku would cost real money
        where Gemini Flash may be free.
      - It would break the rule that Garage Gym questions (`/api/gym/ask`)
        cost no Claude spend, unless those stay on Gemini.
      - The Gemini key wouldn't need a new owner: web search
        (`GEMINI_SEARCH_MODEL`), `/api/gym/ask`'s search and Theta's
        fallback (`manager`) still use it.
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

- [ ] Video and image rippers: grab a page's main image for reference.
      Downloading videos breaks most sites' terms and is too heavy for
      Vercel, so links only for now.

- [ ] Charter's charts in the current color scheme (they're always light now).
- [ ] Quick actions on Home: log an expense, ask Remi, start a round.
- [ ] Open offline: cache the app's pages like Garage Gym does.
- [ ] Rearrange or pin windows on Home.
