"""Outbound email: booking confirmations and ONHOLD acknowledgements.

OutboxNotifier (DEMO_MODE=true) writes each email as an HTML file into
`data/outbox/` so the demo is fully inspectable without sending anything.
GmailNotifier (DEMO_MODE=false) sends through the Gmail API.
"""

import base64
import re
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Protocol

from jinja2 import Environment, FileSystemLoader, select_autoescape

from booking_pipeline.config import Settings
from booking_pipeline.logging_conf import get_logger
from booking_pipeline.models import Booking

logger = get_logger(__name__)

_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html"]),
)


class Notifier(Protocol):
    def send(self, to: str, subject: str, html_body: str, attachment: str | None = None) -> None: ...


class OutboxNotifier:
    def __init__(self, settings: Settings) -> None:
        self._outbox = Path(settings.outbox_dir)
        self._outbox.mkdir(parents=True, exist_ok=True)

    def send(self, to: str, subject: str, html_body: str, attachment: str | None = None) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        safe_subject = re.sub(r"[^\w-]+", "_", subject)[:60]
        path = self._outbox / f"{stamp}_{safe_subject}.html"
        header = (
            f"<!-- To: {to} -->\n<!-- Subject: {subject} -->\n"
            f"<!-- Attachment: {attachment or 'none'} -->\n"
        )
        path.write_text(header + html_body, encoding="utf-8")
        logger.info("outbox: wrote %s (to=%s)", path.name, to)


class GmailNotifier:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service = None

    def _client(self):
        if self._service is None:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials.from_authorized_user_file(
                self._settings.google_token_file,
                scopes=["https://www.googleapis.com/auth/gmail.send"],
            )
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def send(self, to: str, subject: str, html_body: str, attachment: str | None = None) -> None:
        msg = MIMEMultipart()
        msg["to"] = to
        msg["from"] = self._settings.company_email
        msg["subject"] = subject
        msg.attach(MIMEText(html_body, "html"))
        if attachment:
            from email.mime.application import MIMEApplication

            data = Path(attachment).read_bytes()
            part = MIMEApplication(data, _subtype="pdf")
            part.add_header("Content-Disposition", "attachment", filename=Path(attachment).name)
            msg.attach(part)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        self._client().users().messages().send(userId="me", body={"raw": raw}).execute()
        logger.info("gmail: sent %r to %s", subject, to)


def send_confirmation(booking: Booking, notifier: Notifier, settings: Settings) -> None:
    template = _env.get_template("confirmation_email.html.j2")
    html = template.render(
        company_name=settings.company_name,
        company_email=settings.company_email,
        client_name=booking.client_name,
        service_type=booking.service_type,
        service_date=booking.requested_date,
        service_time=booking.requested_time,
        location=booking.location,
    )
    notifier.send(
        to=booking.client_email or "",
        subject=f"Booking confirmed — {booking.service_type} on {booking.requested_date}",
        html_body=html,
        attachment=booking.invoice_path,
    )


def send_onhold_ack(booking: Booking, notifier: Notifier, settings: Settings) -> None:
    template = _env.get_template("onhold_email.html.j2")
    html = template.render(
        company_name=settings.company_name,
        company_email=settings.company_email,
        client_name=booking.client_name or "there",
    )
    notifier.send(
        to=booking.client_email or "",
        subject="We received your booking request",
        html_body=html,
    )


def get_notifier(settings: Settings) -> Notifier:
    return OutboxNotifier(settings) if settings.demo_mode else GmailNotifier(settings)
