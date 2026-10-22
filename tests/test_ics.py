from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from icalendar import Calendar

from trash_feeds.ics import render_feed, render_retired
from trash_feeds.models import Feed

STAMP = datetime(2026, 10, 22, 6, 0, tzinfo=ZoneInfo("Europe/Vilnius"))
SITE = "https://example.github.io/trash"
FEED = Feed(
    id="abc123",
    provider="Ekonovus",
    label="stiklas",
    cadence="kas 14 dienų",
    dates=(date(2026, 10, 29), date(2026, 11, 12)),
)


def test_feed_is_all_day_events_with_an_evening_before_alarm():
    calendar = Calendar.from_ical(render_feed(FEED, SITE, STAMP))

    assert str(calendar["x-wr-calname"]) == "Šiukšlės: stiklas (Ekonovus)"
    events = calendar.walk("VEVENT")
    assert [e.decoded("dtstart") for e in events] == list(FEED.dates)
    assert all(e.decoded("dtend") - e.decoded("dtstart") == timedelta(days=1) for e in events)
    assert str(events[0]["summary"]) == "🗑️ Išstumti: stiklas"
    assert str(events[0]["uid"]) == "abc123-20261029@trash-schedule-calendar"
    assert "kas 14 dienų" in str(events[0]["description"])
    alarm = events[0].walk("VALARM")[0]
    assert alarm.decoded("trigger") == timedelta(hours=-6)


def test_feed_asks_clients_to_refresh_twice_a_day():
    ics = render_feed(FEED, SITE, STAMP)
    assert b"REFRESH-INTERVAL;VALUE=DURATION:PT12H\r\n" in ics
    assert b"X-PUBLISHED-TTL:PT12H\r\n" in ics


def test_feed_output_is_stable_for_the_same_input():
    assert render_feed(FEED, SITE, STAMP) == render_feed(FEED, SITE, STAMP)


def test_retired_feed_tells_subscribers_to_resubscribe():
    calendar = Calendar.from_ical(render_retired("old", SITE, date(2026, 10, 22), STAMP))

    events = calendar.walk("VEVENT")
    assert len(events) == 12
    assert events[0].decoded("dtstart") == date(2026, 10, 22)
    assert SITE in str(events[0]["description"])
    assert "pasikeitė" in str(events[0]["summary"])
