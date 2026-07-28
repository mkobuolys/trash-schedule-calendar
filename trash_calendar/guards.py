"""Sanity checks that fail the run loudly.

The dominant failure mode is silent breakage: a provider changes shape, nothing
is scraped, no events are written, and the reminders quietly stop. Every check
here raises, and the CLI turns that into a non-zero exit so GitHub emails a
failed-workflow notice.
"""

from __future__ import annotations

from trash_calendar.gcal import SyncPlan
from trash_calendar.models import Collection
from trash_calendar.redact import redact

MAX_DATES_PER_CONTAINER = 200


class GuardError(RuntimeError):
    """A sanity check failed; the run must not be treated as successful."""


def check_collections(collections: list[Collection], container_id: str) -> None:
    if not collections:
        raise GuardError(
            f"no collection dates found for container {redact(container_id)!r} within the horizon; "
            "the provider may have changed or the container id may be wrong"
        )
    if len(collections) > MAX_DATES_PER_CONTAINER:
        raise GuardError(
            f"implausible number of dates ({len(collections)}) for container "
            f"{redact(container_id)!r}; expected at most {MAX_DATES_PER_CONTAINER}"
        )


def check_plan(plan: SyncPlan, force: bool = False) -> None:
    if force:
        return
    existing = len(plan.to_delete) + len(plan.to_patch) + len(plan.unchanged)
    if existing and len(plan.to_delete) * 2 > existing:
        raise GuardError(
            f"refusing to delete {len(plan.to_delete)} of {existing} managed events; "
            "re-run with --force if this is intended"
        )
