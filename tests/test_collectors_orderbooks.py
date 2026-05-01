"""Offline tests for orderbook collectors."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.collectors.orderbooks import (
    collect_orderbooks_for_active_markets,
    collect_orderbooks_for_markets,
)
from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, drop_all_tables
from kalshi_no_carry.db.schema import ApiFetchLog, RawMarket, RawOrderbookSnapshot


def _book():
    return {
        "orderbook_fp": {
            "yes_dollars": [["0.3500", "10"]],
            "no_dollars": [["0.5500", "20"]],
        }
    }


class FakeOBClient:
    def __init__(self) -> None:
        self.fail_for: set[str] = set()

    def get_markets(self, **kwargs):
        return {
            "markets": [
                {"ticker": "M1", "event_ticker": "E1", "yes_bid_dollars": "0.1000"},
                {"ticker": "M2", "event_ticker": "E1", "yes_bid_dollars": "0.2000"},
            ],
            "cursor": "",
        }

    def get_orderbook(self, ticker: str, depth=None):
        if ticker in self.fail_for:
            req = httpx.Request("GET", f"https://api.test/markets/{ticker}/orderbook")
            resp = httpx.Response(500, request=req)
            raise httpx.HTTPStatusError("fail", request=req, response=resp)
        return _book()


def test_collect_orderbooks_inserts_snapshots_and_executable_fields():
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, future=True)
    try:
        c = FakeOBClient()
        summ = collect_orderbooks_for_markets(c, engine, ["M1"], source="t")
        assert summ.success
        assert summ.snapshots_inserted == 1
        with Session() as s:
            row = s.scalars(select(RawOrderbookSnapshot)).one()
            assert row.market_ticker == "M1"
            assert row.best_yes_bid_cents == 35
            assert row.best_no_ask_cents == 65
            assert row.best_no_bid_cents == 55
            assert row.best_yes_ask_cents == 45
            assert s.scalar(select(func.count()).select_from(ApiFetchLog)) == 1
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_collect_orderbooks_continue_on_partial_failure():
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    try:
        c = FakeOBClient()
        c.fail_for.add("M1")
        summ = collect_orderbooks_for_markets(c, engine, ["M1", "M2"], fail_fast=False, source="t")
        assert summ.success is False
        assert summ.snapshots_inserted == 1
        assert summ.tickers_failed == 1
        assert len(summ.errors) == 1
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_collect_orderbooks_fail_fast_raises():
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    try:
        c = FakeOBClient()
        c.fail_for.add("M1")
        with pytest.raises(httpx.HTTPStatusError):
            collect_orderbooks_for_markets(c, engine, ["M1"], fail_fast=True, source="t")
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_collect_orderbooks_for_active_markets_chain():
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, future=True)
    try:
        c = FakeOBClient()
        out = collect_orderbooks_for_active_markets(
            c, engine, limit=50, max_pages=1, status="open", source="t"
        )
        assert out.markets.success
        assert out.markets.records_written == 2
        assert out.orderbooks.snapshots_inserted == 2
        with Session() as s:
            assert s.scalar(select(func.count()).select_from(RawMarket)) == 2
            assert s.scalar(select(func.count()).select_from(RawOrderbookSnapshot)) == 2
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_summary_counts_orderbooks():
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    try:
        summ = collect_orderbooks_for_markets(FakeOBClient(), engine, [], source="t")
        d = summ.to_public_dict()
        assert d["tickers_attempted"] == 0
        assert d["snapshots_inserted"] == 0
        assert d["success"] is True
    finally:
        drop_all_tables(engine)
        engine.dispose()
