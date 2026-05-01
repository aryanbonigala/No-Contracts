"""Reusable logging configuration for CLI scripts and workers."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import TextIO


class _UtcFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat(timespec="seconds")


def configure_logging(level: str | int = "INFO", stream: TextIO | None = None) -> None:
    """
    Configure root logger once with a simple structured-ish format.

    :param level: logging level name or numeric level
    :param stream: stdout/stderr; defaults to stderr
    """
    if isinstance(level, str):
        level_num = getattr(logging, level.upper(), None)
        level = level_num if isinstance(level_num, int) else logging.INFO

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(
        _UtcFormatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)
