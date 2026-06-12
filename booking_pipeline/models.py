"""SQLAlchemy 2.0 models."""

import enum
from datetime import date, datetime, time, timezone

from sqlalchemy import Date, DateTime, Enum, String, Text, Time
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class BookingStatus(enum.StrEnum):
    PENDING = "PENDING"        # ingested, not yet processed
    ONHOLD = "ONHOLD"          # needs staff review (extraction failed / slot busy)
    CONFIRMED = "CONFIRMED"    # calendar event created
    INVOICED = "INVOICED"      # invoice generated and confirmation sent
    REJECTED = "REJECTED"      # staff rejected from the review queue


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    gmail_thread_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    raw_email_snippet: Mapped[str] = mapped_column(Text)

    # Extracted fields — nullable because extraction can partially fail
    client_name: Mapped[str | None] = mapped_column(String(200))
    client_email: Mapped[str | None] = mapped_column(String(200))
    service_type: Mapped[str | None] = mapped_column(String(100))
    requested_date: Mapped[date | None] = mapped_column(Date)
    requested_time: Mapped[time | None] = mapped_column(Time)
    location: Mapped[str | None] = mapped_column(String(300))

    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, native_enum=False, length=20),
        default=BookingStatus.PENDING,
        index=True,
    )
    onhold_reason: Mapped[str | None] = mapped_column(String(300))

    calendar_event_id: Mapped[str | None] = mapped_column(String(128))
    invoice_path: Mapped[str | None] = mapped_column(String(500))
    invoiced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:
        return f"<Booking {self.id} {self.client_name!r} {self.status}>"
