"""Shadow bucket ORM + SQLite DDL smoke tests."""

from __future__ import annotations

from sqlalchemy import inspect

from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, drop_all_tables
from kalshi_no_carry.db.schema import Base, ShadowBucketEntry


def test_shadow_bucket_tables_in_metadata() -> None:
    names = set(Base.metadata.tables.keys())
    assert "shadow_bucket_scan_runs" in names
    assert "shadow_bucket_entries" in names
    assert "shadow_bucket_market_observations" in names
    assert "shadow_bucket_execution_probes" in names





def test_create_all_sqlite_has_shadow_tables() -> None:
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    try:
        create_all_tables(engine)
        insp = inspect(engine)
        t = set(insp.get_table_names())
        assert "shadow_bucket_entries" in t
        pk = insp.get_pk_constraint("shadow_bucket_entries")
        assert pk["constrained_columns"] == ["id"]
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_unique_constraint_market_bucket() -> None:
    from sqlalchemy.orm import sessionmaker

    from kalshi_no_carry.db.repositories import insert_shadow_bucket_entry
    from datetime import datetime, timezone

    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    try:
        now = datetime.now(timezone.utc)
        base = {
            "shadow_version": "vtest",
            "experiment_name": "e1",
            "scan_run_id": "r1",
            "bucket_price_cents": 85,
            "bucket_name": "NO_85",
            "market_ticker": "M1",
            "observed_at": now,
            "contracts_requested": 10,
            "contracts_filled": 10,
            "contracts_unfilled": 0,
            "eligible_depth_contracts": 500,
            "best_no_fill_cents": 85,
            "simulated_avg_no_fill_cents": 85.0,
            "target_price_cents": 85,
            "entry_tolerance_cents": 1,
            "fill_quality": "FULL_FILL",
            "gross_cost_cents": 850,
            "fee_cents": 10,
            "net_cost_cents": 860,
            "scored": False,
            "created_at": now,
            "updated_at": now,
        }
        with Session() as s:
            assert insert_shadow_bucket_entry(s, base) is not None
            assert insert_shadow_bucket_entry(s, dict(base)) is None
            s.commit()
    finally:
        drop_all_tables(engine)
        engine.dispose()
