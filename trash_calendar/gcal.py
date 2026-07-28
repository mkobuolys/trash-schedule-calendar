"""Idempotent sync of computed events into one dedicated Google Calendar.

Only events carrying the managed marker are ever read, changed or removed, so
anything the user adds to the calendar by hand survives every run.

Authentication is a user OAuth refresh token rather than a service account,
because the Calendar API applies ``reminders.overrides`` to the *requesting
user's* copy of an event. A service account writing to a shared calendar would
set the reminder on its own copy, and the notification would never arrive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from trash_calendar.models import CalendarEvent, DateRange

MANAGED_MARKER = "trash-schedule-calendar"
SCOPES = ["https://www.googleapis.com/auth/calendar"]


class CalendarClient(Protocol):
    def list_events(self, calendar_id: str, time_min: str, time_max: str) -> list[dict]: ...
    def insert_event(self, calendar_id: str, body: dict) -> Any: ...
    def patch_event(self, calendar_id: str, event_id: str, body: dict) -> Any: ...
    def delete_event(self, calendar_id: str, event_id: str) -> Any: ...


@dataclass
class SyncPlan:
    to_create: list[dict] = field(default_factory=list)
    to_patch: list[tuple[str, dict]] = field(default_factory=list)
    to_delete: list[tuple[str, dict]] = field(default_factory=list)
    unchanged: list[dict] = field(default_factory=list)


def event_body(event: CalendarEvent, timezone: str, reminder_minutes: int) -> dict:
    """An all-day event whose reminder fires the previous evening.

    All-day events start at local midnight, so 360 minutes before start is
    18:00 the day before.
    """
    return {
        "summary": event.summary,
        "description": event.description,
        "start": {"date": event.date.isoformat()},
        "end": {"date": (event.date + timedelta(days=1)).isoformat()},
        "transparency": "transparent",
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": reminder_minutes}],
        },
        "extendedProperties": {
            "private": {
                "managedBy": MANAGED_MARKER,
                "collectionDate": event.date.isoformat(),
            }
        },
        "timeZone": timezone,
    }


class CalendarSync:
    def __init__(
        self,
        client: CalendarClient,
        calendar_id: str,
        timezone: str,
        reminder_minutes: int,
    ) -> None:
        self.client = client
        self.calendar_id = calendar_id
        self.timezone = timezone
        self.reminder_minutes = reminder_minutes

    def plan(self, events: list[CalendarEvent], horizon: DateRange) -> SyncPlan:
        existing = self._managed_by_date(horizon)
        desired = {event.date: event for event in events}
        plan = SyncPlan()

        for when, event in sorted(desired.items()):
            body = event_body(event, self.timezone, self.reminder_minutes)
            current = existing.get(when)
            if current is None:
                plan.to_create.append(body)
            elif self._differs(current, body):
                plan.to_patch.append((current["id"], body))
            else:
                plan.unchanged.append(current)

        for when, current in sorted(existing.items()):
            if when not in desired:
                plan.to_delete.append((current["id"], current))

        return plan

    def apply(self, plan: SyncPlan, dry_run: bool = False) -> None:
        if dry_run:
            return
        for body in plan.to_create:
            self.client.insert_event(self.calendar_id, body)
        for event_id, body in plan.to_patch:
            self.client.patch_event(self.calendar_id, event_id, body)
        for event_id, _ in plan.to_delete:
            self.client.delete_event(self.calendar_id, event_id)

    def _managed_by_date(self, horizon: DateRange) -> dict[date, dict]:
        raw = self.client.list_events(
            self.calendar_id,
            f"{horizon.start.isoformat()}T00:00:00Z",
            f"{(horizon.end + timedelta(days=1)).isoformat()}T00:00:00Z",
        )
        managed: dict[date, dict] = {}
        for item in raw:
            private = (item.get("extendedProperties") or {}).get("private") or {}
            if private.get("managedBy") != MANAGED_MARKER:
                continue
            start = (item.get("start") or {}).get("date")
            if not start:
                continue
            try:
                managed[date.fromisoformat(start)] = item
            except ValueError:
                continue
        return managed

    @staticmethod
    def _differs(current: dict, body: dict) -> bool:
        return (
            current.get("summary") != body["summary"]
            or (current.get("description") or "") != body["description"]
        )


class GoogleCalendarClient:
    """Thin adapter over google-api-python-client."""

    def __init__(self, service: Any) -> None:
        self.service = service

    def list_events(self, calendar_id: str, time_min: str, time_max: str) -> list[dict]:
        items: list[dict] = []
        page_token = None
        while True:
            response = (
                self.service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    maxResults=2500,
                    pageToken=page_token,
                    privateExtendedProperty=f"managedBy={MANAGED_MARKER}",
                )
                .execute()
            )
            items.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return items

    def insert_event(self, calendar_id: str, body: dict) -> Any:
        return self.service.events().insert(calendarId=calendar_id, body=body).execute()

    def patch_event(self, calendar_id: str, event_id: str, body: dict) -> Any:
        return (
            self.service.events()
            .patch(calendarId=calendar_id, eventId=event_id, body=body)
            .execute()
        )

    def delete_event(self, calendar_id: str, event_id: str) -> Any:
        return self.service.events().delete(calendarId=calendar_id, eventId=event_id).execute()


def build_google_client(
    client_id: str, client_secret: str, refresh_token: str
) -> GoogleCalendarClient:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    return GoogleCalendarClient(service)
