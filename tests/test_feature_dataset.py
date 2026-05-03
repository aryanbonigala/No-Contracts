"""Feature row building and join query behavior (SQLite)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.database import create_all_tables, drop_all_tables
from kalshi_no_carry.db.repositories import (
    bulk_upsert_research_feature_rows,
    count_research_feature_rows,
    delete_research_feature_rows_for_version,
    insert_orderbook_snapshot,
    list_orderbook_snapshots_for_feature_building,
    upsert_event,
    upsert_event_cluster,
    upsert_market,
    upsert_research_feature_row,
    upsert_strategy_split,
)
from kalshi_no_carry.research.feature_dataset import build_feature_row_from_joined_record, validate_feature_row


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


def _seed_fixed(session_factory, *, split_name: str = "train", result: str | None = None) -> None:
    day = datetime(2024, 6, 15, 15, 0, 0, tzinfo=timezone.utc)
    close = datetime(2024, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    with session_factory() as s:
        upsert_event(
            s,
            {"event_ticker": "EVT-X", "title": "Event X", "series_ticker": "S", "category": "pol"},
            fetched_at=day,
        )
        mkwargs = {
            "ticker": "MKT-X",
            "event_ticker": "EVT-X",
            "series_ticker": "S",
            "title": "Market X",
            "close_time": close.isoformat(),
            "status": "open",
        }
        if result is not None:
            mkwargs["result"] = result
        upsert_market(s, mkwargs, fetched_at=day)
        upsert_event_cluster(
            s,
            cluster_id="cl-evt-x",
            cluster_key="event_ticker:EVT-X",
            event_ticker="EVT-X",
            series_ticker="S",
            representative_title="Rep X",
            close_time=close,
        )
        upsert_strategy_split(s, cluster_id="cl-evt-x", split_name=split_name, split_version="sv1")
        book = {"yes": [{"price": 50, "count": 10}], "no": [{"price": 48, "count": 10}]}
        insert_orderbook_snapshot(
            s,
            "MKT-X",
            book,
            executable_prices={
                "best_yes_bid_cents": 45,
                "best_yes_ask_cents": 55,
                "best_no_bid_cents": 44,
                "best_no_ask_cents": 56,
                "best_yes_bid_size": 10,
                "best_yes_ask_size": 10,
                "best_no_bid_size": 10,
                "best_no_ask_size": 10,
            },
        )
        s.commit()


def test_joined_query_excludes_test_by_default(session_factory) -> None:
    _seed_fixed(session_factory, split_name="test")
    with session_factory() as s:
        rows = list_orderbook_snapshots_for_feature_building(
            s, split_version="sv1", include_splits=("train", "validation", "test"), include_test=False
        )
        assert rows == []


def test_joined_query_include_test(session_factory) -> None:
    _seed_fixed(session_factory, split_name="test")
    with session_factory() as s:
        rows = list_orderbook_snapshots_for_feature_building(
            s, split_version="sv1", include_splits=("test",), include_test=True
        )
        assert len(rows) == 1
        assert rows[0].split.split_name == "test"


def test_feature_row_versions_persist_and_coexist(session_factory) -> None:
    _seed_fixed(session_factory, split_name="train")
    with session_factory() as s:
        src = list_orderbook_snapshots_for_feature_building(s, split_version="sv1")[0]
        r1 = build_feature_row_from_joined_record(src, feature_version="fv1")
        r2 = build_feature_row_from_joined_record(src, feature_version="fv2")
        assert validate_feature_row(r1) == []
        upsert_research_feature_row(s, r1)
        upsert_research_feature_row(s, r2)
        s.commit()
    with session_factory() as s:
        assert count_research_feature_rows(s, split_version="sv1", feature_version="fv1") == 1
        assert count_research_feature_rows(s, split_version="sv1", feature_version="fv2") == 1


def test_two_split_versions_same_snapshot(session_factory) -> None:
    _seed_fixed(session_factory, split_name="train")
    with session_factory() as s:
        upsert_strategy_split(s, cluster_id="cl-evt-x", split_name="train", split_version="sv2")
        s.commit()
    with session_factory() as s:
        src_a = list_orderbook_snapshots_for_feature_building(s, split_version="sv1")[0]
        src_b = list_orderbook_snapshots_for_feature_building(s, split_version="sv2")[0]
        ra = build_feature_row_from_joined_record(src_a, feature_version="fv")
        rb = build_feature_row_from_joined_record(src_b, feature_version="fv")
        bulk_upsert_research_feature_rows(s, [ra, rb])
        s.commit()
    with session_factory() as s:
        assert count_research_feature_rows(s, feature_version="fv") == 2


def test_delete_research_feature_rows_for_version_scoped(session_factory) -> None:
    _seed_fixed(session_factory, split_name="train")
    with session_factory() as s:
        src = list_orderbook_snapshots_for_feature_building(s, split_version="sv1")[0]
        a = build_feature_row_from_joined_record(src, feature_version="fvA")
        b = build_feature_row_from_joined_record(src, feature_version="fvB")
        bulk_upsert_research_feature_rows(s, [a, b])
        s.commit()
    with session_factory() as s:
        n = delete_research_feature_rows_for_version(s, split_version="sv1", feature_version="fvA")
        s.commit()
        assert n == 1
        assert count_research_feature_rows(s, split_version="sv1", feature_version="fvB") == 1


def test_label_prefix_on_row(session_factory) -> None:
    _seed_fixed(session_factory, split_name="train", result="yes")
    with session_factory() as s:
        src = list_orderbook_snapshots_for_feature_building(s, split_version="sv1")[0]
        row = build_feature_row_from_joined_record(src, feature_version="fv")
        assert row.label_market_result == "yes"
