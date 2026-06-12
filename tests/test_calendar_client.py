from datetime import date, datetime, time

from booking_pipeline.calendar_client import (
    DemoCalendarClient,
    slot_for,
    within_business_hours,
)


def dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 6, 3, hour, minute)  # arbitrary future Monday


def test_free_slot_is_available() -> None:
    cal = DemoCalendarClient()
    assert cal.is_available(dt(10), dt(11))


def test_daily_busy_block_rejects_overlap() -> None:
    cal = DemoCalendarClient()
    assert not cal.is_available(dt(13), dt(14))       # exact overlap
    assert not cal.is_available(dt(12, 30), dt(13, 30))  # partial overlap
    assert cal.is_available(dt(14), dt(15))           # adjacent is fine
    assert cal.is_available(dt(12), dt(13))           # ends as block starts


def test_created_event_blocks_subsequent_bookings() -> None:
    cal = DemoCalendarClient()
    event_id = cal.create_event("consultation — Client X", dt(10), dt(11), "test")
    assert event_id.startswith("demo-evt-")
    assert not cal.is_available(dt(10, 30), dt(11, 30))
    assert cal.is_available(dt(11), dt(12))


def test_within_business_hours(settings) -> None:
    assert within_business_hours(dt(9), dt(10), settings)
    assert within_business_hours(dt(16), dt(17), settings)
    assert not within_business_hours(dt(8), dt(9), settings)
    assert not within_business_hours(dt(19), dt(20), settings)  # evening request
    assert not within_business_hours(dt(16, 30), dt(17, 30), settings)  # runs past close


def test_slot_for_uses_configured_duration(settings) -> None:
    start, end = slot_for(date(2030, 6, 3), time(10, 0), settings)
    assert start == datetime(2030, 6, 3, 10, 0)
    assert (end - start).total_seconds() == settings.appointment_duration_minutes * 60
