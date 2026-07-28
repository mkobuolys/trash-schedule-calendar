from datetime import date
from pathlib import Path

import pytest

from trash_calendar.models import DateRange, ProviderError
from trash_calendar.providers.ics import parse_ics

FIXTURE = Path(__file__).parent / "fixtures" / "svara_schedule.ics"
HORIZON = DateRange(date(2026, 7, 28), date(2027, 1, 28))

EXPLICIT = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//
BEGIN:VEVENT
UID:1
DTSTART;VALUE=DATE:20260806
SUMMARY:Misrios komunalines atliekos
END:VEVENT
BEGIN:VEVENT
UID:2
DTSTART;VALUE=DATE:20260813
SUMMARY:Misrios komunalines atliekos
END:VEVENT
BEGIN:VEVENT
UID:3
DTSTART;VALUE=DATE:20270401
SUMMARY:Beyond the horizon
END:VEVENT
END:VCALENDAR
"""

# The real provider ships one VEVENT with an RRULE rather than dated events.
RECURRING = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//
BEGIN:VEVENT
UID:r1
DTSTART;VALUE=DATE:20260805
DTEND;VALUE=DATE:20260806
RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=WE;COUNT=32
SUMMARY:Misrios
END:VEVENT
END:VCALENDAR
"""

RECURRING_WITH_EXDATE = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//
BEGIN:VEVENT
UID:r2
DTSTART;VALUE=DATE:20260805
RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=WE;COUNT=4
EXDATE;VALUE=DATE:20260819
SUMMARY:Misrios
END:VEVENT
END:VCALENDAR
"""


def test_parse_ics_extracts_explicit_all_day_dates_within_the_horizon():
    collections = parse_ics(EXPLICIT, "10-MK-000000", "svara", HORIZON)
    assert [c.date for c in collections] == [date(2026, 8, 6), date(2026, 8, 13)]


def test_parse_ics_expands_a_recurrence_rule():
    # Without RRULE expansion this would yield a single date.
    collections = parse_ics(RECURRING, "10-MK-000000", "svara", HORIZON)
    dates = [c.date for c in collections]
    assert len(dates) > 10, f"expected the fortnightly series, got {dates}"
    assert dates[:4] == [
        date(2026, 8, 5),
        date(2026, 8, 19),
        date(2026, 9, 2),
        date(2026, 9, 16),
    ]
    assert all(d.weekday() == 2 for d in dates), "every occurrence falls on a Wednesday"


def test_parse_ics_clamps_the_recurrence_to_the_horizon():
    collections = parse_ics(
        RECURRING, "10-MK-000000", "svara", DateRange(date(2026, 8, 1), date(2026, 9, 3))
    )
    assert [c.date for c in collections] == [
        date(2026, 8, 5),
        date(2026, 8, 19),
        date(2026, 9, 2),
    ]


def test_parse_ics_honours_exdate():
    collections = parse_ics(RECURRING_WITH_EXDATE, "10-MK-000000", "svara", HORIZON)
    assert date(2026, 8, 19) not in [c.date for c in collections]
    assert date(2026, 8, 5) in [c.date for c in collections]


def test_parse_ics_tags_provider_and_container():
    collections = parse_ics(EXPLICIT, "10-MK-000000", "svara", HORIZON)
    assert {c.container_id for c in collections} == {"10-MK-000000"}
    assert {c.provider for c in collections} == {"svara"}


def test_parse_ics_uses_the_supplied_label_and_cadence():
    collections = parse_ics(
        EXPLICIT, "10-MK-000000", "svara", HORIZON, label="mišrios", cadence="kas 14 dienų"
    )
    assert {c.label for c in collections} == {"mišrios"}
    assert {c.cadence for c in collections} == {"kas 14 dienų"}


def test_parse_ics_deduplicates_repeated_dates():
    twice = EXPLICIT.replace(
        b"END:VCALENDAR",
        b"BEGIN:VEVENT\nUID:dup\nDTSTART;VALUE=DATE:20260806\nSUMMARY:x\nEND:VEVENT\nEND:VCALENDAR",
    )
    collections = parse_ics(twice, "10-MK-000000", "svara", HORIZON)
    assert [c.date for c in collections].count(date(2026, 8, 6)) == 1


def test_parse_ics_returns_dates_sorted():
    collections = parse_ics(RECURRING, "10-MK-000000", "svara", HORIZON)
    assert [c.date for c in collections] == sorted(c.date for c in collections)


def test_parse_ics_rejects_unparseable_input():
    with pytest.raises(ProviderError):
        parse_ics(b"this is not a calendar", "10-MK-000000", "svara", HORIZON)


def test_parse_ics_rejects_a_calendar_with_no_events():
    empty = b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//\nEND:VCALENDAR\n"
    with pytest.raises(ProviderError, match="no events"):
        parse_ics(empty, "10-MK-000000", "svara", HORIZON)


def test_parse_real_downloaded_ics_fixture_expands_the_fortnightly_series():
    collections = parse_ics(FIXTURE.read_bytes(), "10-MK-000000", "svara", HORIZON)
    dates = [c.date for c in collections]
    assert len(dates) >= 12, f"6 months of fortnightly pickups expected, got {dates}"
    assert all(HORIZON.contains(d) for d in dates)
    assert all(d.weekday() == 2 for d in dates)
