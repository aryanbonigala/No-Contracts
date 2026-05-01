"""Repository CRUD/upsert behavior on SQLite (no network)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, drop_all_tables
from kalshi_no_carry.db.repositories import (
    insert_orderbook_snapshot,
    record_api_fetch,
    upsert_event,
    upsert_event_cluster,
    upsert_market,
    upsert_strategy_split,
)
from kalshi_no_carry.db.schema import ApiFetchLog, RawEvent, RawMarket, RawOrderbookSnapshot, StrategySplit


def _utc_naive_safe(dt: datetime) -> datetime:
    """SQLite may return naive datetimes; treat as UTC for equality checks."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@pytest.fixture
def memory_engine():
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    yield engine
    drop_all_tables(engine)
    engine.dispose()


@pytest.fixture
def session_factory(memory_engine):
    maker = sessionmaker(memory_engine, expire_on_commit=False, future=True)
    yield maker


def test_record_api_fetch(session_factory) -> None:
    mk = session_factory
    with mk() as session:
        record_api_fetch(
            session,
            endpoint="/markets",
            params_json={"limit": 5},
            status_code=200,
            success=True,
            row_count=5,
            source="test",
        )
        session.commit()
    with mk() as session:
        n = session.scalar(select(func.count()).select_from(ApiFetchLog))
        assert n == 1


def test_upsert_event_idempotent(session_factory) -> None:
    mk = session_factory
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2024, 2, 1, tzinfo=timezone.utc)
    with mk() as session:
        upsert_event(
            session, {"event_ticker": "EVT-1", "title": "A", "status": "open"}, fetched_at=t0
        )
        session.commit()
    with mk() as session:
        upsert_event(
            session, {"event_ticker": "EVT-1", "title": "B", "status": "closed"}, fetched_at=t1
        )
        session.commit()
    with mk() as session:
        rows = session.scalars(select(RawEvent)).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.title == "B"
        assert row.status == "closed"
        assert _utc_naive_safe(row.first_seen_at) == t0
        assert _utc_naive_safe(row.last_seen_at) == t1


def test_upsert_market_idempotent(session_factory) -> None:
    mk = session_factory
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2024, 3, 1, tzinfo=timezone.utc)
    j1 = {
        "ticker": "MKT-1",
        "event_ticker": "EVT-1",
        "yes_bid_dollars": "0.4000",
        "yes_ask_dollars": "0.4500",
        "status": "active",
    }
    j2 = {**j1, "yes_bid_dollars": "0.4100", "status": "closed"}
    with mk() as session:
        upsert_market(session, j1, fetched_at=t0)
        session.commit()
    with mk() as session:
        upsert_market(session, j2, fetched_at=t1)
        session.commit()
    with mk() as session:
        rows = session.scalars(select(RawMarket)).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.yes_bid_cents == 41
        assert _utc_naive_safe(row.first_seen_at) == t0
        assert _utc_naive_safe(row.last_seen_at) == t1
        assert row.raw_json["yes_bid_dollars"] == "0.4100"


def test_insert_orderbook_snapshot(session_factory) -> None:
    mk = session_factory
    book = {
        "orderbook_fp": {
            "yes_dollars": [["0.3000", "100"]],
            "no_dollars": [["0.6000", "50"]],
        }
    }
    exec_override = {
        "best_yes_bid_cents": 30,
        "best_no_bid_cents": 60,
        "best_yes_ask_cents": 40,
        "best_no_ask_cents": 70,
        "yes_bid_size": "100",
        "no_bid_size": "50",
        "yes_ask_size": "50",
        "no_ask_size": "100",
    }
    with mk() as session:
        insert_orderbook_snapshot(
            session, "MKT-OB", book, executable_prices=exec_override
        )
        session.commit()
    with mk() as session:
        row = session.scalars(select(RawOrderbookSnapshot)).one()
        assert row.market_ticker == "MKT-OB"
        assert row.best_yes_bid_cents == 30
        assert row.best_no_ask_cents == 70
        assert row.raw_json == book


def test_upsert_strategy_split(session_factory) -> None:
    mk = session_factory
    with mk() as session:
        upsert_event_cluster(session, cluster_id="c1", representative_title="Cluster 1")
        upsert_strategy_split(
            session,
            cluster_id="c1",
            split_name="train",
            split_version="v2024-01",
        )
        session.commit()
    with mk() as session:
        upsert_strategy_split(
            session,
            cluster_id="c1",
            split_name="test",
            split_version="v2024-02",
            notes="holdout",
        )
        session.commit()
    with mk() as session:
        row = session.scalars(select(StrategySplit).where(StrategySplit.cluster_id == "c1")).one()
        assert row.split_name == "test"
        assert row.split_version == "v2024-02"
        assert row.notes == "holdout"


def test_upsert_strategy_split_invalid_name(session_factory) -> None:
    mk = session_factory
    with mk() as session:
        upsert_event_cluster(session, cluster_id="c2")
        with pytest.raises(ValueError):
            upsert_strategy_split(
                session,
                cluster_id="c2",
                split_name="train_test",
                split_version="v1",
            )
