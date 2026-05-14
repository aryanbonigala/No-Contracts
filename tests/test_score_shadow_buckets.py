"""Scoring logic for shadow bucket entries."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, drop_all_tables
from kalshi_no_carry.db.repositories import insert_shadow_bucket_entry
from kalshi_no_carry.db.schema import RawMarket, ResearchMarketLabel, ShadowBucketEntry
from kalshi_no_carry.research.score_shadow_buckets import (
    LOST_RESOLVED_YES,
    MARKET_NOT_RESOLVED,
    UNRESOLVED,
    WIN_AFTER_FEES,
    score_shadow_bucket_entries,
)


def _entry_payload(market_ticker: str) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "shadow_version": "sv1",
        "experiment_name": "ex1",
        "scan_run_id": None,
        "bucket_price_cents": 85,
        "bucket_name": "NO_85",
        "market_ticker": market_ticker,
        "observed_at": now,
        "contracts_requested": 10,
        "contracts_filled": 10,
        "simulated_avg_no_fill_cents": 85.0,
        "target_price_cents": 85,
        "entry_tolerance_cents": 1,
        "fill_quality": "FULL_FILL",
        "gross_cost_cents": 850,
        "fee_cents": 5,
        "net_cost_cents": 855,
        "scored": False,
        "created_at": now,
        "updated_at": now,
    }


def _raw(mt: str, **payload) -> RawMarket:
    now = datetime.now(timezone.utc)
    base = {"ticker": mt, "status": "finalized"}
    base.update(payload)
    return RawMarket(
        market_ticker=mt,
        raw_json=base,
        first_seen_at=now,
        last_seen_at=now,
        fetched_at=now,
    )


def test_no_win_positive_net_pnl() -> None:
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    try:
        with Session() as s:
            insert_shadow_bucket_entry(s, _entry_payload("M1"))
            s.add(_raw("M1", result="no"))
            s.commit()
            summ = score_shadow_bucket_entries(s, "sv1")
            s.commit()
            assert summ["entries_scored"] == 1
            row = s.execute(select(ShadowBucketEntry)).scalar_one()
            assert row.result_category == WIN_AFTER_FEES
            assert int(row.net_pnl_cents or 0) > 0
            assert int(row.fee_drag_cents or 0) == int(row.gross_pnl_cents or 0) - int(row.net_pnl_cents or 0)
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_yes_win_lost_category() -> None:
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    try:
        with Session() as s:
            insert_shadow_bucket_entry(s, _entry_payload("M2"))
            s.add(_raw("M2", result="yes"))
            s.commit()
            score_shadow_bucket_entries(s, "sv1")
            s.commit()
            row = s.execute(select(ShadowBucketEntry)).scalar_one()
            assert row.result_category == LOST_RESOLVED_YES
            assert int(row.net_pnl_cents or 0) < 0
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_unresolved_stays_unscored() -> None:
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    try:
        with Session() as s:
            insert_shadow_bucket_entry(s, _entry_payload("M3"))
            s.add(
                RawMarket(
                    market_ticker="M3",
                    raw_json={"ticker": "M3", "status": "open"},
                    first_seen_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc),
                    fetched_at=datetime.now(timezone.utc),
                )
            )
            s.commit()
            score_shadow_bucket_entries(s, "sv1")
            s.commit()
            row = s.execute(select(ShadowBucketEntry)).scalar_one()
            assert row.scored is False
            assert row.result_category == UNRESOLVED
            assert row.unscored_reason == MARKET_NOT_RESOLVED
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_label_version_prefers_table() -> None:
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    try:
        with Session() as s:
            insert_shadow_bucket_entry(s, _entry_payload("M4"))
            s.add(_raw("M4", status="open", result="yes"))
            s.add(
                ResearchMarketLabel(
                    market_ticker="M4",
                    label_version="lvx",
                    label_market_result="no",
                    label_no_won=True,
                    label_yes_won=False,
                    label_is_resolved=True,
                    label_is_void=False,
                    label_confidence="high",
                    extracted_at=datetime.now(timezone.utc),
                    created_at=datetime.now(timezone.utc),
                )
            )
            s.commit()
            score_shadow_bucket_entries(s, "sv1", label_version="lvx")
            s.commit()
            row = s.execute(select(ShadowBucketEntry)).scalar_one()
            assert row.result_category == WIN_AFTER_FEES
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_limit_respected() -> None:
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    try:
        with Session() as s:
            insert_shadow_bucket_entry(s, _entry_payload("MA"))
            insert_shadow_bucket_entry(s, _entry_payload("MB"))
            s.add(_raw("MA", result="no"))
            s.add(
                RawMarket(
                    market_ticker="MB",
                    raw_json={"ticker": "MB", "status": "open"},
                    first_seen_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc),
                    fetched_at=datetime.now(timezone.utc),
                )
            )
            s.commit()
            score_shadow_bucket_entries(s, "sv1", limit=1)
            s.commit()
            scored_n = s.scalar(select(func.count()).select_from(ShadowBucketEntry).where(ShadowBucketEntry.scored.is_(True)))
            unscored_n = s.scalar(select(func.count()).select_from(ShadowBucketEntry).where(ShadowBucketEntry.scored.is_(False)))
            assert scored_n == 1
            assert unscored_n == 1
    finally:
        drop_all_tables(engine)
        engine.dispose()
