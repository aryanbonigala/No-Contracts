"""Repository helpers for shadow bucket tables."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, drop_all_tables
from kalshi_no_carry.db.repositories import (
    create_shadow_bucket_scan_run,
    fetch_unscored_shadow_bucket_entries,
    finish_shadow_bucket_scan_run,
    get_or_create_shadow_bucket_market_observation,
    has_shadow_bucket_entry,
    insert_shadow_bucket_entry,
    summarize_shadow_bucket_entries,
    update_shadow_bucket_market_observation,
)
from kalshi_no_carry.db.schema import ShadowBucketScanRun
from kalshi_no_carry.research.shadow_bucket_config import BucketShadowConfig


@pytest.fixture
def engine():
    eng = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(eng)
    yield eng
    drop_all_tables(eng)
    eng.dispose()


def test_create_and_finish_scan_run(engine) -> None:
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    cfg = BucketShadowConfig(dry_run=False)
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session() as s:
        row = create_shadow_bucket_scan_run(s, cfg, "rid-1", started)
        s.commit()
        assert row.status == "running"
        finish_shadow_bucket_scan_run(
            s,
            "rid-1",
            "success",
            summary_json={"ok": True},
            counts={
                "markets_seen": 3,
                "orderbooks_attempted": 3,
                "orderbooks_successful": 2,
                "orderbooks_failed": 1,
                "entries_inserted": 1,
                "rejections_recorded": 4,
                "fill_failures": 2,
            },
        )
        s.commit()
        r = s.get(ShadowBucketScanRun, "rid-1")
        assert r is not None
        assert r.status == "success"
        assert r.markets_seen == 3
        assert r.entries_inserted == 1


def test_observation_get_create_update(engine) -> None:
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    with Session() as s:
        o = get_or_create_shadow_bucket_market_observation(
            s,
            "sv",
            "ex",
            "MKT",
            defaults={"event_ticker": "E", "series_ticker": "S"},
        )
        s.commit()
        assert o.times_scanned == 0
        update_shadow_bucket_market_observation(s, o, {"times_scanned": 2, "last_rejection_reason": "x"})
        s.commit()
        o2 = get_or_create_shadow_bucket_market_observation(s, "sv", "ex", "MKT", {})
        assert o2.times_scanned == 2


def test_has_entry_and_fetch_unscored(engine) -> None:
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    now = datetime.now(timezone.utc)
    payload = {
        "shadow_version": "sv",
        "experiment_name": "ex",
        "scan_run_id": None,
        "bucket_price_cents": 85,
        "bucket_name": "NO_85",
        "market_ticker": "M",
        "observed_at": now,
        "contracts_requested": 5,
        "contracts_filled": 5,
        "simulated_avg_no_fill_cents": 85.0,
        "target_price_cents": 85,
        "entry_tolerance_cents": 1,
        "fill_quality": "FULL_FILL",
        "gross_cost_cents": 425,
        "fee_cents": 3,
        "net_cost_cents": 428,
        "scored": False,
        "created_at": now,
        "updated_at": now,
    }
    with Session() as s:
        insert_shadow_bucket_entry(s, payload)
        s.commit()
        assert has_shadow_bucket_entry(s, "sv", "ex", "M", 85)
        rows = fetch_unscored_shadow_bucket_entries(s, "sv")
        assert len(rows) == 1


def test_summarize_empty(engine) -> None:
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    with Session() as s:
        assert summarize_shadow_bucket_entries(s, "sv")["total_entries"] == 0
