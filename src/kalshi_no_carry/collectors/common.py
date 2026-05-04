"""Shared types and helpers for read-only Kalshi collectors."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, date, timezone
from typing import Any

import httpx


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def json_safe_collector_value(obj: Any) -> Any:
    """Recursively convert collector summary fragments to JSON-serializable values."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): json_safe_collector_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe_collector_value(x) for x in obj]
    if isinstance(obj, set):
        return [json_safe_collector_value(x) for x in sorted(obj, key=lambda x: str(x))]
    return str(obj)


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
class MultiStatusMarketsSummary:
    """Markets collector across one or more API ``status`` filters (Kalshi allows one per request)."""

    name: str
    started_at: datetime
    finished_at: datetime | None = None
    requested_statuses: list[str | None] = field(default_factory=list)
    """``None`` means unfiltered / API-default single pass."""
    status_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    records_seen: int = 0
    records_written: int = 0
    fetched_pages: int = 0
    duplicate_tickers_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    success: bool = True
    ids_collected: list[str] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        keys = []
        for s in self.requested_statuses:
            keys.append("__api_default__" if s is None else str(s))
        return {
            "name": self.name,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "requested_statuses": keys,
            "status_results": json_safe_collector_value(self.status_results),
            "records_seen": self.records_seen,
            "records_written": self.records_written,
            "fetched_pages": self.fetched_pages,
            "duplicate_tickers_skipped": self.duplicate_tickers_skipped,
            "success": self.success,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "ids_collected_count": len(self.ids_collected),
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
    tickers_succeeded: int = 0
    books_with_yes_bids: int = 0
    books_with_no_bids: int = 0
    books_empty_both_sides: int = 0
    books_with_executable_no_ask: int = 0
    books_with_executable_yes_ask: int = 0
    errors: list[str] = field(default_factory=list)
    success: bool = True

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "tickers_attempted": self.tickers_attempted,
            "tickers_succeeded": self.tickers_succeeded,
            "snapshots_inserted": self.snapshots_inserted,
            "tickers_failed": self.tickers_failed,
            "books_with_yes_bids": self.books_with_yes_bids,
            "books_with_no_bids": self.books_with_no_bids,
            "books_empty_both_sides": self.books_empty_both_sides,
            "books_with_executable_no_ask": self.books_with_executable_no_ask,
            "books_with_executable_yes_ask": self.books_with_executable_yes_ask,
            "success": self.success,
            "errors": list(self.errors),
        }


@dataclass
class ActiveMarketsOrderbookSummary:
    """Combined market load + orderbook pull for active/open markets."""

    markets: CollectorSummary | MultiStatusMarketsSummary
    orderbooks: OrderbookCollectionSummary
    warnings: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """True when both the market listing and orderbook pulls completed without recorded errors."""
        return bool(self.markets.success and self.orderbooks.success)

    @property
    def errors(self) -> list[str]:
        return list(self.markets.errors) + list(self.orderbooks.errors)

    def to_public_dict(self) -> dict[str, Any]:
        md = self.markets.to_public_dict()
        od = self.orderbooks.to_public_dict()
        finished = od.get("finished_at") or md.get("finished_at")
        rec_seen = int(md.get("records_seen") or 0) + int(od.get("tickers_attempted") or 0)
        rec_written = int(md.get("records_written") or 0) + int(od.get("snapshots_inserted") or 0)
        return {
            "success": self.success,
            "errors": self.errors,
            "warnings": list(self.warnings),
            "records_seen": rec_seen,
            "records_written": rec_written,
            "ids_collected_count": int(md.get("ids_collected_count") or 0),
            "started_at": md["started_at"],
            "finished_at": finished,
            "markets": md,
            "orderbooks": od,
        }


def _detail_dict_from_summary(summary: Any) -> dict[str, Any]:
    if summary is None:
        return {}
    if isinstance(summary, dict):
        return dict(summary)
    if hasattr(summary, "to_public_dict") and callable(summary.to_public_dict):
        try:
            return summary.to_public_dict()
        except Exception:
            return {}
    try:
        from pydantic import BaseModel

        if isinstance(summary, BaseModel):
            return summary.model_dump(mode="json")
    except ImportError:
        pass
    if is_dataclass(summary) and not isinstance(summary, type):
        try:
            raw = asdict(summary)
            return json_safe_collector_value(raw)  # type: ignore[return-value]
        except Exception:
            return {}
    return {}


