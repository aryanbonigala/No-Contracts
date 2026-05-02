"""Integration tests for build_event_clusters_from_raw_data and assign_chronological_splits."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, drop_all_tables
from kalshi_no_carry.db.repositories import (
    count_strategy_splits,
    get_existing_strategy_splits,
    upsert_event,
    upsert_event_cluster,
    upsert_market,
    upsert_strategy_split,
)
from kalshi_no_carry.db.schema import EventCluster, StrategySplit
from kalshi_no_carry.research.build_splits import (
    SplitVersionExistsError,
    assign_chronological_splits,
    build_event_clusters_from_raw_data,
)


@pytest.fixture
def memory_engine():
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    yield engine
    drop_all_tables(engine)
    engine.dispose()


@pytest.fixture
def session_factory(memory_engine):
    return sessionmaker(memory_engine, expire_on_commit=False, future=True)


def _seed_ten_clusters(session_factory, *, prefix: str = "E") -> None:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with session_factory() as session:
        for i in range(10):
            et = f"{prefix}-{i}"
            day = base.replace(day=1 + i)
            upsert_event(
                session,
                {"event_ticker": et, "title": f"Event {i}", "series_ticker": "S", "category": "c"},
                fetched_at=day,
            )
            upsert_market(
                session,
                {"ticker": f"M-{et}", "event_ticker": et, "close_time": day.isoformat()},
                fetched_at=day,
            )
        session.commit()


def test_build_clusters_writes_event_clusters(memory_engine, session_factory) -> None:
    with session_factory() as session:
        upsert_event(
            session,
            {"event_ticker": "E0", "title": "A", "series_ticker": "S"},
            fetched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        upsert_market(
            session,
            {"ticker": "M-E0", "event_ticker": "E0", "close_time": "2024-06-01T00:00:00Z"},
            fetched_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        session.commit()

    summary = build_event_clusters_from_raw_data(memory_engine)
    assert summary["success"] is True
    assert summary["clusters_written"] == 1

    with session_factory() as session:
        rows = session.scalars(select(EventCluster)).all()
        assert len(rows) == 1
        assert rows[0].event_ticker == "E0"


def test_build_clusters_idempotent(memory_engine, session_factory) -> None:
    with session_factory() as session:
        upsert_market(
            session,
            {"ticker": "MX", "event_ticker": "EX", "close_time": "2024-06-01T00:00:00Z"},
            fetched_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        upsert_event(
            session,
            {"event_ticker": "EX", "title": "x"},
            fetched_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        session.commit()
    s1 = build_event_clusters_from_raw_data(memory_engine)
    s2 = build_event_clusters_from_raw_data(memory_engine)
    assert s1["clusters_written"] == s2["clusters_written"] == 1
    with session_factory() as session:
        n = session.scalar(select(func.count()).select_from(EventCluster))
        assert n == 1


def test_assign_chronological_split_counts(memory_engine, session_factory) -> None:
    _seed_ten_clusters(session_factory)
    build_event_clusters_from_raw_data(memory_engine)
    out = assign_chronological_splits(
        memory_engine,
        "v-test-1",
        train_fraction=0.60,
        validation_fraction=0.20,
        test_fraction=0.20,
    )
    assert out["success"] is True
    assert out["total_clusters"] == 10
    assert out["train_count"] == 6
    assert out["validation_count"] == 2
    assert out["test_count"] == 2

    with session_factory() as session:
        train_n = session.scalar(
            select(func.count()).select_from(StrategySplit).where(StrategySplit.split_name == "train")
        )
        assert train_n == 6


def test_assign_split_version_exists_raises(memory_engine, session_factory) -> None:
    _seed_ten_clusters(session_factory, prefix="S")
    build_event_clusters_from_raw_data(memory_engine)
    assign_chronological_splits(memory_engine, "v-dup", train_fraction=0.6, validation_fraction=0.2, test_fraction=0.2)
    with pytest.raises(SplitVersionExistsError):
        assign_chronological_splits(
            memory_engine,
            "v-dup",
            train_fraction=0.6,
            validation_fraction=0.2,
            test_fraction=0.2,
            overwrite=False,
        )


def test_assign_overwrite_rebuilds_same_version(memory_engine, session_factory) -> None:
    _seed_ten_clusters(session_factory, prefix="O")
    build_event_clusters_from_raw_data(memory_engine)
    assign_chronological_splits(memory_engine, "v-a", train_fraction=0.6, validation_fraction=0.2, test_fraction=0.2)
    with pytest.raises(SplitVersionExistsError):
        assign_chronological_splits(
            memory_engine,
            "v-a",
            train_fraction=0.6,
            validation_fraction=0.2,
            test_fraction=0.2,
            overwrite=False,
        )
    out = assign_chronological_splits(
        memory_engine,
        "v-a",
        train_fraction=0.6,
        validation_fraction=0.2,
        test_fraction=0.2,
        overwrite=True,
    )
    assert out["overwritten"] is True
    assert out["train_count"] == 6
    with session_factory() as s:
        assert count_strategy_splits(s, split_version="v-a") == 10


def test_assign_invalid_fractions_raises(memory_engine, session_factory) -> None:
    _seed_ten_clusters(session_factory, prefix="F")
    build_event_clusters_from_raw_data(memory_engine)
    with pytest.raises(ValueError, match="sum to 1.0"):
        assign_chronological_splits(
            memory_engine,
            "v-bad",
            train_fraction=0.5,
            validation_fraction=0.2,
            test_fraction=0.2,
        )


def test_assign_empty_clusters_warning(memory_engine, session_factory) -> None:
    out = assign_chronological_splits(
        memory_engine,
        "v-empty",
        train_fraction=0.6,
        validation_fraction=0.2,
        test_fraction=0.2,
    )
    assert out["total_clusters"] == 0
    assert out["warnings"]
    with session_factory() as s:
        assert count_strategy_splits(s, split_version="v-empty") == 0


def test_get_existing_strategy_splits_filter(session_factory) -> None:
    with session_factory() as session:
        upsert_event_cluster(session, cluster_id="a1")
        upsert_event_cluster(session, cluster_id="a2")
        upsert_strategy_split(session, cluster_id="a1", split_name="train", split_version="vx")
        upsert_strategy_split(session, cluster_id="a2", split_name="test", split_version="vy")
        session.commit()
    with session_factory() as s:
        vx = get_existing_strategy_splits(s, split_version="vx")
        assert len(vx) == 1 and vx[0].cluster_id == "a1"


def test_assign_chronological_two_versions_coexist(memory_engine, session_factory) -> None:
    _seed_ten_clusters(session_factory, prefix="TWOVER")
    build_event_clusters_from_raw_data(memory_engine)
    assign_chronological_splits(
        memory_engine,
        "version-A",
        train_fraction=0.6,
        validation_fraction=0.2,
        test_fraction=0.2,
    )
    assign_chronological_splits(
        memory_engine,
        "version-B",
        train_fraction=0.6,
        validation_fraction=0.2,
        test_fraction=0.2,
    )
    with session_factory() as s:
        assert count_strategy_splits(s, split_version="version-A") == 10
        assert count_strategy_splits(s, split_version="version-B") == 10
        total = s.scalar(select(func.count()).select_from(StrategySplit))
        assert total == 20


def test_assign_overwrite_replaces_only_requested_version(memory_engine, session_factory) -> None:
    _seed_ten_clusters(session_factory, prefix="OW")
    build_event_clusters_from_raw_data(memory_engine)
    assign_chronological_splits(
        memory_engine,
        "split-A",
        train_fraction=0.6,
        validation_fraction=0.2,
        test_fraction=0.2,
    )
    assign_chronological_splits(
        memory_engine,
        "split-B",
        train_fraction=0.6,
        validation_fraction=0.2,
        test_fraction=0.2,
    )
    assign_chronological_splits(
        memory_engine,
        "split-A",
        train_fraction=0.5,
        validation_fraction=0.25,
        test_fraction=0.25,
        overwrite=True,
    )
    with session_factory() as s:
        train_a = s.scalar(
            select(func.count())
            .select_from(StrategySplit)
            .where(StrategySplit.split_version == "split-A", StrategySplit.split_name == "train")
        )
        train_b = s.scalar(
            select(func.count())
            .select_from(StrategySplit)
            .where(StrategySplit.split_version == "split-B", StrategySplit.split_name == "train")
        )
        assert train_a == 5
        assert train_b == 6
        assert count_strategy_splits(s, split_version="split-B") == 10
