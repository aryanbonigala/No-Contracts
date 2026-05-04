"""Tests for orderbook price extraction audit (read-only)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.database import create_all_tables, drop_all_tables, create_engine_from_database_url
from kalshi_no_carry.db.repositories import (
    insert_orderbook_snapshot,
    upsert_event,
    upsert_event_cluster,
    upsert_market,
    upsert_research_feature_row,
    upsert_strategy_split,
    list_orderbook_snapshots_for_feature_building,
)
from kalshi_no_carry.research.feature_dataset import build_feature_row_from_joined_record
from kalshi_no_carry.research.orderbook_audit import audit_orderbook_price_extraction


def test_audit_counts_snapshots_and_derives_no_ask() -> None:
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    try:
        day = datetime(2024, 6, 15, 15, 0, 0, tzinfo=timezone.utc)
        close = datetime(2024, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
        book = {
            "orderbook_fp": {
                "yes_dollars": [["0.3500", "10"]],
                "no_dollars": [["0.5500", "20"]],
            }
        }
        with Session() as s:
            insert_orderbook_snapshot(s, "M-X", book)
            s.commit()

        r = audit_orderbook_price_extraction(engine, limit=10)
        assert r["success"] is True
        c = r["counts"]
        assert c["snapshots_seen"] == 1
        assert c["snapshots_with_raw_json"] == 1
        assert c["snapshots_with_nonempty_yes_book"] == 1
        assert c["snapshots_with_executable_no_ask"] == 1
        assert c["rows_derived_no_ask_present"] == 1
        assert c["snapshots_empty_both_sides"] == 0
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_audit_empty_both_sides() -> None:
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    try:
        book = {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}
        with Session() as s:
            insert_orderbook_snapshot(s, "M-E", book)
            s.commit()
        r = audit_orderbook_price_extraction(engine)
        c = r["counts"]
        assert c["snapshots_seen"] == 1
        assert c["snapshots_empty_both_sides"] == 1
        assert c["snapshots_with_executable_no_ask"] == 0
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_audit_unrecognized_shape_sample() -> None:
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    try:
        with Session() as s:
            insert_orderbook_snapshot(s, "M-BAD", {"unexpected": 1})
            s.commit()
        r = audit_orderbook_price_extraction(engine, max_shape_samples=3)
        assert r["counts"]["snapshots_unrecognized_shape"] >= 1
        assert r["shape_samples"]
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_audit_feature_mismatch_raw_has_no_ask_feature_missing() -> None:
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    try:
        day = datetime(2024, 6, 15, 15, 0, 0, tzinfo=timezone.utc)
        close = datetime(2024, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
        book = {
            "orderbook_fp": {
                "yes_dollars": [["0.4000", "5"]],
                "no_dollars": [["0.3000", "8"]],
            }
        }
        with Session() as s:
            upsert_event(s, {"event_ticker": "EVT-1", "title": "t"}, fetched_at=day)
            upsert_market(
                s,
                {
                    "ticker": "M-J",
                    "event_ticker": "EVT-1",
                    "close_time": close.isoformat(),
                    "status": "open",
                },
                fetched_at=day,
            )
            upsert_event_cluster(
                s,
                cluster_id="cl-1",
                cluster_key="event_ticker:EVT-1",
                event_ticker="EVT-1",
                close_time=close,
            )
            upsert_strategy_split(s, cluster_id="cl-1", split_name="train", split_version="sv1")
            insert_orderbook_snapshot(s, "M-J", book)
            s.commit()
            src = list_orderbook_snapshots_for_feature_building(
                s, split_version="sv1", include_splits=("train",), include_test=False
            )[0]
            row = build_feature_row_from_joined_record(src, feature_version="fv1")
            row.no_ask_cents = None
            row.best_no_ask_cents = None
            row.has_complete_executable_prices = False
            upsert_research_feature_row(s, row)
            s.commit()

        r = audit_orderbook_price_extraction(
            engine,
            split_version="sv1",
            feature_version="fv1",
        )
        assert r["counts"]["feature_raw_executable_no_ask_feature_missing_no_ask"] >= 1
    finally:
        drop_all_tables(engine)
        engine.dispose()
