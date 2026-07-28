"""Registry mapping a config ``provider`` name to its implementation.

Adding a provider means adding a module and one entry here.
"""

from __future__ import annotations

from trash_calendar.providers.base import Provider


def get_provider(name: str) -> Provider:
    from trash_calendar.providers.ekonovus import EkonovusProvider
    from trash_calendar.providers.svara import SvaraProvider

    registry: dict[str, Provider] = {
        EkonovusProvider.name: EkonovusProvider(),
        SvaraProvider.name: SvaraProvider(),
    }
    return registry[name]
