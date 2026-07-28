from datetime import date

import pytest

from trash_calendar.gcal import SyncPlan
from trash_calendar.guards import GuardError, check_collections, check_plan
from trash_calendar.models import Collection


def some(n):
    return [Collection(date(2026, 8, 1), f"c{i}", "ekonovus") for i in range(n)]


def test_zero_collections_trips_the_guard():
    with pytest.raises(GuardError, match="10-S-000000"):
        check_collections([], "10-S-000000")


def test_a_normal_number_of_collections_passes():
    check_collections(some(19), "10-P-000000")


def test_an_implausible_number_of_collections_trips_the_guard():
    with pytest.raises(GuardError, match="implausible"):
        check_collections(some(201), "10-P-000000")


def test_deleting_most_managed_events_trips_the_guard():
    plan = SyncPlan(
        to_delete=[(f"id{i}", {}) for i in range(6)],
        unchanged=[{} for _ in range(4)],
    )
    with pytest.raises(GuardError, match="force"):
        check_plan(plan)


def test_a_large_delete_is_allowed_with_force():
    plan = SyncPlan(to_delete=[(f"id{i}", {}) for i in range(6)], unchanged=[{}])
    check_plan(plan, force=True)


def test_a_small_delete_passes_without_force():
    plan = SyncPlan(to_delete=[("id0", {})], unchanged=[{} for _ in range(9)])
    check_plan(plan)


def test_an_empty_plan_passes():
    check_plan(SyncPlan())


def test_deleting_everything_on_a_fresh_calendar_is_not_blocked_when_nothing_exists():
    # Creating events on an empty calendar must never trip the delete guard.
    check_plan(SyncPlan(to_create=[{}, {}, {}]))
