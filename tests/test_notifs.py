"""Stage 9d (2026-11-03): more notifications, each with an on/off switch:
weather, money, calendar changes, wind-down, water breaks, releases the day
before, missed reminders. Fakes stand in for Open-Meteo and the calendar."""
import sys, json, os, time
sys.dont_write_bytecode = True
from datetime import datetime, timedelta
mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
os.environ.update(DASHBOARD_KEY="dk", HOME_CITY="St George, UT", GLASS_BUDGETS="Groceries:100",
                  NEWS_FEEDS="http://127.0.0.1:1/x.xml", ENTERTAINMENT_FEEDS="http://127.0.0.1:1/x.json")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
import index as h
PUSH = []
h.notify = lambda title, body, url="/": PUSH.append((title, body, url)) or 1
GETS = []


def fake_get(url, timeout=6):
    GETS.append(url)
    if "geocoding" in url:
        return {"results": [{"name": "St. George", "admin1": "Utah", "country_code": "US", "latitude": 37.1, "longitude": -113.6}]}
    return {"daily": {"temperature_2m_max": [97.4], "temperature_2m_min": [61.2], "precipitation_probability_max": [70]},
            "hourly": {"time": [f"2026-11-03T{h:02d}:00" for h in range(24)],
                       "precipitation_probability": [0] * 15 + [70] + [10] * 8}}


h._get = fake_get


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        sys.exit(1)


tz = h.hub_tz()
day = datetime.now(tz).replace(hour=7, minute=0, second=0, microsecond=0)

# ---- weather
PUSH.clear()
bits = h.weather_tick(day)
check("weather: rain time and heat", bits and "Rain likely around 3 PM (70%)" in bits[0] and "up to 97°" in bits[1])
check("weather: pushed", PUSH and "take a jacket" in PUSH[-1][1])
check("weather: once a day", h.weather_tick(day.replace(hour=8)) is None)
check("weather: city looked up once", sum("geocoding" in u for u in GETS) == 1)
check("weather in the morning brief", "Weather in St. George, Utah: high 97°" in h.morning_digest(day.date())[0])
check("not before WEATHER_TIME", h.weather_tick((day + timedelta(days=1)).replace(hour=6, minute=0)) is None)

# ---- money
PUSH.clear()
h.glass_log_reply((50.0, "groceries", "food"))
check("money: under 80%, quiet", not PUSH)
h.glass_log_reply((35.0, "groceries", "more food"))
check("money: passing 80%", PUSH and "at 85% of its budget" in PUSH[-1][1])
h.glass_log_reply((20.0, "groceries", "snacks"))
check("money: passing 100%", "over budget" in PUSH[-1][1])
PUSH.clear()
h.glass_log_reply((150.0, "electronics", "headphones"))
check("money: a big purchase", PUSH and "Big purchase: $150.00" in PUSH[-1][1])

# ---- calendar changes
h.REMI_CALENDAR_URLS = ["https://cal.example/x.ics"]
h.calendar_problems = lambda: []
s1 = day.replace(hour=15)
EV = [{"title": "Dentist", "location": "", "start": s1, "end": s1 + timedelta(hours=1), "all_day": False, "birthday": False},
      {"title": "Gym", "location": "", "start": day.replace(hour=18), "end": day.replace(hour=19), "all_day": False, "birthday": False}]
h.calendar_events = lambda a, b: list(EV)
PUSH.clear()
check("calendar: the first look only remembers", h.calendar_changes(day) is None and not PUSH)
EV[0] = dict(EV[0], start=day.replace(hour=16), end=day.replace(hour=17))
EV.pop(1)
EV.append({"title": "Call Sam", "location": "", "start": day.replace(hour=20), "end": day.replace(hour=20, minute=30), "all_day": False, "birthday": False})
lines = h.calendar_changes(day)
check("calendar: moved, new, cancelled", any(l.startswith("Moved:") and "Dentist" in l for l in lines)
      and any(l.startswith("New:") and "Call Sam" in l for l in lines) and any(l.startswith("Cancelled:") and "Gym" in l for l in lines))
