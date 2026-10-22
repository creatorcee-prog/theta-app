# To-do

The dashboard's **Wiring** panel shows which of these are done.

## Needs a computer

- [ ] **Remi's calendar.** Google Calendar on a computer (the phone app
      can't do this): Settings → your calendar → **Integrate calendar** →
      copy **Secret address in iCal format**. In Vercel, set
      `REMI_CALENDAR_URLS` to it (comma-separate several calendars) and
      redeploy. Treat the address like a password.
- [ ] **Rocket Money export.** Rocket Money only lets you download the CSV
      on a computer: Transactions → Export, open the emailed link, then
      upload the file on the dashboard's **Budget** card.

## Setup (phone is fine)

- [ ] `CRON_SECRET` in Vercel, then run `supabase/cron.sql.example` in the
      Supabase SQL editor (easier on a computer, works in a phone browser).
- [ ] `TMDB_API_KEY` for Lenz (themoviedb.org → Settings → API).
- [ ] `GLASS_BUDGETS`, e.g. `Groceries:600,Dining:200`; optionally
      `GLASS_CATEGORY_MAP` to match Rocket Money's category names.
- [ ] `BIRTHDAYS`, e.g. `Sam:03-14,Grandma:11-02`.
- [ ] Phone notifications: open `/api/push/new-keys` (signed in), put both
      keys in Vercel, redeploy, delete and re-add the Home Screen app, open
      it from the Home Screen, tap **Turn on**, then **Send a test**.

## Planned

- [ ] Intuitive UI.
- [ ] Scriptable widgets: Home Screen and Lock Screen.
- [ ] Discord: webhook mirror, then slash commands, then Remi's
      auto-moderation (needs an always-on host, not Vercel).
- [ ] Paid model for Theta.
