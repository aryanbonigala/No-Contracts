"""Read-only collectors: Kalshi orderbooks → ``raw_orderbook_snapshots``."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.collectors.common import (
    ActiveMarketsOrderbookSummary,
    OrderbookCollectionSummary,
    safe_error_message,
    utc_now,
)
from kalshi_no_carry.collectors.markets import collect_markets_multi_status
from kalshi_no_carry.db.repositories import insert_orderbook_snapshot, record_api_fetch
from kalshi_no_carry.research.orderbook_audit import orderbook_json_coverage_flags

ORDERBOOK_LOG_ENDPOINT = "/markets/{ticker}/orderbook"


def collect_orderbooks_for_markets(
    client: Any,
    engine: Engine,
    market_tickers: list[str],
    *,
    depth: int | None = None,
    source: str = "kalshi",
    fail_fast: bool = False,
    sleep_seconds: float = 0.0,
) -> OrderbookCollectionSummary:
    """
    Fetch one orderbook per ticker, insert a **new** snapshot row each time, log each attempt.

    ``client`` must provide ``get_orderbook(ticker, depth=None)``.
    """
    summary = OrderbookCollectionSummary(name="collect_orderbooks_for_markets", started_at=utc_now())
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    tickers = [str(t).strip() for t in market_tickers if str(t).strip()]

    for ticker in tickers:
        summary.tickers_attempted += 1
        if sleep_seconds > 0 and summary.tickers_attempted > 1:
            time.sleep(sleep_seconds)
        with Session() as session:
            try:
                ob = client.get_orderbook(ticker, depth=depth)
                insert_orderbook_snapshot(session, ticker, ob)
                record_api_fetch(
                    session,
                    endpoint=ORDERBOOK_LOG_ENDPOINT,
                    params_json={"ticker": ticker, "depth": depth},
                    status_code=200,
                    success=True,
                    row_count=1,
                    source=source,
                )
                session.commit()
                summary.snapshots_inserted += 1
                summary.tickers_succeeded += 1
                flags = orderbook_json_coverage_flags(ob if isinstance(ob, dict) else {})
                if flags.get("books_with_yes_bids"):
                    summary.books_with_yes_bids += 1
                if flags.get("books_with_no_bids"):
                    summary.books_with_no_bids += 1
                if flags.get("books_empty_both_sides"):
                    summary.books_empty_both_sides += 1
                if flags.get("books_with_executable_no_ask"):
                    summary.books_with_executable_no_ask += 1
                if flags.get("books_with_executable_yes_ask"):
                    summary.books_with_executable_yes_ask += 1
            except Exception as exc:
                session.rollback()
                msg = safe_error_message(exc)
                summary.errors.append(f"{ticker}: {msg}")
                summary.tickers_failed += 1
                summary.success = False
                with Session() as session2:
                    record_api_fetch(
                        session2,
                        endpoint=ORDERBOOK_LOG_ENDPOINT,
                        params_json={"ticker": ticker, "depth": depth},
                        success=False,
                        error_message=msg,
                        row_count=0,
                        source=source,
                    )
                    session2.commit()
                if fail_fast:
                    summary.finished_at = utc_now()
                    raise

    summary.finished_at = utc_now()
    return summary


def collect_orderbooks_for_active_markets(
    client: Any,
    engine: Engine,
    *,
    limit: int = 100,
    max_pages: int = 1,
    orderbook_source_status: str = "open",
    depth: int | None = None,
    source: str = "kalshi",
    fail_fast: bool = False,
    sleep_seconds: float = 0.0,
) -> ActiveMarketsOrderbookSummary:
    """
    Load markets (upsert), then fetch orderbooks for returned tickers.

    ``orderbook_source_status`` selects which market listing status seeds tickers (default ``open``).
    """
    warnings: list[str] = []
    oss = str(orderbook_source_status).strip().lower()
    if oss != "open":
        warnings.append(
            "Orderbooks are generally expected for open/active markets; non-open statuses may return "
            "empty or unavailable books."
        )

    msum = collect_markets_multi_status(
        client,
        engine,
        market_statuses=(oss,),
        limit=limit,
        max_pages=max_pages,
        source=source,
    )
    osum = collect_orderbooks_for_markets(
        client,
        engine,
        msum.ids_collected,
        depth=depth,
        source=source,
        fail_fast=fail_fast,
        sleep_seconds=sleep_seconds,
    )
    return ActiveMarketsOrderbookSummary(markets=msum, orderbooks=osum, warnings=warnings)
