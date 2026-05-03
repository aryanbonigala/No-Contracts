"""Dataset audit metrics (v0.8)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.database import create_all_tables, drop_all_tables
from kalshi_no_carry.db.repositories import (
    insert_orderbook_snapshot,
    list_orderbook_snapshots_for_feature_building,
    upsert_event,
    upsert_event_cluster,
    upsert_market,
    upsert_research_feature_row,
    upsert_strategy_split,
)
from kalshi_no_carry.research.feature_dataset import build_feature_row_from_joined_record, validate_feature_row
from kalshi_no_carry.research.dataset_audit import audit_research_dataset


@pytest.fixture
def memory_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_all_tables(engine)
    yield engine
    drop_all_tables(engine)
    engine.dispose()


@pytest.fixture
def session_factory(memory_engine):
    return sessionmaker(memory_engine, expire_on_commit=False, future=True)


def test_audit_excludes_test_by_default_warning(memory_engine) -> None:
    out = audit_research_dataset(
        memory_engine,
        split_version="sv1",
        feature_version="fv1",
        include_test=False,
    )
    assert out["research_feature_rows_count"] == 0
    assert any("TEST_SPLIT_EXCLUDED" in w for w in out["warnings"])


def test_audit_include_test_no_sealed_warning(memory_engine) -> None:
    out = audit_research_dataset(
        memory_engine,
        split_version="sv1",
        feature_version="fv1",
        include_test=True,
    )
    assert not any("TEST_SPLIT_EXCLUDED" in w for w in out["warnings"])


def test_audit_feature_counts_and_labels(session_factory, memory_engine) -> None:
    day = datetime(2024, 6, 15, 15, 0, 0, tzinfo=timezone.utc)
    close = datetime(2024, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    with session_factory() as s:
        upsert_event(s, {"event_ticker": "EVA", "title": "E"}, fetched_at=day)
        upsert_market(
            s,
            {
                "ticker": "MKA",
                "event_ticker": "EVA",
                "close_time": close.isoformat(),
                "result": "no",
            },
            fetched_at=day,
        )
        upsert_event_cluster(
            s,
            cluster_id="cl-a",
            cluster_key="event_ticker:EVA",
            event_ticker="EVA",
            close_time=close,
        )
        upsert_strategy_split(s, cluster_id="cl-a", split_name="train", split_version="sv1")
        insert_orderbook_snapshot(
            s,
            "MKA",
            {"yes": [], "no": []},
            executable_prices={
                "best_yes_bid_cents": 40,
                "best_yes_ask_cents": 60,
                "best_no_bid_cents": 40,
                "best_no_ask_cents": 60,
                "best_yes_bid_size": 1,
                "best_yes_ask_size": 1,
                "best_no_bid_size": 1,
                "best_no_ask_size": 1,
            },
        )
        s.commit()
    with session_factory() as s:
        src = list_orderbook_snapshots_for_feature_building(s, split_version="sv1")[0]
        row = build_feature_row_from_joined_record(src, feature_version="fv1")
        assert validate_feature_row(row) == []
        upsert_research_feature_row(s, row)
        s.commit()

    out = audit_research_dataset(
        memory_engine,
        split_version="sv1",
        feature_version="fv1",
        include_test=False,
    )
    assert out["research_feature_rows_count"] == 1
    assert out["feature_rows_with_complete_prices"] == 1
    assert out["feature_rows_by_split"]["train"] == 1
    assert out["resolved_no_count"] == 1
