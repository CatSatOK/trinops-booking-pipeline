"""APScheduler job: poll the inbox every POLL_INTERVAL_MINUTES."""

from apscheduler.schedulers.background import BackgroundScheduler

from booking_pipeline.calendar_client import get_calendar_client
from booking_pipeline.config import get_settings
from booking_pipeline.database import session_scope
from booking_pipeline.email_ingestion import get_email_source
from booking_pipeline.logging_conf import get_logger
from booking_pipeline.notifier import get_notifier
from booking_pipeline.pipeline import process_new_emails

logger = get_logger(__name__)

_scheduler: BackgroundScheduler | None = None
_email_source = None  # kept module-level so the seed source remembers processed ids


def poll_inbox() -> None:
    global _email_source
    settings = get_settings()
    if _email_source is None:
        _email_source = get_email_source(settings)
    calendar = get_calendar_client(settings)
    notifier = get_notifier(settings)
    try:
        with session_scope() as session:
            process_new_emails(session, settings, _email_source, calendar, notifier)
    except Exception:
        logger.exception("inbox poll failed")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    settings = get_settings()
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        poll_inbox,
        trigger="interval",
        minutes=settings.poll_interval_minutes,
        id="poll_inbox",
        coalesce=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info("scheduler started: polling every %d min", settings.poll_interval_minutes)
    # process anything already waiting (and the seed file in demo mode)
    poll_inbox()
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
