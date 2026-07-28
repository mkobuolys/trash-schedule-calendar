from datetime import date

from trash_calendar.gcal import MANAGED_MARKER, CalendarSync, event_body
from trash_calendar.models import CalendarEvent, DateRange

HORIZON = DateRange(date(2026, 7, 28), date(2027, 1, 28))
TZ = "Europe/Vilnius"


def evt(day, summary="🗑️ Išstumti: stiklas", description="10-S-000000"):
    return CalendarEvent(date(2026, 8, day), summary, description)


class FakeClient:
    def __init__(self, existing=None):
        self.existing = list(existing or [])
        self.inserted, self.patched, self.deleted = [], [], []

    def list_events(self, calendar_id, time_min, time_max):
        return list(self.existing)

    def insert_event(self, calendar_id, body):
        self.inserted.append(body)

    def patch_event(self, calendar_id, event_id, body):
        self.patched.append((event_id, body))

    def delete_event(self, calendar_id, event_id):
        self.deleted.append(event_id)


def managed(day, summary="🗑️ Išstumti: stiklas", description="10-S-000000", event_id=None):
    return {
        "id": event_id or f"id-{day}",
        "summary": summary,
        "description": description,
        "start": {"date": f"2026-08-{day:02d}"},
        "extendedProperties": {"private": {"managedBy": MANAGED_MARKER}},
    }


def sync(client):
    return CalendarSync(client, "cal-1", TZ, 360)


def test_event_body_is_all_day_in_the_configured_timezone():
    body = event_body(evt(6), TZ, 360)
    assert body["start"] == {"date": "2026-08-06"}
    assert body["end"] == {"date": "2026-08-07"}  # exclusive end
    assert body.get("start", {}).get("dateTime") is None


def test_event_body_sets_the_evening_before_reminder():
    body = event_body(evt(6), TZ, 360)
    assert body["reminders"]["useDefault"] is False
    assert body["reminders"]["overrides"] == [{"method": "popup", "minutes": 360}]


def test_event_body_marks_the_event_as_managed():
    body = event_body(evt(6), TZ, 360)
    assert body["extendedProperties"]["private"]["managedBy"] == MANAGED_MARKER
    assert body["extendedProperties"]["private"]["collectionDate"] == "2026-08-06"


def test_plan_creates_missing_events():
    plan = sync(FakeClient()).plan([evt(6), evt(27)], HORIZON)
    assert len(plan.to_create) == 2
    assert not plan.to_patch and not plan.to_delete


def test_plan_leaves_identical_events_untouched():
    plan = sync(FakeClient([managed(6)])).plan([evt(6)], HORIZON)
    assert not plan.to_create and not plan.to_patch and not plan.to_delete
    assert len(plan.unchanged) == 1


def test_plan_patches_an_event_whose_summary_changed():
    existing = managed(6, summary="🗑️ Išstumti: stiklas")
    plan = sync(FakeClient([existing])).plan(
        [evt(6, summary="🗑️ Išstumti: stiklas + pakuotės")], HORIZON
    )
    assert len(plan.to_patch) == 1
    assert not plan.to_create and not plan.to_delete


def test_plan_patches_an_event_whose_description_changed():
    plan = sync(FakeClient([managed(6, description="old")])).plan(
        [evt(6, description="10-S-000000 (stiklas) — ekonovus")], HORIZON
    )
    assert len(plan.to_patch) == 1


def test_plan_deletes_managed_events_whose_date_disappeared():
    plan = sync(FakeClient([managed(6), managed(13)])).plan([evt(6)], HORIZON)
    assert [event_id for event_id, _ in plan.to_delete] == ["id-13"]


def test_plan_never_touches_events_without_the_managed_marker():
    handmade = {
        "id": "mine",
        "summary": "Dentist",
        "start": {"date": "2026-08-13"},
    }
    plan = sync(FakeClient([handmade])).plan([evt(6)], HORIZON)
    assert plan.to_delete == []
    assert "mine" not in [body.get("id") for body in plan.to_create]


def test_apply_performs_the_planned_operations():
    client = FakeClient([managed(13)])
    syncer = sync(client)
    syncer.apply(syncer.plan([evt(6)], HORIZON))
    assert len(client.inserted) == 1
    assert client.deleted == ["id-13"]


def test_apply_does_nothing_when_dry_run():
    client = FakeClient([managed(13)])
    syncer = sync(client)
    plan = syncer.plan([evt(6)], HORIZON)
    syncer.apply(plan, dry_run=True)
    assert client.inserted == [] and client.deleted == []


def test_plan_ignores_managed_events_with_no_start_date():
    broken = {
        "id": "weird",
        "summary": "x",
        "start": {},
        "extendedProperties": {"private": {"managedBy": MANAGED_MARKER}},
    }
    plan = sync(FakeClient([broken])).plan([evt(6)], HORIZON)
    assert plan.to_delete == []


def test_running_twice_is_idempotent():
    client = FakeClient()
    syncer = sync(client)
    syncer.apply(syncer.plan([evt(6), evt(27)], HORIZON))
    # Feed the created bodies back as if they were now on the calendar.
    client.existing = [{**body, "id": f"created-{i}"} for i, body in enumerate(client.inserted)]
    client.inserted = []
    second = syncer.plan([evt(6), evt(27)], HORIZON)
    assert not second.to_create and not second.to_patch and not second.to_delete
    assert len(second.unchanged) == 2
