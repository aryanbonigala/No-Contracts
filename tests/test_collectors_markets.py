"""Offline tests for market collector."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.collectors.markets import collect_markets
from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, drop_all_tables
from kalshi_no_carry.db.schema import ApiFetchLog, RawMarket


class FakeMarketsClient:
    def __init__(self) -> None:
        self.pages = [
            {
                "markets": [
                    {
                        "ticker": "M1",
                        "event_ticker": "E1",
                        "yes_bid_dollars": "0.5000",
                        "status": "active",
                    }
                ],
                "cursor": "",
            }
        ]
        self.calls = 0

    def get_markets(self, **kwargs):
        if self.calls >= len(self.pages):
            return {"markets": [], "cursor": ""}
        p = self.pages[self.calls]
        self.calls += 1
        return p


def test_collect_markets_upserts_and_logs():
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, future=True)
    try:
        summ = collect_markets(FakeMarketsClient(), engine, limit=10, max_pages=2, source="test")
        assert summ.success
        assert summ.records_written == 1
        assert summ.ids_collected == ["M1"]
        with Session() as s:
            assert s.scalar(select(func.count()).select_from(RawMarket)) == 1
            assert s.scalar(select(func.count()).select_from(ApiFetchLog)) == 1
            m = s.get(RawMarket, "M1")
            assert m is not None
            assert m.yes_bid_cents == 50
    finally:
        drop_all_tables(engine)
        engine.dispose()
