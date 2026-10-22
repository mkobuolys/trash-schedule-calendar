from __future__ import annotations

from datetime import date, datetime, timedelta

from icalendar import Alarm, Calendar, Event, vDuration

from trash_feeds.models import Feed

PRODID = "-//trash-schedule-calendar//LT"
UID_DOMAIN = "trash-schedule-calendar"
# Midnight minus six hours: 18:00 the evening before the all-day event.
REMINDER = timedelta(hours=-6)
REFRESH = timedelta(hours=12)
RETIRED_NOTICE_WEEKS = 12


def _calendar(name: str) -> Calendar:
    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", name)
    calendar.add("x-wr-timezone", "Europe/Vilnius")
    calendar.add("refresh-interval", REFRESH, parameters={"VALUE": "DURATION"})
    calendar.add("x-published-ttl", vDuration(REFRESH))
    return calendar


def _event(uid: str, day: date, summary: str, description: str, stamp: datetime) -> Event:
    event = Event()
    event.add("uid", uid)
    event.add("dtstamp", stamp)
    event.add("dtstart", day)
    event.add("dtend", day + timedelta(days=1))
    event.add("summary", summary)
    event.add("description", description)
    event.add("transp", "TRANSPARENT")
    alarm = Alarm()
    alarm.add("action", "DISPLAY")
    alarm.add("description", summary)
    alarm.add("trigger", REMINDER)
    event.add_component(alarm)
    return event


def render_feed(feed: Feed, site_url: str, stamp: datetime) -> bytes:
    calendar = _calendar(feed.calendar_name)
    details = " · ".join(part for part in (feed.provider, feed.cadence) if part)
    description = f"{details}\n\nGrafikas atnaujinamas kasdien: {site_url}"
    for day in feed.dates:
        uid = f"{feed.id}-{day:%Y%m%d}@{UID_DOMAIN}"
        calendar.add_component(_event(uid, day, feed.summary, description, stamp))
    return calendar.to_ical()


def render_retired(feed_id: str, site_url: str, today: date, stamp: datetime) -> bytes:
    """A feed whose schedule no longer exists, kept so subscribers find out."""
    calendar = _calendar("Šiukšlės: grafikas pasikeitė")
    summary = "⚠️ Šiukšlių grafikas pasikeitė"
    description = (
        "Šis kalendorius nebeatnaujinamas, nes jūsų konteinerio grafikas pasikeitė. "
        f"Ištrinkite šį kalendorių ir pridėkite naują: {site_url}"
    )
    for week in range(RETIRED_NOTICE_WEEKS):
        day = today + timedelta(weeks=week)
        uid = f"{feed_id}-retired-{day:%Y%m%d}@{UID_DOMAIN}"
        calendar.add_component(_event(uid, day, summary, description, stamp))
    return calendar.to_ical()
