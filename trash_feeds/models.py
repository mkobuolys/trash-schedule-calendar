from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Schedule:
    id: int
    cadence: str | None
    dates: tuple[date, ...]


@dataclass(frozen=True)
class Feed:
    id: str
    provider: str
    label: str | None
    cadence: str | None
    dates: tuple[date, ...]

    @property
    def summary(self) -> str:
        return f"🗑️ Išstumti: {self.label}" if self.label else "🗑️ Išstumti konteinerį"

    @property
    def calendar_name(self) -> str:
        name = f"Šiukšlės: {self.label}" if self.label else "Šiukšlių išvežimas"
        return f"{name} ({self.provider})"
