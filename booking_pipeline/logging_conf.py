"""Structured logging: timestamp, level, module, function, message."""

import logging
import sys

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s.%(funcName)s | %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    # third-party noise
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("fontTools").setLevel(logging.WARNING)
    logging.getLogger("weasyprint").setLevel(logging.ERROR)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
