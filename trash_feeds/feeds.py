"""Group containers into shared feeds and build the container lookup."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta

from trash_feeds.ekonovus import Container
from trash_feeds.models import Feed, Schedule

WASTE_TYPE_LABELS = {
    "Stiklas": "stiklas",
    "Pakuotė": "pakuotės",
    "Komunalinės": "mišrios komunalinės",
    "Žaliosios": "žaliosios atliekos",
    "Plastikas": "plastikas",
    "Popierius": "popierius",
}

# About a third of containers carry no waste type, only the inventory-code
# convention in the middle segment of their number.
CODE_LABELS = {
    "S": "stiklas",
    "P": "pakuotės",
    "L": "mišrios komunalinės",
    "MK": "mišrios komunalinės",
    "Ž": "žaliosios atliekos",
}

REFERENCE_MONDAY = date(2024, 1, 1)
SVARA_CADENCES = {
    1: "kas savaitę",
    2: "kas 2 savaites",
    3: "kas 3 savaites",
    4: "kas 4 savaites",
}


def normalize_id(raw: str) -> str:
    """Must stay identical to ``normalizeId`` in site/logic.js."""
    text = unicodedata.normalize("NFC", raw)
    text = re.sub(r"\s+", "", text)
    text = re.sub("[‐-―−]", "-", text)
    return text.upper()


def shard_of(normalized_id: str) -> str:
    """Must stay identical to ``shardOf`` in site/logic.js."""
    return hashlib.sha256(normalized_id.encode()).hexdigest()[:2]


def resolve_label(container: Container) -> str | None:
    if container.waste_type in WASTE_TYPE_LABELS:
        return WASTE_TYPE_LABELS[container.waste_type]
    parts = container.id.split("-")
    if len(parts) >= 3:
        return CODE_LABELS.get(parts[1].upper())
    return None


def feed_id(label: str | None, schedule_ids: frozenset[int]) -> str:
    key = f"{label or ''}|{','.join(str(s) for s in sorted(schedule_ids))}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def build_ekonovus(
    containers: list[Container],
    schedules: dict[int, Schedule],
    start: date,
    end: date,
) -> tuple[list[Feed], dict[str, str]]:
    """Return one feed per (label, schedule set) and a container → feed id lookup.

    Containers whose schedules have no future dates are left out of both.
    """
    groups: dict[tuple[str | None, frozenset[int]], list[str]] = defaultdict(list)
    for container in containers:
        active = frozenset(s for s in container.schedule_ids if s in schedules)
        if active:
            groups[(resolve_label(container), active)].append(container.id)

    feeds: list[Feed] = []
    lookup: dict[str, str] = {}
    for (label, schedule_ids), members in groups.items():
        ordered = [schedules[s] for s in sorted(schedule_ids)]
        dates = sorted({d for s in ordered for d in s.dates if start <= d < end})
        cadences = list(dict.fromkeys(s.cadence for s in ordered if s.cadence))
        feed = Feed(
            id=feed_id(label, schedule_ids),
            provider="Ekonovus",
            label=label,
            cadence=" + ".join(cadences) or None,
            dates=tuple(dates),
        )
        feeds.append(feed)
        for member in members:
            lookup[normalize_id(member)] = feed.id
    return sorted(feeds, key=lambda f: f.id), lookup


def svara_feed_id(interval: int, weekday: int, phase: int) -> str:
    return f"svara-{interval}w-d{weekday}-p{phase}"


def svara_pattern_of(day: date, interval: int) -> str:
    """Must stay identical to ``svaraFeedId`` in site/logic.js."""
    days = (day - REFERENCE_MONDAY).days
    return svara_feed_id(interval, day.weekday(), (days // 7) % interval)


def build_svara(start: date, end: date) -> list[Feed]:
    """One feed for every fixed weekly recurrence a user can describe.

    Svara blocks automated access, so the user states their recurrence instead:
    every ``interval`` weeks on ``weekday``, in week ``phase`` of the cycle.
    """
    feeds = []
    for interval, cadence in SVARA_CADENCES.items():
        for weekday in range(7):
            for phase in range(interval):
                first = REFERENCE_MONDAY + timedelta(weeks=phase, days=weekday)
                step = timedelta(weeks=interval)
                if first < start:
                    first += step * -(-(start - first).days // step.days)
                dates = []
                while first < end:
                    dates.append(first)
                    first += step
                feeds.append(
                    Feed(
                        id=svara_feed_id(interval, weekday, phase),
                        provider="Svara",
                        label="mišrios komunalinės",
                        cadence=cadence,
                        dates=tuple(dates),
                    )
                )
    return feeds
