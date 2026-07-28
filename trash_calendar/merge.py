"""Group collections by date into one all-day event per collection day."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from trash_calendar.labels import resolve_label
from trash_calendar.models import CalendarEvent, Collection

SUMMARY_PREFIX = "🗑️ Išstumti"


def merge(collections: list[Collection]) -> list[CalendarEvent]:
    by_date: dict[date, list[Collection]] = defaultdict(list)
    for collection in collections:
        by_date[collection.date].append(collection)

    events: list[CalendarEvent] = []
    for when in sorted(by_date):
        # Sort by container id so the summary is stable regardless of fetch order.
        same_day = sorted(set(by_date[when]), key=lambda c: c.container_id)
        labels: list[str] = []
        lines: list[str] = []
        for collection in same_day:
            label = resolve_label(collection)
            if label not in labels:
                labels.append(label)
            # Full container id on purpose: the description lands on the user's
            # own calendar, not in a log, and it is what they need when
            # contacting the operator. Logs use trash_calendar.redact instead.
            detail = f"{collection.container_id} ({label}) — {collection.provider}"
            if collection.cadence:
                detail += f", {collection.cadence}"
            lines.append(detail)
        events.append(
            CalendarEvent(
                date=when,
                summary=f"{SUMMARY_PREFIX}: {' + '.join(labels)}",
                description="\n".join(lines),
            )
        )
    return events
