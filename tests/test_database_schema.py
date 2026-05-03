"""Schema metadata coverage for v0.3 tables."""

from __future__ import annotations

import pytest

from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, drop_all_tables
from kalshi_no_carry.db.schema import (
    ApiFetchLog,
    BacktestTrade,
    Base,
    EventCluster,
    RawEvent,
    RawMarket,
    RawOrderbookSnapshot,
    ResearchFeatureRow,
    ResearchMarketLabel,
    StrategySplit,
)

EXPECTED_TABLES = frozenset(
    {
        "api_fetch_log",
        "raw_events",
        "raw_markets",
        "raw_orderbook_snapshots",
        "event_clusters",
        "strategy_splits",
        "research_feature_rows",
        "research_market_labels",
        "backtest_runs",
        "backtest_trades",
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
        (ResearchFeatureRow, "snapshot_id"),
    ],
)
def test_key_columns_exist(model: type, column: str) -> None:
    assert column in model.__table__.columns


def test_strategy_splits_composite_primary_key() -> None:
    pk_cols = {c.key for c in StrategySplit.__table__.primary_key.columns}
    assert pk_cols == {"cluster_id", "split_version"}


def test_research_feature_rows_composite_primary_key() -> None:
    pk_cols = {c.key for c in ResearchFeatureRow.__table__.primary_key.columns}
    assert pk_cols == {"snapshot_id", "split_version", "feature_version"}


def test_research_market_labels_composite_primary_key() -> None:
    pk_cols = {c.key for c in ResearchMarketLabel.__table__.primary_key.columns}
    assert pk_cols == {"market_ticker", "label_version"}


def test_backtest_trades_composite_primary_key() -> None:
    pk_cols = {c.key for c in BacktestTrade.__table__.primary_key.columns}
    assert pk_cols == {"run_id", "trade_index"}


def test_create_all_sqlite_memory() -> None:
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    try:
        create_all_tables(engine)
        assert EXPECTED_TABLES <= set(Base.metadata.tables.keys())
    finally:
        drop_all_tables(engine)
        engine.dispose()
