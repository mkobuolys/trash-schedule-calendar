"""The one interface every provider implements."""

from __future__ import annotations

from typing import ClassVar, Protocol

from pydantic import BaseModel

from trash_calendar.config import ContainerConfig
from trash_calendar.models import Collection, DateRange


class Provider(Protocol):
    name: ClassVar[str]
    ConfigModel: ClassVar[type[BaseModel]]

    def fetch(self, container: ContainerConfig, horizon: DateRange) -> list[Collection]:
        """Return every scheduled collection for this container within horizon."""
