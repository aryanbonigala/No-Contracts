"""Read-only collector: Kalshi markets → ``raw_markets`` + ``api_fetch_log``."""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.collectors.common import (
    CollectorSummary,
    MultiStatusMarketsSummary,
    safe_error_message,
    utc_now,
)
from kalshi_no_carry.db.repositories import record_api_fetch, upsert_market


def _paginate_markets_once(
    client: Any,
    engine: Engine,
    *,
    limit: int,
    max_pages: int | None,
    status: str | None,
    event_ticker: str | None,
    series_ticker: str | None,
    source: str,
    seen_tickers: set[str] | None,
    duplicate_counter: list[int],
    ids_unique_order: list[str],
) -> CollectorSummary:
    """
    One GET /markets pagination loop with at most one ``status`` query parameter.

    When ``seen_tickers`` is provided, tickers already seen increment ``duplicate_counter``
    and are not appended again to ``ids_unique_order`` (fresh upserts still occur).
    """
    summary = CollectorSummary(name="collect_markets", started_at=utc_now())
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    cursor: str | None = None
    pages = 0
    dup = duplicate_counter
    try:
        while True:
            if max_pages is not None and pages >= max_pages:
                break
            with Session() as session:
                try:
                    page = client.get_markets(
                        limit=limit,
                        cursor=cursor,
                        status=status,
                        event_ticker=event_ticker,
                        series_ticker=series_ticker,
                    )
                except Exception as exc:
                    summary.success = False
                    summary.errors.append(safe_error_message(exc))
                    record_api_fetch(
                        session,
                        endpoint="/markets",
                        params_json={
                            "limit": limit,
                            "status": status,
                            "event_ticker": event_ticker,
                            "series_ticker": series_ticker,
                            "page": pages,
                        },
                        success=False,
                        error_message=safe_error_message(exc),
                        row_count=0,
                        source=source,
                    )
                    session.commit()
                    break

                markets = page.get("markets") or []
                if not isinstance(markets, list):
                    markets = []

                written = 0
                for m in markets:
                    if not isinstance(m, dict):
                        continue
                    tid = str(m.get("ticker") or "").strip()
                    try:
                        upsert_market(session, m)
                    except ValueError:
                        continue
                    written += 1
                    summary.ids_collected.append(tid)
                    if tid:
                        if seen_tickers is not None:
                            if tid in seen_tickers:
                                dup[0] += 1
                            else:
                                seen_tickers.add(tid)
                                ids_unique_order.append(tid)
                        else:
                            if tid not in ids_unique_order:
                                ids_unique_order.append(tid)

                summary.fetched_pages += 1
                summary.records_seen += len(markets)
                summary.records_written += written

                record_api_fetch(
                    session,
                    endpoint="/markets",
                    params_json={
                        "limit": limit,
                        "status": status,
                        "event_ticker": event_ticker,
                        "series_ticker": series_ticker,
                        "page": pages,
                    },
                    status_code=200,
                    success=True,
                    row_count=len(markets),
                    source=source,
                )
                session.commit()

                cursor = page.get("cursor")
                if not cursor:
                    break
                pages += 1
    finally:
        summary.finished_at = utc_now()
    return summary


def collect_markets(
    client: Any,
    engine: Engine,
    *,
    limit: int = 100,
    max_pages: int | None = None,
    status: str | None = None,
    event_ticker: str | None = None,
    series_ticker: str | None = None,
    source: str = "kalshi",
) -> CollectorSummary:
    """
    Paginate ``GET /markets``, upsert each market, and log each page fetch.

    ``client`` must provide ``get_markets(limit=..., cursor=..., ...)``.
    """
    ids_order: list[str] = []
    return _paginate_markets_once(
        client,
        engine,
        limit=limit,
        max_pages=max_pages,
        status=status,
        event_ticker=event_ticker,
        series_ticker=series_ticker,
        source=source,
        seen_tickers=None,
        duplicate_counter=[0],
        ids_unique_order=ids_order,
    )


def collect_markets_multi_status(
    client: Any,
    engine: Engine,
    *,
    market_statuses: tuple[str, ...] | None,
    limit: int = 100,
    max_pages: int | None = None,
    event_ticker: str | None = None,
    series_ticker: str | None = None,
    source: str = "kalshi",
) -> MultiStatusMarketsSummary:
    """
    Collect markets using Kalshi's single-``status`` filter per request.

    * ``market_statuses`` ``None`` or empty → one unfiltered pass (no ``status`` query arg).
    * Otherwise iterate each status string in order (dedupe semantics: API may return overlapping
      tickers across statuses; those are upserted once per occurrence but counted as duplicates).

    Summary includes per-status aggregates and ``duplicate_tickers_skipped`` for overlaps across
    passes within this run.
    """
    started = utc_now()
    out = MultiStatusMarketsSummary(
        name="collect_markets_multi_status",
        started_at=started,
        requested_statuses=[],
        success=True,
    )

    if not market_statuses:
        iteration: tuple[str | None, ...] = (None,)
    else:
        iteration = tuple(market_statuses)

    seen: set[str] = set()
    dup_box = [0]
    unique_ids: list[str] = []

    for st in iteration:
        api_status: str | None = None if st is None else str(st).strip().lower() or None
        key = "__api_default__" if api_status is None else api_status
        out.requested_statuses.append(api_status)

        sub = _paginate_markets_once(
            client,
            engine,
            limit=limit,
            max_pages=max_pages,
            status=api_status,
            event_ticker=event_ticker,
            series_ticker=series_ticker,
            source=source,
            seen_tickers=seen,
            duplicate_counter=dup_box,
            ids_unique_order=unique_ids,
        )

        out.status_results[key] = {
            "records_seen": sub.records_seen,
            "records_written": sub.records_written,
            "fetched_pages": sub.fetched_pages,
            "success": sub.success,
            "errors": list(sub.errors),
        }
        out.records_seen += sub.records_seen
        out.records_written += sub.records_written
        out.fetched_pages += sub.fetched_pages
        out.errors.extend(sub.errors)
        if not sub.success:
            out.success = False

    out.duplicate_tickers_skipped = int(dup_box[0])
    out.ids_collected = unique_ids
    out.finished_at = utc_now()
    if out.duplicate_tickers_skipped > 0:
        out.warnings.append(
            "DUPLICATE_TICKERS_ACROSS_STATUSES: overlapping tickers across status passes were counted "
            f"as duplicates ({out.duplicate_tickers_skipped}); rows were still upserted for freshness."
        )
    return out
