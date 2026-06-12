"""FastAPI app: booking API + static admin panel."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes.bookings import router as bookings_router
from booking_pipeline.database import init_db
from booking_pipeline.logging_conf import setup_logging
from booking_pipeline.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Trinops Booking Pipeline", lifespan=lifespan)
app.include_router(bookings_router)
app.mount("/", StaticFiles(directory="frontend", html=True), name="admin")
