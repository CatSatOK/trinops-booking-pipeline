"""Calendar availability + event creation.

DemoCalendarClient (DEMO_MODE=true) simulates a calendar with a recurring
busy block from 13:00–14:00 every day, so the "slot unavailable → ONHOLD"
path can be demonstrated deterministically with seed data.
"""

import itertools
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Protocol

from booking_pipeline.config import Settings
from booking_pipeline.logging_conf import get_logger

logger = get_logger(__name__)


class CalendarClient(Protocol):
    def is_available(self, start: datetime, end: datetime) -> bool: ...
    def create_event(self, summary: str, start: datetime, end: datetime, description: str) -> str: ...


@dataclass
class DemoCalendarClient:
    """In-memory calendar. Busy daily between `busy_start` and `busy_end`."""

    busy_start: time = time(13, 0)
    busy_end: time = time(14, 0)
    events: dict[str, tuple[datetime, datetime, str]] = field(default_factory=dict)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    def is_available(self, start: datetime, end: datetime) -> bool:
        day_busy_start = datetime.combine(start.date(), self.busy_start)
        day_busy_end = datetime.combine(start.date(), self.busy_end)
        if start < day_busy_end and end > day_busy_start:
            logger.info("slot %s–%s overlaps daily busy block", start, end)
            return False
        for event_id, (ev_start, ev_end, _) in self.events.items():
            if start < ev_end and end > ev_start:
                logger.info("slot %s–%s overlaps existing event %s", start, end, event_id)
                return False
        return True

    def create_event(self, summary: str, start: datetime, end: datetime, description: str) -> str:
        event_id = f"demo-evt-{next(self._ids)}"
        self.events[event_id] = (start, end, summary)
        logger.info("created demo event %s: %s (%s–%s)", event_id, summary, start, end)
        return event_id


class GoogleCalendarClient:
    """Real Google Calendar client (DEMO_MODE=false)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service = None

    def _client(self):
        if self._service is None:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials.from_authorized_user_file(
                self._settings.google_token_file,
                scopes=["https://www.googleapis.com/auth/calendar"],
            )
            self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def is_available(self, start: datetime, end: datetime) -> bool:
        body = {
            "timeMin": start.isoformat() + "Z",
            "timeMax": end.isoformat() + "Z",
            "items": [{"id": self._settings.google_calendar_id}],
        }
        resp = self._client().freebusy().query(body=body).execute()
        busy = resp["calendars"][self._settings.google_calendar_id]["busy"]
        return len(busy) == 0

    def create_event(self, summary: str, start: datetime, end: datetime, description: str) -> str:
        event = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
        }
        created = (
            self._client()
            .events()
            .insert(calendarId=self._settings.google_calendar_id, body=event)
            .execute()
        )
        logger.info("created calendar event %s", created["id"])
        return created["id"]


def within_business_hours(start: datetime, end: datetime, settings: Settings) -> bool:
    open_t = time(settings.business_start_hour, 0)
    close_t = time(settings.business_end_hour, 0)
    return start.time() >= open_t and (end.time() <= close_t or end.time() == time(0, 0))


def slot_for(booking_date, booking_time, settings: Settings) -> tuple[datetime, datetime]:
    start = datetime.combine(booking_date, booking_time)
    return start, start + timedelta(minutes=settings.appointment_duration_minutes)


_demo_singleton: DemoCalendarClient | None = None


def get_calendar_client(settings: Settings) -> CalendarClient:
    global _demo_singleton
    if settings.demo_mode:
        if _demo_singleton is None:
            _demo_singleton = DemoCalendarClient()
        return _demo_singleton
    return GoogleCalendarClient(settings)
