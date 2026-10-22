# To-do

**Settings → Wiring** shows which of these are done.

## Needs a computer

- [ ] **Remi's calendar.** Google Calendar on a computer (the phone app
      can't do this): Settings → your calendar → **Integrate calendar** →
      copy **Secret address in iCal format**. In Vercel, set
      `REMI_CALENDAR_URLS` to it (comma-separate several calendars) and
      redeploy. Treat the address like a password.
- [ ] **Rocket Money export.** Rocket Money only lets you download the CSV
      on a computer: Transactions → Export, open the emailed link, then
      upload the file on the **Money** tab.

## Setup (phone is fine)

- [ ] `CRON_SECRET` in Vercel, then run `supabase/cron.sql.example` in the
      Supabase SQL editor (easier on a computer, works in a phone browser).
- [ ] `TMDB_API_KEY` for Lenz (themoviedb.org → Settings → API).
- [ ] `GLASS_BUDGETS`, e.g. `Groceries:600,Dining:200`; optionally
      `GLASS_CATEGORY_MAP` to match Rocket Money's category names.
- [ ] `BIRTHDAYS`, e.g. `Sam:03-14,Grandma:11-02`.
- [ ] Run the `bot-hub-tick` job from `supabase/cron.sql.example` (Remi's
      reminders check every 5 minutes).
- [ ] `LENZ_DOC_URL` (your entertainment log), `MAL_CLIENT_ID` and
      `MAL_USERNAME` for Lenz; `GITHUB_TOKEN` for QWERTY's `/issue`.
- [ ] Settings → Face ID sign-in → Add this device, then re-add the Home
      Screen icon without `?key=` in it.

## Planned

- [ ] Scriptable widgets: Home Screen and Lock Screen. Build on a JSON
      version of the Home windows (`/api/windows`), so the widget shows
      the same short titles and pictures.
- [ ] Discord: webhook mirror, then slash commands, then Remi's
      auto-moderation (needs an always-on host, not Vercel).
- [ ] Paid model for Theta.
- [ ] Gmail for Remi: list threads you haven't answered, sort senders into
      family / friends / work / other (you confirm each new sender once),
      and draft replies for the unimportant ones for you to approve. Needs
      a Google Cloud OAuth client (set up on a computer).
- [ ] Sending on your behalf: email via Gmail drafts first; SMS via Twilio
      only if worth the 10DLC registration and per-text fees; iMessage only
      through an iPhone Shortcut you run.
- [ ] Lenz writes ratings and status back to MyAnimeList (needs MAL's
      sign-in flow, not just the client ID).

## Ideas (not built yet)

- [ ] Charter's charts in the current color scheme (they're always light now).
- [ ] Quick actions on Home: log an expense, ask Remi, start a round.
- [ ] Open offline: cache the app's pages like Garage Gym does.
- [ ] Rearrange or pin windows on Home.