def _gather_collector_errors(detail: dict[str, Any], summary: Any) -> list[str]:
    out: list[str] = []
    if isinstance(detail.get("errors"), list):
        out.extend(str(x) for x in detail["errors"])
    elif hasattr(summary, "errors"):
        err = getattr(summary, "errors", None)
        if isinstance(err, list):
            out.extend(str(x) for x in err)
    for key in ("markets", "orderbooks", "events"):
        sub = detail.get(key)
        if isinstance(sub, dict) and isinstance(sub.get("errors"), list):
            out.extend(str(x) for x in sub["errors"])
    seen: set[str] = set()
    deduped: list[str] = []
    for e in out:
        if e not in seen:
            seen.add(e)
            deduped.append(e)
    return deduped


def _records_from_detail(detail: dict[str, Any]) -> tuple[int | None, int | None]:
    if not detail:
        return None, None
    if "records_seen" in detail and "records_written" in detail:
        try:
            return int(detail["records_seen"]), int(detail["records_written"])
        except (TypeError, ValueError):
            pass
    if "tickers_attempted" in detail and "snapshots_inserted" in detail:
        try:
            return int(detail["tickers_attempted"]), int(detail["snapshots_inserted"])
        except (TypeError, ValueError):
            pass
    m = detail.get("markets") if isinstance(detail.get("markets"), dict) else {}
    o = detail.get("orderbooks") if isinstance(detail.get("orderbooks"), dict) else {}
    if m or o:
        try:
            rs = int(m.get("records_seen") or 0) + int(o.get("tickers_attempted") or 0)
            rw = int(m.get("records_written") or 0) + int(o.get("snapshots_inserted") or 0)
            return rs, rw
        except (TypeError, ValueError):
            return None, None
    return None, None


def normalize_collector_summary(summary: Any, stage_name: str) -> dict[str, Any]:
    """
    Produce a JSON-serializable summary dict for pipeline / CLI output.

    Handles dicts, Pydantic models, dataclasses, and objects that implement ``to_public_dict``.
    ``success`` defaults to True when there is no explicit field and ``errors`` is empty.
    """
    norm_warnings: list[str] = []
    detail_raw = _detail_dict_from_summary(summary)
    detail = json_safe_collector_value(detail_raw)
    if not isinstance(detail, dict):
        detail = {"_unstructured_detail": detail}

    errors = _gather_collector_errors(detail, summary)

    if isinstance(detail.get("warnings"), list):
        for w in detail["warnings"]:
            if isinstance(w, str) and w.strip():
                norm_warnings.append(w.strip())

    explicit_success: bool | None = None
    if hasattr(summary, "success"):
        explicit_success = bool(getattr(summary, "success"))
    elif isinstance(detail.get("success"), bool):
        explicit_success = bool(detail["success"])

    if explicit_success is not None:
        success = bool(explicit_success)
    else:
        has_nested_success = False
        nested_ok = True
        for key in ("markets", "orderbooks", "events"):
            sub = detail.get(key)
            if isinstance(sub, dict) and "success" in sub:
                has_nested_success = True
                nested_ok = nested_ok and bool(sub.get("success"))
        if has_nested_success:
            success = nested_ok and len(errors) == 0
            if not nested_ok:
                norm_warnings.append(
                    "COLLECTOR_SUMMARY: success=false inferred from nested collector summary flags."
                )
        else:
            success = len(errors) == 0
            if success:
                norm_warnings.append(
                    "COLLECTOR_SUMMARY: success inferred (no explicit success field); errors empty."
                )

    if errors and success:
        success = False
        norm_warnings.append("COLLECTOR_SUMMARY: success set to false because errors list is non-empty.")

    rs, rw = _records_from_detail(detail)
    out: dict[str, Any] = {
        "stage_name": stage_name,
        "success": success,
        "errors": errors,
        "warnings": norm_warnings,
        "detail": detail,
    }
    if rs is not None:
        out["records_seen"] = rs
    if rw is not None:
        out["records_written"] = rw
    return out
