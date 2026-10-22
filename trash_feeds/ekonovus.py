"""Every future Ekonovus collection date and every container's schedules."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from trash_feeds.models import Schedule
from trash_feeds.powerbi import Client, Query, column, count, epoch_ms_to_date, equals, not_null

SCHEDULE_DATES = Query(
    entities={"sc": "Schedule", "s": "ScheduleDates"},
    select={
        "schedule": column("sc", "ScheduleId"),
        "cadence": column("sc", "Description"),
        "date": column("s", "Date"),
    },
    where=[equals("s", "Future", "'true'")],
)

# The trailing count is what makes Power BI constrain the join across the three
# tables instead of returning their cross product.
CONTAINER_SCHEDULES = Query(
    entities={"d": "Dumpster", "w": "WasteObject", "ws": "WasteObjectShedules"},
    select={
        "container": column("d", "InventoryNumber"),
        "label": column("w", "Inventorinis nr."),
        "schedule": column("ws", "SheduleID"),
        "n": count("ws", "SheduleID"),
    },
    where=[not_null("d", "InventoryNumber")],
)


@dataclass(frozen=True)
class Container:
    id: str
    waste_type: str | None
    schedule_ids: frozenset[int]


def fetch_schedules(client: Client) -> dict[int, Schedule]:
    cadences: dict[int, str | None] = {}
    dates: dict[int, set] = defaultdict(set)
    for row in client.rows(SCHEDULE_DATES):
        if row["schedule"] is None or row["date"] is None:
            continue
        schedule = int(row["schedule"])
        cadences[schedule] = row["cadence"]
        dates[schedule].add(epoch_ms_to_date(row["date"]))
    return {
        schedule: Schedule(schedule, cadences[schedule], tuple(sorted(found)))
        for schedule, found in dates.items()
    }


def fetch_containers(client: Client) -> list[Container]:
    waste_types: dict[str, str | None] = {}
    schedules: dict[str, set[int]] = defaultdict(set)
    for row in client.rows(CONTAINER_SCHEDULES):
        if row["schedule"] is None:
            continue
        container = row["container"]
        schedules[container].add(int(row["schedule"]))
        waste_types[container] = waste_types.get(container) or waste_type(row["label"])
    return [
        Container(container, waste_types[container], frozenset(ids))
        for container, ids in schedules.items()
    ]


def waste_type(label: str | None) -> str | None:
    """Extract 'Stiklas' from '00-S-00000 (Stiklas)'."""
    match = re.search(r"\(([^)]+)\)\s*$", label or "")
    return match.group(1) if match else None
