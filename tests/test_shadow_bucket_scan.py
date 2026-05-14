"""Shadow bucket scanner persistence tests (offline fake client)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, drop_all_tables
from kalshi_no_carry.db.schema import ShadowBucketEntry
from kalshi_no_carry.research.shadow_bucket_config import BucketShadowConfig
from kalshi_no_carry.research.shadow_bucket_experiment import run_bucket_shadow_scan_persisted


class RecordingFakeClient:
    def __init__(self, pages: dict[str | None, list[dict]], books: dict[str, dict]) -> None:
        self.pages = pages
        self.books = books
        self.orderbook_calls: list[str] = []

    def iter_markets(self, *, limit: int = 100, status: str | None = None, **_: object):
        for m in self.pages.get(status, []):
            yield m

    def get_orderbook(self, ticker: str) -> dict:
        self.orderbook_calls.append(ticker)
        if ticker not in self.books:
            raise RuntimeError("boom")
        return self.books[ticker]


def _engine():
    eng = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(eng)
    return eng


def test_scanner_empty_universe() -> None:
    engine = _engine()
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    cfg = BucketShadowConfig(max_markets_per_scan=10)
    client = RecordingFakeClient({"open": [], "active": []}, {})
    try:
        with Session() as s:
            summary = run_bucket_shadow_scan_persisted(s, client, cfg)
            s.commit()
        assert summary["markets_seen"] == 0
        assert summary["entries_inserted"] == 0
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_scanner_inserts_85_bucket_entry() -> None:
    engine = _engine()
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    close = datetime.now(timezone.utc) + timedelta(days=1)
    markets = {
        "open": [
            {
                "ticker": "T85",
                "event_ticker": "E",
                "series_ticker": "S",
                "status": "open",
                "close_time": close.isoformat(),
            }
        ],
        "active": [],
    }
    books = {"T85": {"yes": [[15, 500]], "no": [[10, 100]]}}
    client = RecordingFakeClient(markets, books)
    cfg = BucketShadowConfig(
        bucket_prices_cents=(85,),
        stake_cents_per_trade=8500,
        entry_tolerance_cents=1,
        dry_run=False,
    )
    try:
        with Session() as s:
            summary = run_bucket_shadow_scan_persisted(s, client, cfg)
            s.commit()
        assert summary["entries_inserted"] == 1
        assert summary["entries_by_bucket"]["85"] == 1
        with Session() as s:
            n = s.scalar(select(func.count()).select_from(ShadowBucketEntry))
            assert n == 1
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_dry_run_inserts_no_entries() -> None:
    engine = _engine()
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    close = datetime.now(timezone.utc) + timedelta(days=1)
    markets = {
        "open": [
            {
                "ticker": "TDR",
                "status": "open",
                "close_time": close.isoformat(),
            }
        ],
        "active": [],
    }
    books = {"TDR": {"yes": [[15, 500]], "no": [[10, 100]]}}
    client = RecordingFakeClient(markets, books)
    cfg = BucketShadowConfig(
        bucket_prices_cents=(85,),
        stake_cents_per_trade=8500,
        dry_run=True,
    )
    try:
        with Session() as s:
            summary = run_bucket_shadow_scan_persisted(s, client, cfg)
            s.commit()
        assert summary["entries_inserted"] == 0
        assert summary["dry_run"] is True
        with Session() as s:
            assert s.scalar(select(func.count()).select_from(ShadowBucketEntry)) == 0
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_orderbook_fetch_failure_recorded() -> None:
    engine = _engine()
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    close = datetime.now(timezone.utc) + timedelta(days=1)
    markets = {
        "open": [
            {
                "ticker": "TX",
                "status": "open",
                "close_time": close.isoformat(),
            }
        ],
        "active": [],
    }
    client = RecordingFakeClient(markets, {})
    cfg = BucketShadowConfig(bucket_prices_cents=(85,), stake_cents_per_trade=8500)
    try:
        with Session() as s:
            summary = run_bucket_shadow_scan_persisted(s, client, cfg)
            s.commit()
        assert summary["orderbooks_failed"] >= 1
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_max_markets_limit() -> None:
    engine = _engine()
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    close = datetime.now(timezone.utc) + timedelta(days=1)
    mks = [
        {
            "ticker": f"T{i}",
            "status": "open",
            "close_time": close.isoformat(),
        }
        for i in range(5)
    ]
    books = {f"T{i}": {"yes": [[1, 1]], "no": [[1, 1]]} for i in range(5)}
    client = RecordingFakeClient({"open": mks, "active": []}, books)
    cfg = BucketShadowConfig(bucket_prices_cents=(85,), stake_cents_per_trade=8500, max_markets_per_scan=2)
    try:
        with Session() as s:
            summary = run_bucket_shadow_scan_persisted(s, client, cfg)
            s.commit()
        assert summary["markets_seen"] == 2
    finally:
        drop_all_tables(engine)
        engine.dispose()
