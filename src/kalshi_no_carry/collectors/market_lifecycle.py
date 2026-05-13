"""Generic read-only lifecycle refresh for previously observed market tickers (v0.15+).

Refetches market payloads via **batched** ``GET /markets?tickers=...`` when supported, with
**per-ticker** ``GET /markets/{ticker}`` fallback. Upserts ``raw_markets``. Selection uses only
stored lifecycle/label state — not prices, categories, or strategy filters.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.collectors.common import safe_error_message, utc_now
from kalshi_no_carry.db.repositories import record_api_fetch, upsert_market
from kalshi_no_carry.db.schema import RawMarket, RawOrderbookSnapshot, ResearchMarketLabel
from kalshi_no_carry.research.outcomes import DEFAULT_LABEL_VERSION

BATCH_REFRESH_FALLBACK_WARN = "batch_refresh_fallback_used"


def _dedupe_tickers_preserve_order(tickers: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in tickers:
        t = str(raw).strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _definitive_label_predicate() -> Any:
    """SQL expression true when stored label indicates a finalized yes/no or void outcome."""
    resolved_yes_no = and_(
        ResearchMarketLabel.label_is_resolved.is_(True),
        ResearchMarketLabel.label_market_result.in_(("yes", "no")),
    )
    voidish = or_(
        ResearchMarketLabel.label_is_void.is_(True),
        func.lower(func.coalesce(ResearchMarketLabel.label_market_result, "")) == "void",
    )
    return or_(resolved_yes_no, voidish)


def lifecycle_refresh_candidates_select(
    *,
    require_orderbook_snapshot: bool,
    label_version: str,
    include_already_labeled: bool,
    ordered: bool = True,
) -> Any:
    """
    Shared SELECT of distinct candidate ``market_ticker`` values.

    Returned object is SQLAlchemy 2.x ``Select`` ordered by ticker (for stable limits).
    """
    lv = (label_version or "").strip() or DEFAULT_LABEL_VERSION

    if require_orderbook_snapshot:
        stmt = (
            select(RawOrderbookSnapshot.market_ticker)
            .distinct()
            .outerjoin(
                ResearchMarketLabel,
                and_(
                    ResearchMarketLabel.market_ticker == RawOrderbookSnapshot.market_ticker,
                    ResearchMarketLabel.label_version == lv,
                ),
            )
        )
        order_col = RawOrderbookSnapshot.market_ticker
    else:
        stmt = (
            select(RawMarket.market_ticker)
            .distinct()
            .outerjoin(
                ResearchMarketLabel,
                and_(
                    ResearchMarketLabel.market_ticker == RawMarket.market_ticker,
                    ResearchMarketLabel.label_version == lv,
                ),
            )
        )
        order_col = RawMarket.market_ticker

    if not include_already_labeled:
        definitive = _definitive_label_predicate()
        stmt = stmt.where(
            or_(
                ResearchMarketLabel.market_ticker.is_(None),
                not_(definitive),
            )
        )

    if ordered:
        stmt = stmt.order_by(order_col)
    return stmt


def count_lifecycle_refresh_candidates(
    engine: Engine,
    *,
    label_version: str = DEFAULT_LABEL_VERSION,
    include_already_labeled: bool = False,
    require_orderbook_snapshot: bool = True,
) -> int:
    """Count refresh candidates matching :func:`find_lifecycle_refresh_candidates` without a limit."""
    subq = lifecycle_refresh_candidates_select(
        require_orderbook_snapshot=require_orderbook_snapshot,
        label_version=label_version,
        include_already_labeled=include_already_labeled,
        ordered=False,
    ).subquery()
    maker = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with maker() as session:
        n = session.scalar(select(func.count()).select_from(subq))
    return int(n or 0)


def find_lifecycle_refresh_candidates(
    engine: Engine,
    *,
    limit: int | None = None,
    require_orderbook_snapshot: bool = True,
    label_version: str = DEFAULT_LABEL_VERSION,
    include_already_labeled: bool = False,
) -> list[str]:
    """
    Return ticker symbols worth refreshing based on generic lifecycle state only.

    Default: distinct markets with stored orderbook snapshots and **non-definitive** labels
    (missing label row, unknown, or not yet resolved yes/no / void per stored extraction).
    """
    stmt = lifecycle_refresh_candidates_select(
        require_orderbook_snapshot=require_orderbook_snapshot,
        label_version=label_version,
        include_already_labeled=include_already_labeled,
    )
    if limit is not None:
        stmt = stmt.limit(int(limit))

    maker = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with maker() as session:
        rows = list(session.scalars(stmt).all())
    return [str(x).strip() for x in rows if x and str(x).strip()]


def _extract_market_dict(response: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    m = response.get("market")
    if isinstance(m, dict):
        return m
    if "ticker" in response:
        return response
    return None


def _request_markets_batch(client: Any, tickers: list[str]) -> dict[str, Any]:
    """Call batched GET /markets (``tickers`` query param); raises on missing client support or HTTP errors."""
    fn = getattr(client, "get_markets_by_tickers", None)
    if callable(fn):
        return fn(tickers)
    gm = getattr(client, "get_markets", None)
    if not callable(gm):
        raise AttributeError("kalshi_client has no get_markets_by_tickers or get_markets")
    joined = ",".join(tickers)
    lim = min(200, max(len(tickers), 1))
    return gm(limit=lim, tickers=joined)


def _markets_list_from_page(page: dict[str, Any]) -> list[dict[str, Any]]:
    markets = page.get("markets") or []
    if not isinstance(markets, list):
        return []
    return [m for m in markets if isinstance(m, dict)]


def refresh_markets_by_ticker(
    engine: Engine,
    kalshi_client: Any,
    tickers: Sequence[str],
    *,
    batch_size: int = 100,
    dry_run: bool = False,
    source: str = "kalshi_lifecycle_refresh",
) -> dict[str, Any]:
    """
    Re-fetch markets for distinct tickers (order preserved), preferring **batched** ``GET /markets``
    and falling back to ``GET /markets/{ticker}``. Upserts ``raw_markets``.

    Returns a JSON-serializable summary (no secrets). ``dry_run`` performs no database writes
    (no upserts, no ``api_fetch_log`` rows) but may still call the client when provided.
    """
    unique = _dedupe_tickers_preserve_order(tickers)
    # Kalshi listing endpoint supports at most 200 markets per request.
    bs = max(1, min(int(batch_size), 200))

    summary: dict[str, Any] = {
        "requested_tickers_count": len(list(tickers)),
        "unique_tickers_count": len(unique),
        "batches_attempted": 0,
        "batches_succeeded": 0,
        "batch_refresh_used": False,
        "fallback_ticker_refresh_used": False,
        "markets_seen": 0,
        "markets_written": 0,
        "missing_tickers_count": 0,
        "errors": [],
        "warnings": [],
        "dry_run": bool(dry_run),
        "success": True,
        "started_at": utc_now().isoformat(),
    }

    if not unique:
        summary["warnings"].append("NO_TICKERS: refresh list empty after normalization.")
        summary["finished_at"] = utc_now().isoformat()
        return summary

    batch_count = (len(unique) + bs - 1) // bs
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    errs: list[str] = []

    def _log_fetch(
        *,
        endpoint: str,
        params_json: dict[str, Any],
        success: bool,
        status_code: int | None = None,
        error_message: str | None = None,
        row_count: int | None = None,
    ) -> None:
        if dry_run:
            return
        with Session() as session:
            try:
                record_api_fetch(
                    session,
                    endpoint=endpoint,
                    params_json=params_json,
                    status_code=status_code,
                    success=success,
                    error_message=error_message,
                    row_count=row_count,
                    source=source,
                )
                session.commit()
            except Exception as log_exc:
                session.rollback()
                errs.append(f"log_error:{endpoint}:{safe_error_message(log_exc)}")

    def _upsert_one(
        m: dict[str, Any],
        ticker: str,
        params_json: dict[str, Any],
        *,
        record_ticker_fetch: bool = True,
    ) -> bool:
        """Returns True if this ticker was processed OK (seen); False if inner batch should fail."""
        nonlocal summary
        if not m or not str(m.get("ticker") or "").strip():
            summary["missing_tickers_count"] += 1
            errs.append(f"{ticker}: empty_or_invalid_market_payload")
            if record_ticker_fetch and not dry_run:
                _log_fetch(
                    endpoint="/markets/{ticker}",
                    params_json=params_json,
                    success=False,
                    status_code=200,
                    error_message="empty_or_invalid_market_payload",
                    row_count=0,
                )
            return False

        summary["markets_seen"] += 1
        if dry_run:
            return True

        with Session() as session:
            try:
                upsert_market(session, m)
                if record_ticker_fetch:
                    record_api_fetch(
                        session,
                        endpoint="/markets/{ticker}",
                        params_json=params_json,
                        status_code=200,
                        success=True,
                        row_count=1,
                        source=source,
                    )
                session.commit()
                summary["markets_written"] += 1
            except ValueError:
                session.rollback()
                summary["missing_tickers_count"] += 1
                errs.append(f"{ticker}: upsert_validation_error")
                return False
            except Exception as exc:
                session.rollback()
                errs.append(f"{ticker}: {safe_error_message(exc)}")
                return False
        return True

    def _per_ticker_loop(slice_: list[str], b: int) -> bool:
        """Returns True if batch had no per-ticker failures."""
        summary["fallback_ticker_refresh_used"] = True
        batch_ok = True
        for ticker in slice_:
            params_json = {"ticker": ticker, "batch_index": b, "mode": "per_ticker"}
            try:
                page = kalshi_client.get_market(ticker)
            except Exception as exc:
                batch_ok = False
                msg = safe_error_message(exc)
                errs.append(f"{ticker}: {msg}")
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
                    summary["missing_tickers_count"] += 1
                elif "404" in msg:
                    summary["missing_tickers_count"] += 1
                if not dry_run:
                    _log_fetch(
                        endpoint="/markets/{ticker}",
                        params_json=params_json,
                        success=False,
                        error_message=msg,
                        row_count=0,
                    )
                continue

            m = _extract_market_dict(page)
            ok = _upsert_one(m, ticker, params_json)
            if not ok:
                batch_ok = False
        return batch_ok

    for b in range(batch_count):
        summary["batches_attempted"] += 1
        slice_ = unique[b * bs : (b + 1) * bs]
        batch_ok = True
        batch_params = {
            "tickers": ",".join(slice_),
            "batch_index": b,
            "mode": "tickers_query",
            "ticker_count": len(slice_),
        }

        used_batch_path = False
        try:
            page = _request_markets_batch(kalshi_client, slice_)
            used_batch_path = True
            summary["batch_refresh_used"] = True
            by_ticker: dict[str, dict[str, Any]] = {}
            for m in _markets_list_from_page(page):
                tid = str(m.get("ticker") or "").strip()
                if tid:
                    by_ticker[tid] = m

            if not dry_run:
                _log_fetch(
                    endpoint="/markets",
                    params_json=batch_params,
                    success=True,
                    status_code=200,
                    row_count=len(by_ticker),
                )

            for ticker in slice_:
                m = by_ticker.get(ticker)
                if m is None:
                    summary["missing_tickers_count"] += 1
                    errs.append(f"{ticker}: not_in_batch_response")
                    batch_ok = False
                    continue
                params_json = {**batch_params, "ticker": ticker}
                ok = _upsert_one(m, ticker, params_json, record_ticker_fetch=False)
                if not ok:
                    batch_ok = False

        except (AttributeError, TypeError, NotImplementedError, ValueError) as exc:
            summary["warnings"].append(
                f"{BATCH_REFRESH_FALLBACK_WARN}: {type(exc).__name__}: {safe_error_message(exc)}"
            )
            batch_ok = _per_ticker_loop(slice_, b)
        except Exception as exc:
            extra = ""
            if isinstance(exc, httpx.ConnectError):
                extra = (
                    " If this is a connectivity failure, run `python scripts/check_kalshi_connectivity.py` "
                    "(read-only diagnostics)."
                )
            summary["warnings"].append(
                f"{BATCH_REFRESH_FALLBACK_WARN}: {type(exc).__name__}: {safe_error_message(exc)}{extra}"
            )
            if used_batch_path and not dry_run:
                _log_fetch(
                    endpoint="/markets",
                    params_json=batch_params,
                    success=False,
                    error_message=safe_error_message(exc),
                    row_count=0,
                )
            batch_ok = _per_ticker_loop(slice_, b)

        if batch_ok:
            summary["batches_succeeded"] += 1

    summary["errors"] = errs[:200]
    if len(errs) > 200:
        summary["warnings"].append(f"ERRORS_TRUNCATED: total_errors={len(errs)}")
    summary["success"] = len(errs) == 0
    summary["finished_at"] = utc_now().isoformat()
    return summary


__all__ = [
    "BATCH_REFRESH_FALLBACK_WARN",
    "count_lifecycle_refresh_candidates",
    "find_lifecycle_refresh_candidates",
    "lifecycle_refresh_candidates_select",
    "refresh_markets_by_ticker",
]
