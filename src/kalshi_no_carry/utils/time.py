"""Time utilities for research code paths (UTC-first, no strategy logic)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    """Return timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """Return an UTC-normalized datetime (naive inputs are treated as UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso8601_utc(value: str) -> datetime:
    """
    Parse an ISO-8601 timestamp into UTC.

    Python 3.11+ supports ``Z`` suffix natively; for broader compatibility we replace Z with +00:00.
    """
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return ensure_utc(parsed)


def isoformat_z(dt: datetime) -> str:
    """Format datetime as ISO-8601 with ``Z`` suffix (UTC)."""
    return ensure_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def json_sanitize_dt(obj: Any) -> Any:
    """
    Intended for ``json.dumps(..., default=json_sanitize_dt)`` helpers (future use).

    Converts ``datetime`` to ISO strings; leaves other types untouched (let ``json`` raise).
    """
    if isinstance(obj, datetime):
        return isoformat_z(obj)
    raise TypeError(f"Object of type {type(obj)!r} is not JSON serializable")
