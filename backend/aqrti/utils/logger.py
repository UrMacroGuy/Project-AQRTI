"""
AQRTI Logging System
Structured logging with per-module loggers and file rotation.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

_FMT = "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def _build_handler_stream() -> logging.StreamHandler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))
    return handler


def _build_handler_file(filename: str) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        LOG_DIR / filename,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))
    return handler


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(f"aqrti.{name}")
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.addHandler(_build_handler_stream())
    logger.addHandler(_build_handler_file("aqrti.log"))
    logger.propagate = False
    return logger


# Module-specific loggers used across the codebase
data_logger     = get_logger("data")
api_logger      = get_logger("api")
db_logger       = get_logger("database")
scheduler_logger = get_logger("scheduler")
