"""Decoder for Power BI's compressed DSR result encoding.

Power BI does not return plain rows. It returns a value dictionary plus a
sequence of sparse rows, where a bitmask says which columns repeat the previous
row's value and which are null. See the module tests for the observed shapes.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from trash_calendar.models import ProviderError


def epoch_ms_to_date(value: int) -> date:
    """Convert a Power BI date-only value to a calendar date.

    These values are UTC midnight, so they must be read in UTC. Converting
    through a local timezone would shift the date for zones behind UTC.
    """
    return datetime.fromtimestamp(value / 1000, tz=UTC).date()


def decode_dsr(response: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    """Return (column names, rows) from a querydata response."""
    try:
        data = response["results"][0]["result"]["data"]
        shape = data["dsr"]["DS"][0]
    except (KeyError, IndexError) as exc:
        raise ProviderError(f"unexpected querydata response shape: {exc}") from exc

    if "odata.error" in shape:
        raise ProviderError(shape["odata.error"]["message"]["value"])

    names = [entry["Name"] for entry in data["descriptor"]["Select"]]
    dictionaries = shape.get("ValueDicts", {})

    rows: list[list[Any]] = []
    spec: list[dict[str, Any]] | None = None
    previous: list[Any] = []

    for item in shape.get("PH", [{}])[0].get("DM0", []):
        if "S" in item:
            spec = item["S"]
        if spec is None:
            raise ProviderError("DSR row appeared before its column spec")

        repeats = item.get("R", 0)
        nulls = item.get("Ø", 0)
        present = item.get("C", [])
        cursor = 0
        row: list[Any] = []

        for index, column in enumerate(spec):
            if repeats >> index & 1:
                row.append(previous[index])
                continue
            if nulls >> index & 1:
                row.append(None)
                continue
            try:
                value = present[cursor]
            except IndexError as exc:
                raise ProviderError(
                    f"DSR row is missing a value for column {index} ({column.get('N')})"
                ) from exc
            cursor += 1
            dictionary = column.get("DN")
            if dictionary and isinstance(value, int) and dictionary in dictionaries:
                value = dictionaries[dictionary][value]
            row.append(value)

        previous = row
        rows.append(row)

    return names, rows
