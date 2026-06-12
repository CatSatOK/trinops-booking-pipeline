import os
from pathlib import Path

import pytest

from booking_pipeline.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent

# Jinja templates are loaded relative to the repo root
os.chdir(REPO_ROOT)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        demo_mode=True,
        anthropic_api_key="",
        invoice_dir=str(tmp_path / "invoices"),
        outbox_dir=str(tmp_path / "outbox"),
        database_url=f"sqlite:///{tmp_path}/test.db",
    )
