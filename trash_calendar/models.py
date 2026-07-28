"""Core value types shared by providers, merging, and calendar sync."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date


class ProviderError(RuntimeError):
    """A provider could not produce usable data."""


class ConfigError(ValueError):
    """Configuration is missing or malformed."""


@dataclass(frozen=True)
class Collection:
    """One scheduled collection of one container."""

    date: date
    container_id: str
    provider: str
    label: str | None = None
    cadence: str | None = None


@dataclass(frozen=True)
class CalendarEvent:
    """One all-day calendar event, possibly covering several containers."""

    date: date
    summary: str
    description: str


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    @classmethod
    def from_months(cls, start: date, months: int) -> DateRange:
        year = start.year + (start.month - 1 + months) // 12
        month = (start.month - 1 + months) % 12 + 1
        day = min(start.day, monthrange(year, month)[1])
        return cls(start, date(year, month, day))

    def contains(self, value: date) -> bool:
        return self.start <= value <= self.end

    def years(self) -> list[int]:
        return list(range(self.start.year, self.end.year + 1))
