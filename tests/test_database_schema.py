"""Schema metadata coverage for v0.3 tables."""

from __future__ import annotations

import pytest

from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, drop_all_tables
from kalshi_no_carry.db.schema import ApiFetchLog, Base, EventCluster, RawEvent, RawMarket, RawOrderbookSnapshot, StrategySplit

EXPECTED_TABLES = frozenset(
    {
        "api_fetch_log",
        "raw_events",
        "raw_markets",
        "raw_orderbook_snapshots",
        "event_clusters",
        "strategy_splits",
    }
)


def test_metadata_contains_required_tables() -> None:
    tables = set(Base.metadata.tables.keys())
    missing = EXPECTED_TABLES - tables
    assert not missing, f"missing tables: {missing}"


@pytest.mark.parametrize(
    "model, column",
    [
        (ApiFetchLog, "endpoint"),
        (RawEvent, "event_ticker"),
        (RawMarket, "market_ticker"),
        (RawOrderbookSnapshot, "raw_json"),
        (EventCluster, "cluster_id"),
        (StrategySplit, "split_name"),
    ],
)
def test_key_columns_exist(model: type, column: str) -> None:
    assert column in model.__table__.columns


def test_strategy_splits_composite_primary_key() -> None:
    pk_cols = {c.key for c in StrategySplit.__table__.primary_key.columns}
    assert pk_cols == {"cluster_id", "split_version"}


def test_create_all_sqlite_memory() -> None:
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    try:
        create_all_tables(engine)
        assert EXPECTED_TABLES <= set(Base.metadata.tables.keys())
    finally:
        drop_all_tables(engine)
        engine.dispose()
