"""Centralized application logging.

Every module in the application should obtain a logger via
``get_logger(__name__)`` rather than using ``print()``.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from utils.paths import get_log_file_path

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_INITIALIZED = False


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root application logger exactly once.

    Sets up a rotating file handler (so logs don't grow unbounded) and, for
    convenience during development, a console handler as well.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return

    root_logger = logging.getLogger("activity_tracker")
    root_logger.setLevel(level)

    formatter = logging.Formatter(_LOG_FORMAT)

    try:
        log_file = get_log_file_path()
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except (OSError, RuntimeError):
        # If we can't write to the log directory - because of a filesystem
        # error, or because get_log_file_path() raised RuntimeError for an
        # unsupported OS (e.g. running the shared business logic's test
        # suite on a Linux CI runner) - fall back to console-only logging
        # rather than crashing the whole application/import.
        pass

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    _INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger under the ``activity_tracker`` root logger."""
    configure_logging()
    if not name.startswith("activity_tracker"):
        name = f"activity_tracker.{name}"
    return logging.getLogger(name)
