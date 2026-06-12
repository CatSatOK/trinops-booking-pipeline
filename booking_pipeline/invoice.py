"""PDF invoice generation: Jinja2 template rendered to PDF by WeasyPrint."""

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from booking_pipeline.config import Settings
from booking_pipeline.logging_conf import get_logger
from booking_pipeline.models import Booking

logger = get_logger(__name__)

_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html"]),
)


def render_invoice_html(booking: Booking, settings: Settings) -> str:
    net = settings.service_prices.get(booking.service_type or "", 0.0)
    vat = round(net * settings.vat_rate, 2)
    template = _env.get_template("invoice.html.j2")
    return template.render(
        invoice_number=f"INV-{booking.id:05d}",
        issue_date=date.today().isoformat(),
        company_name=settings.company_name,
        company_email=settings.company_email,
        company_address=settings.company_address,
        client_name=booking.client_name,
        client_email=booking.client_email,
        service_type=booking.service_type,
        service_date=booking.requested_date,
        service_time=booking.requested_time,
        location=booking.location,
        net=f"{net:.2f}",
        vat=f"{vat:.2f}",
        vat_pct=f"{settings.vat_rate * 100:.0f}",
        total=f"{net + vat:.2f}",
    )


def generate_invoice(booking: Booking, settings: Settings) -> str:
    """Render the invoice PDF and return its file path."""
    from weasyprint import HTML  # heavy native deps — imported lazily

    html = render_invoice_html(booking, settings)
    out_dir = Path(settings.invoice_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"INV-{booking.id:05d}.pdf"
    HTML(string=html).write_pdf(str(path))
    logger.info("generated invoice %s for booking %d", path, booking.id)
    return str(path)
