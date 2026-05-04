"""Collection coverage summaries (v0.13)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.database import create_all_tables, drop_all_tables
from kalshi_no_carry.db.repositories import insert_orderbook_snapshot, upsert_market
from kalshi_no_carry.research.collection_coverage import summarize_collection_coverage


def test_summarize_collection_coverage_raw_markets_and_ratios():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_all_tables(engine)
    maker = sessionmaker(engine, expire_on_commit=False, future=True)
    day = datetime(2024, 6, 15, tzinfo=timezone.utc)
    try:
        with maker() as s:
            upsert_market(
                s,
                {
                    "ticker": "MX",
                    "event_ticker": "EX",
                    "status": "open",
                    "close_time": day.isoformat(),
                },
                fetched_at=day,
            )
            insert_orderbook_snapshot(
                s,
                "MX",
                {"orderbook_fp": {"yes_dollars": [["0.40", "1"]], "no_dollars": []}},
            )
            insert_orderbook_snapshot(s, "MX", {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}})
            s.commit()

        out = summarize_collection_coverage(
            engine,
            split_version="sv",
            feature_version="fv",
            label_version=None,
            include_test=False,
        )
        assert out["raw_markets_by_status"].get("open", 0) >= 1
        assert out["orderbook_snapshots_total"] == 2
        assert out["executable_no_ask_coverage_ratio"] is not None
        assert float(out["executable_no_ask_coverage_ratio"]) > 0
    finally:
        drop_all_tables(engine)
        engine.dispose()
