"""Application settings.

Every company-specific or environment-specific value lives in `.env`
(see `.env.example`). Nothing client-identifying is hardcoded.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    demo_mode: bool = True

    database_url: str = "sqlite:///./data/bookings.db"

    poll_interval_minutes: int = 10

    anthropic_api_key: str = ""
    claude_model: str = "claude-haiku-4-5-20251001"

    google_credentials_file: str = "credentials.json"
    google_token_file: str = "token.json"
    google_calendar_id: str = "primary"
    gmail_query: str = "is:unread label:bookings"

    company_name: str = "Company A"
    company_email: str = "bookings@example.com"
    company_address: str = "1 Example Street, Example Town, EX1 2MP"
    vat_rate: float = 0.20

    business_start_hour: int = 9
    business_end_hour: int = 17
    appointment_duration_minutes: int = 60

    invoice_dir: str = "data/invoices"
    outbox_dir: str = "data/outbox"
    seed_emails_file: str = "seed/emails.json"

    # Net price per service type, used on invoices. Override with a JSON
    # object in the env var SERVICE_PRICES, e.g. {"consultation": 150}
    service_prices: dict[str, float] = {
        "consultation": 120.0,
        "installation": 350.0,
        "maintenance": 180.0,
        "inspection": 95.0,
    }

    def ensure_dirs(self) -> None:
        for d in (self.invoice_dir, self.outbox_dir):
            Path(d).mkdir(parents=True, exist_ok=True)
        db_path = self.database_url.removeprefix("sqlite:///")
        if db_path != self.database_url:  # only for sqlite URLs
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
