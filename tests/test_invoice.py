from datetime import date, time
from pathlib import Path

from booking_pipeline.invoice import generate_invoice, render_invoice_html
from booking_pipeline.models import Booking


def make_booking() -> Booking:
    return Booking(
        id=42,
        gmail_thread_id="t-42",
        raw_email_snippet="snippet",
        client_name="Client X",
        client_email="client.x@example.com",
        service_type="consultation",
        requested_date=date(2030, 6, 3),
        requested_time=time(10, 0),
        location="12 Sample Street, Example Town",
    )


def test_render_invoice_html_contains_amounts(settings) -> None:
    html = render_invoice_html(make_booking(), settings)
    assert "INV-00042" in html
    assert "Client X" in html
    net = settings.service_prices["consultation"]
    assert f"{net:.2f}" in html
    assert f"{net * (1 + settings.vat_rate):.2f}" in html  # gross total
    assert settings.company_name in html


def test_generate_invoice_writes_pdf(settings) -> None:
    path = generate_invoice(make_booking(), settings)
    pdf = Path(path)
    assert pdf.exists()
    assert pdf.name == "INV-00042.pdf"
    assert pdf.read_bytes()[:5] == b"%PDF-"


def test_unknown_service_invoices_at_zero(settings) -> None:
    booking = make_booking()
    booking.service_type = "something-unpriced"
    html = render_invoice_html(booking, settings)
    assert "0.00" in html
