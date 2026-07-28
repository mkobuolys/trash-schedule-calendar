"""Resolve a human waste-type label for a container.

Order: explicit config, then what the provider reported, then the Lithuanian
inventory-code convention, then the raw id.
"""

from __future__ import annotations

from trash_calendar.models import Collection

CODE_LABELS = {
    "S": "stiklas",
    "P": "pakuotės",
    "MK": "mišrios komunalinės",
}


def resolve_label(collection: Collection, configured: str | None = None) -> str:
    if configured:
        return configured
    if collection.label:
        return collection.label
    parts = collection.container_id.split("-")
    if len(parts) >= 3 and parts[1].upper() in CODE_LABELS:
        return CODE_LABELS[parts[1].upper()]
    return collection.container_id
