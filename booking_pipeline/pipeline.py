"""End-to-end booking pipeline.

PENDING ──(slot free)──────────────► CONFIRMED ──► INVOICED
   │
   └─(extraction incomplete /
      outside hours / slot busy)──► ONHOLD ──(staff accept)──► CONFIRMED ──► INVOICED
                                       └────(staff reject)──► REJECTED
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from booking_pipeline.calendar_client import CalendarClient, slot_for, within_business_hours
from booking_pipeline.config import Settings
from booking_pipeline.email_ingestion import EmailSource, IncomingEmail
from booking_pipeline.extractor import extract_fields
from booking_pipeline.invoice import generate_invoice
from booking_pipeline.logging_conf import get_logger
from booking_pipeline.models import Booking, BookingStatus
from booking_pipeline.notifier import Notifier, send_confirmation, send_onhold_ack

logger = get_logger(__name__)


def process_new_emails(
    session: Session,
    settings: Settings,
    source: EmailSource,
    calendar: CalendarClient,
    notifier: Notifier,
) -> list[Booking]:
    """One polling cycle: fetch, extract, and route every new enquiry."""
    processed: list[Booking] = []
    for email in source.fetch_unread():
        existing = session.scalar(select(Booking).where(Booking.gmail_thread_id == email.thread_id))
        if existing is not None:
            source.mark_processed(email.thread_id)
            continue
        booking = _ingest_email(session, email, settings, calendar, notifier)
        source.mark_processed(email.thread_id)
        processed.append(booking)
    if processed:
        logger.info("processed %d new enquiry email(s)", len(processed))
    return processed


def _ingest_email(
    session: Session,
    email: IncomingEmail,
    settings: Settings,
    calendar: CalendarClient,
    notifier: Notifier,
) -> Booking:
    extraction = extract_fields(email, settings)
    booking = Booking(
        gmail_thread_id=email.thread_id,
        raw_email_snippet=email.raw_snippet,
        client_name=extraction.client_name,
        client_email=extraction.client_email,
        service_type=extraction.service_type,
        requested_date=extraction.requested_date,
        requested_time=extraction.requested_time,
        location=extraction.location,
        status=BookingStatus.PENDING,
    )
    session.add(booking)
    session.flush()  # assign id

    if not extraction.complete:
        _put_on_hold(
            booking, f"extraction incomplete — missing: {', '.join(extraction.missing)}",
            notifier, settings,
        )
        return booking

    assert booking.requested_date is not None and booking.requested_time is not None
    start, end = slot_for(booking.requested_date, booking.requested_time, settings)

    if not within_business_hours(start, end, settings):
        _put_on_hold(
            booking,
            f"requested time outside business hours "
            f"({settings.business_start_hour}:00–{settings.business_end_hour}:00)",
            notifier, settings,
        )
        return booking

    if not calendar.is_available(start, end):
        _put_on_hold(booking, "requested slot unavailable in calendar", notifier, settings)
        return booking

    confirm_booking(session, booking, settings, calendar, notifier)
    return booking


def confirm_booking(
    session: Session,
    booking: Booking,
    settings: Settings,
    calendar: CalendarClient,
    notifier: Notifier,
) -> None:
    """CONFIRMED → INVOICED: calendar event, PDF invoice, confirmation email."""
    assert booking.requested_date is not None and booking.requested_time is not None
    start, end = slot_for(booking.requested_date, booking.requested_time, settings)

    booking.calendar_event_id = calendar.create_event(
        summary=f"{booking.service_type} — {booking.client_name}",
        start=start,
        end=end,
        description=f"Booked automatically from email thread {booking.gmail_thread_id}",
    )
    booking.status = BookingStatus.CONFIRMED
    session.flush()

    booking.invoice_path = generate_invoice(booking, settings)
    send_confirmation(booking, notifier, settings)
    booking.status = BookingStatus.INVOICED
    session.flush()
    logger.info("booking %d confirmed and invoiced", booking.id)


def reject_booking(booking: Booking) -> None:
    booking.status = BookingStatus.REJECTED
    logger.info("booking %d rejected by staff", booking.id)


def _put_on_hold(booking: Booking, reason: str, notifier: Notifier, settings: Settings) -> None:
    booking.status = BookingStatus.ONHOLD
    booking.onhold_reason = reason
    logger.info("booking %d ONHOLD: %s", booking.id, reason)
    if booking.client_email:
        send_onhold_ack(booking, notifier, settings)