check("calendar: pushed", PUSH and PUSH[-1][1].startswith("Calendar change:"))
PUSH.clear()
later = day.replace(hour=17, minute=30)  # the dentist ended: not a cancellation
check("calendar: an event that ended isn't cancelled", not h.calendar_changes(later) and not PUSH)
h.calendar_problems = lambda: [1]
check("calendar: a link that didn't load says nothing", h.calendar_changes(later) is None)
h.calendar_problems = lambda: []

# ---- wind-down
PUSH.clear()
check("wind-down: not before its time", h.wind_down(day.replace(hour=20)) is None)
EV[:] = [{"title": "Standup", "location": "", "start": (day + timedelta(days=1)).replace(hour=9), "end": (day + timedelta(days=1)).replace(hour=9, minute=15), "all_day": False, "birthday": False}]
text = h.wind_down(day.replace(hour=21, minute=40))
check("wind-down with tomorrow's first event", text and "Tomorrow starts with Standup at 9 AM" in text)
check("wind-down once a night", h.wind_down(day.replace(hour=22)) is None)

# ---- water
PUSH.clear()
w0 = day.replace(hour=10, minute=5)
check("water: the first of the day waits", h.water_break(w0) is None)
check("water: not before the interval", h.water_break(w0 + timedelta(hours=1)) is None)
check("water: after 2 hours", h.water_break(w0 + timedelta(hours=2, minutes=1)) and PUSH)
check("water: not at night", h.water_break(day.replace(hour=22)) is None)
h.focus_start("20 taxes", (w0 + timedelta(hours=4, minutes=5)).timestamp())
check("water: not during focus", h.water_break(w0 + timedelta(hours=4, minutes=10)) is None)
h.focus_start("stop")

# ---- releases the evening before
tomorrow = (day + timedelta(days=1)).date().isoformat()
h.releases = lambda today=None: [{"title": "Frieren S3", "date": tomorrow, "followed": "Frieren", "kind": "anime", "url": "u"},
                                 {"title": "Random Show", "date": tomorrow, "followed": None, "kind": "tv", "url": "v"}]
PUSH.clear()
got = h.releases_eve(day.replace(hour=19, minute=5))
check("releases: only what you follow, the night before", got == ["Frieren S3"] and "Tomorrow: Frieren S3 comes out." in PUSH[-1][1])

# ---- missed reminders
r = h.add_reminder("today at 9am take vitamins until done", now=day.replace(hour=8))
rs = h.reminders()
for x in rs:
    if x["id"] == r["id"]:
        x.update(pending=True, fired=True)
h._save_reminders(rs)
PUSH.clear()
left = h.missed_reminders(day.replace(hour=20, minute=35))
check("missed: found and pushed", left == ["take vitamins"] and "Move to tomorrow?" in PUSH[-1][1])
card = [m for m in h.store().list_chat(h.ALLCHAT_KEEP) if m["text"].startswith("These didn't get done")][-1]
check("missed: a card with Move to tomorrow", card["buttons"][0]["label"] == "Move to tomorrow")
pid = card["buttons"][0]["id"].split(":")[1]
out = h.apply_proposal(pid, True)
x = next(x for x in h.reminders() if x["id"] == r["id"])
check("missed: moved to tomorrow, same time", out.startswith("✓ Moved") and not x["pending"] and not x["fired"]
      and datetime.fromtimestamp(x["at"], tz).date() == (day + timedelta(days=1)).date()
      and datetime.fromtimestamp(x["at"], tz).hour == 9)

# ---- switches
s, ct, out = h.handle("POST", "/api/settings/notifs", {}, {"x-dashboard-key": "dk"}, json.dumps({"kind": "water", "on": False}).encode())[:3]
check("switch off", s == 200 and not h.notif_on("water"))
h.store().set_meta("notif:water_at", "0")
check("off means quiet", h.water_break(day.replace(hour=15)) is None)
check("unknown kind refused", h.handle("POST", "/api/settings/notifs", {}, {"x-dashboard-key": "dk"},
                                       json.dumps({"kind": "x", "on": True}).encode())[0] == 400)
card = h.notifs_card()
check("Settings card lists all seven", all(f'data-notif="{k}"' in card for k in h.NOTIF_KINDS) and "St George, UT" in card)
check("the tick runs them", isinstance(h.notifs_tick(), dict))
print("done")
