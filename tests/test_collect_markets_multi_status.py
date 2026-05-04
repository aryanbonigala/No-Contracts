"""Multi-status market collection (v0.13; offline)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.collectors.markets import collect_markets, collect_markets_multi_status
from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, drop_all_tables
from kalshi_no_carry.db.schema import RawMarket


class FakeMultiStatusClient:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def get_markets(self, **kwargs):
        st = kwargs.get("status")
        self.calls.append(st)
        if st == "open":
            return {"markets": [{"ticker": "DUP", "event_ticker": "E1", "yes_bid_dollars": "0.4000"}], "cursor": ""}
        if st == "settled":
            return {
                "markets": [
                    {"ticker": "DUP", "event_ticker": "E1", "yes_bid_dollars": "0.4100"},
                    {"ticker": "ONLY_SET", "event_ticker": "E1", "yes_bid_dollars": "0.5000"},
                ],
                "cursor": "",
            }
        return {"markets": [{"ticker": "DEF", "event_ticker": "E2", "yes_bid_dollars": "0.3000"}], "cursor": ""}


def test_collect_markets_multi_status_loops_statuses_and_counts_duplicates():
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, future=True)
    try:
        c = FakeMultiStatusClient()
        summ = collect_markets_multi_status(
            c,
            engine,
            market_statuses=("open", "settled"),
            limit=10,
            max_pages=1,
            source="test",
        )
        assert c.calls == ["open", "settled"]
        assert summ.success
        assert summ.records_seen == 3
        assert summ.records_written == 3
        assert summ.duplicate_tickers_skipped == 1
        assert summ.ids_collected == ["DUP", "ONLY_SET"]
        assert "open" in summ.status_results and "settled" in summ.status_results
        with Session() as s:
            assert s.scalar(select(func.count()).select_from(RawMarket)) == 2
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_collect_markets_multi_status_none_means_unfiltered_single_pass():
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    try:
        c = FakeMultiStatusClient()
        summ = collect_markets_multi_status(c, engine, market_statuses=None, limit=10, max_pages=1, source="test")
        assert c.calls == [None]
        assert summ.ids_collected == ["DEF"]
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_collect_markets_single_status_backward_compat():
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    try:
        summ = collect_markets(FakeMultiStatusClient(), engine, limit=10, max_pages=1, source="test")
        assert summ.records_written >= 1
    finally:
        drop_all_tables(engine)
        engine.dispose()
