"""Booking endpoints: list, accept (with optional field corrections), reject."""

from collections.abc import Iterator
from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from booking_pipeline.calendar_client import get_calendar_client, slot_for, within_business_hours
from booking_pipeline.config import get_settings
from booking_pipeline.database import session_scope
from booking_pipeline.models import Booking, BookingStatus
from booking_pipeline.notifier import get_notifier
from booking_pipeline.pipeline import confirm_booking, reject_booking

router = APIRouter(prefix="/bookings", tags=["bookings"])


def db_session() -> Iterator[Session]:
    with session_scope() as session:
        yield session


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gmail_thread_id: str
    raw_email_snippet: str
    client_name: str | None
    client_email: str | None
    service_type: str | None
    requested_date: date | None
    requested_time: time | None
    location: str | None
    status: BookingStatus
    onhold_reason: str | None
    calendar_event_id: str | None
    invoice_path: str | None


class AcceptPayload(BaseModel):
    """Optional corrections staff can apply before accepting an ONHOLD booking."""

    client_name: str | None = None
    client_email: str | None = None
    service_type: str | None = None
    requested_date: date | None = None
    requested_time: time | None = None
    location: str | None = None


@router.get("", response_model=list[BookingOut])
def list_bookings(
    status: BookingStatus | None = None,
    session: Session = Depends(db_session),
) -> list[Booking]:
    stmt = select(Booking).order_by(Booking.created_at.desc())
    if status is not None:
        stmt = stmt.where(Booking.status == status)
    return list(session.scalars(stmt))


@router.patch("/{booking_id}/accept", response_model=BookingOut)
def accept_booking(
    booking_id: int,
    payload: AcceptPayload | None = None,
    session: Session = Depends(db_session),
) -> Booking:
    booking = _get_onhold(session, booking_id)
    settings = get_settings()

    if payload is not None:
        for field_name, value in payload.model_dump(exclude_none=True).items():
            setattr(booking, field_name, value)

    missing = [
        f for f in ("client_name", "service_type", "requested_date", "requested_time")
        if getattr(booking, f) is None
    ]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"cannot accept: missing fields {', '.join(missing)} — supply them in the request body",
        )

    calendar = get_calendar_client(settings)
    start, end = slot_for(booking.requested_date, booking.requested_time, settings)
    if not within_business_hours(start, end, settings):
        raise HTTPException(status_code=409, detail="requested time is outside business hours")
    if not calendar.is_available(start, end):
        raise HTTPException(status_code=409, detail="requested slot is still unavailable")

    confirm_booking(session, booking, settings, calendar, get_notifier(settings))
    return booking


@router.patch("/{booking_id}/reject", response_model=BookingOut)
def reject_booking_endpoint(
    booking_id: int,
    session: Session = Depends(db_session),
) -> Booking:
    booking = _get_onhold(session, booking_id)
    reject_booking(booking)
    return booking


def _get_onhold(session: Session, booking_id: int) -> Booking:
    booking = session.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="booking not found")
    if booking.status != BookingStatus.ONHOLD:
        raise HTTPException(
            status_code=409, detail=f"booking is {booking.status}, only ONHOLD bookings can be reviewed"
        )
    return booking
