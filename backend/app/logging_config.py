"""Central logging configuration for the FMS backend.

The application keeps a complete backend log and duplicates warning-or-higher
records into a smaller file that is convenient during incident analysis.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import LOG_BACKUP_COUNT, LOG_DIR, LOG_LEVEL, LOG_MAX_BYTES


_FORMAT = (
    "%(asctime)s.%(msecs)03d %(levelname)s "
    "%(name)s [%(threadName)s] %(message)s"
)


def _file_handler(path: Path, level: int) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S"))
    return handler


def configure_logging() -> None:
    """Configure file logging once, without replacing Uvicorn console logs."""

    app_logger = logging.getLogger("fms")
    if getattr(app_logger, "_fms_configured", False):
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    configured_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    app_logger.setLevel(configured_level)
    app_logger.propagate = False
    app_logger.addHandler(_file_handler(LOG_DIR / "backend.log", configured_level))
    app_logger.addHandler(
        _file_handler(LOG_DIR / "backend.warning-error.log", logging.WARNING)
    )

    # Zenoh records also remain in backend.log, while this file gives a focused
    # timeline for connection investigations.
    zenoh_logger = logging.getLogger("fms.zenoh")
    zenoh_logger.setLevel(configured_level)
    zenoh_logger.addHandler(
        _file_handler(LOG_DIR / "zenoh-connection.log", configured_level)
    )

    frontend_logger = logging.getLogger("fms.frontend")
    frontend_logger.setLevel(logging.WARNING)
    frontend_logger.addHandler(
        _file_handler(LOG_DIR / "frontend-client.log", logging.WARNING)
    )

    setattr(app_logger, "_fms_configured", True)

