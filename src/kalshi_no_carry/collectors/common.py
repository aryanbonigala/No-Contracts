"""Shared types and helpers for read-only Kalshi collectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def safe_error_message(exc: BaseException, *, max_len: int = 400) -> str:
    """Truncate exception text; avoid echoing full URLs or response bodies."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"[:max_len]
    if isinstance(exc, httpx.RequestError):
        return f"request_error: {type(exc).__name__}"[:max_len]
    return str(exc).replace("\n", " ")[:max_len]


@dataclass
class CollectorSummary:
    """Summary for paginated event/market ingestion (no secrets)."""

    name: str
    started_at: datetime
    finished_at: datetime | None = None
    fetched_pages: int = 0
    records_seen: int = 0
    records_written: int = 0
    errors: list[str] = field(default_factory=list)
    success: bool = True
    """Stable ids written in order (event_ticker or market ticker); may be large."""
    ids_collected: list[str] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        """JSON-friendly dict for CLI output (omits long id lists)."""
        return {
            "name": self.name,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "fetched_pages": self.fetched_pages,
            "records_seen": self.records_seen,
            "records_written": self.records_written,
            "ids_collected_count": len(self.ids_collected),
            "success": self.success,
            "errors": list(self.errors),
        }


@dataclass
class OrderbookCollectionSummary:
    """Summary for per-ticker orderbook snapshots."""

    name: str
    started_at: datetime
    finished_at: datetime | None = None
    tickers_attempted: int = 0
    snapshots_inserted: int = 0
    tickers_failed: int = 0
    errors: list[str] = field(default_factory=list)
    success: bool = True

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "tickers_attempted": self.tickers_attempted,
            "snapshots_inserted": self.snapshots_inserted,
            "tickers_failed": self.tickers_failed,
            "success": self.success,
            "errors": list(self.errors),
        }


@dataclass
class ActiveMarketsOrderbookSummary:
    """Combined market load + orderbook pull for active/open markets."""

    markets: CollectorSummary
    orderbooks: OrderbookCollectionSummary

    def to_public_dict(self) -> dict[str, Any]:
        return {"markets": self.markets.to_public_dict(), "orderbooks": self.orderbooks.to_public_dict()}

