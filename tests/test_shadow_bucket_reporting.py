"""Reporting aggregates for shadow buckets."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, drop_all_tables
from kalshi_no_carry.db.repositories import insert_shadow_bucket_entry
from kalshi_no_carry.research.shadow_bucket_reporting import build_shadow_bucket_report


def test_report_empty_creates_files(tmp_path) -> None:
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    try:
        with Session() as s:
            out = build_shadow_bucket_report(
                s,
                shadow_version="sv",
                experiment_name="ex",
                report_name="t1",
                output_dir=tmp_path / "t1",
                min_scored_sample=1,
            )
        assert (tmp_path / "t1" / "shadow_bucket_report.json").is_file()
        assert "paths" in out
        md = (tmp_path / "t1" / "shadow_bucket_report.md").read_text(encoding="utf-8")
        assert "NO Bucket Shadow Experiment Report" in md
        assert "| Bucket |" in md
        js = json.loads((tmp_path / "t1" / "shadow_bucket_report.json").read_text(encoding="utf-8"))
        for bk in ("60", "70", "80", "85", "90", "95"):
            assert bk in js["buckets"]
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_report_drawdown_and_diagnosis(tmp_path) -> None:
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    now = datetime.now(timezone.utc)
    try:
        with Session() as s:
            for i, net in enumerate([50, -10, 40], start=1):
                insert_shadow_bucket_entry(
                    s,
                    {
                        "shadow_version": "sv",
                        "experiment_name": "ex",
                        "scan_run_id": None,
                        "bucket_price_cents": 85,
                        "bucket_name": "NO_85",
                        "market_ticker": f"M{i}",
                        "observed_at": now,
                        "contracts_requested": 10,
                        "contracts_filled": 10,
                        "simulated_avg_no_fill_cents": 85.0,
                        "target_price_cents": 85,
                        "entry_tolerance_cents": 1,
                        "fill_quality": "FULL_FILL",
                        "gross_cost_cents": 50,
                        "fee_cents": 1,
                        "net_cost_cents": 51,
                        "scored": True,
                        "gross_pnl_cents": net + 1,
                        "net_pnl_cents": net,
                        "fee_drag_cents": 1,
                        "no_spread_cents": 2,
                        "seconds_to_close": 600,
                        "slippage_cents": 0.0,
                        "result_category": "X",
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            s.commit()
        with Session() as s:
            build_shadow_bucket_report(
                s,
                shadow_version="sv",
                experiment_name="ex",
                report_name="t2",
                output_dir=tmp_path / "t2",
                min_scored_sample=1,
            )
        data = json.loads((tmp_path / "t2" / "shadow_bucket_report.json").read_text(encoding="utf-8"))
        b85 = data["buckets"]["85"]
        assert b85["max_drawdown_cents"] >= 10
        assert b85["longest_loss_streak"] >= 1
    finally:
        drop_all_tables(engine)
        engine.dispose()
