"""Parse a provider-supplied ICS calendar into Collections.

Providers do not necessarily list one event per collection: Svara ships a single
VEVENT carrying an RRULE (e.g. every second Wednesday, 32 times). Recurrences
must therefore be expanded, or all but the first date would be lost.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from dateutil.rrule import rrulestr
from icalendar import Calendar

from trash_calendar.models import Collection, DateRange, ProviderError
from trash_calendar.redact import redact


def parse_ics(
    data: bytes,
    container_id: str,
    provider: str,
    horizon: DateRange,
    label: str | None = None,
    cadence: str | None = None,
) -> list[Collection]:
    try:
        calendar = Calendar.from_ical(data)
    except Exception as exc:  # icalendar raises assorted ValueError subclasses
        raise ProviderError(f"could not parse ICS for {redact(container_id)!r}: {exc}") from exc

    events = list(calendar.walk("VEVENT"))
    if not events:
        raise ProviderError(f"ICS for {redact(container_id)!r} contains no events")

    dates: set[date] = set()
    for event in events:
        start = _as_date(event.get("DTSTART"))
        if start is None:
            continue
        rule = event.get("RRULE")
        if rule is None:
            dates.add(start)
            continue
        dates.update(_expand(event, start, horizon))

    return [
        Collection(
            date=when,
            container_id=container_id,
            provider=provider,
            label=label,
            cadence=cadence,
        )
        for when in sorted(when for when in dates if horizon.contains(when))
    ]


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    raw = getattr(value, "dt", value)
    if isinstance(raw, datetime):
        return raw.date()
    return raw if isinstance(raw, date) else None


def _expand(event: Any, start: date, horizon: DateRange) -> set[date]:
    """Expand an RRULE, minus EXDATEs, bounded by the horizon."""
    rule_text = event["RRULE"].to_ical().decode("utf-8", "replace")
    anchor = datetime(start.year, start.month, start.day)
    try:
        rule = rrulestr(f"RRULE:{rule_text}", dtstart=anchor)
    except (ValueError, TypeError) as exc:
        raise ProviderError(f"could not parse RRULE {rule_text!r}: {exc}") from exc

    # An unbounded rule would iterate forever, so stop at the horizon's end.
    limit = datetime(horizon.end.year, horizon.end.month, horizon.end.day)
    occurrences = {occurrence.date() for occurrence in rule.between(anchor, limit, inc=True)}

    for excluded in _exdates(event):
        occurrences.discard(excluded)
    return occurrences


def _exdates(event: Any) -> set[date]:
    raw = event.get("EXDATE")
    if raw is None:
        return set()
    entries = raw if isinstance(raw, list) else [raw]
    excluded: set[date] = set()
    for entry in entries:
        for item in getattr(entry, "dts", []):
            value = _as_date(item)
            if value is not None:
                excluded.add(value)
    return excluded
