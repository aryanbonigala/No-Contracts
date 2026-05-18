"""v0.18 shadow additions: gated depth sim, dashboards, deployment hygiene."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, drop_all_tables
from kalshi_no_carry.db.repositories import (
    create_shadow_bucket_scan_run,
    finish_shadow_bucket_scan_run,
    insert_shadow_bucket_entry,
    upsert_shadow_execution_probe,
)
from kalshi_no_carry.kalshi_client import KalshiClient
from kalshi_no_carry.research.shadow_bucket_config import BucketShadowConfig
from kalshi_no_carry.research.shadow_bucket_dashboard import build_shadow_bucket_dashboard, longest_losing_streak_pnls, max_drawdown_cents
from kalshi_no_carry.research.shadow_bucket_experiment import FULL_FILL, INSUFFICIENT_DEPTH, simulate_buy_no_fill_from_yes_bids


def test_sim_respects_bucket_implied_ceiling_partial() -> None:
    yes = [(35, 10), (20, 50)]
    sim = simulate_buy_no_fill_from_yes_bids(
        yes,
        25,
        max_acceptable_implied_no_cents=71,
        allow_partial_fills=False,
    )
    assert sim.fill_quality == INSUFFICIENT_DEPTH
    assert sim.contracts_filled == 10
    assert pytest.approx(sim.avg_no_fill_cents) == 65.0


def test_sim_bucket_window_full_best_worst() -> None:
    yes = [(20, 100)]
    sim = simulate_buy_no_fill_from_yes_bids(
        yes,
        10,
        max_acceptable_implied_no_cents=82,
        allow_partial_fills=False,
    )
    assert sim.fill_quality == FULL_FILL
    assert sim.best_no_fill_cents == 80
    assert sim.worst_no_fill_cents == 80
    assert sim.contracts_unfilled == 0


def test_dashboard_dd_and_streak_helpers() -> None:
    assert max_drawdown_cents([50, -20, -10, 80, -70]) >= 70
    assert longest_losing_streak_pnls([3, -1, -5, -2, 10]) >= 3


@pytest.fixture()
def mem_engine():
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    try:
        yield engine
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_dashboard_static_bundle_writes_files(mem_engine, tmp_path: Path) -> None:
    Session = sessionmaker(mem_engine, expire_on_commit=False, future=True)
    now = datetime.now(timezone.utc)
    with Session() as s:
        cfg = BucketShadowConfig(shadow_version="svdash", experiment_name="expdash", bucket_prices_cents=(85,))
        create_shadow_bucket_scan_run(s, cfg, "probe-run", now)
        finish_shadow_bucket_scan_run(
            s,
            "probe-run",
            "success",
            summary_json={"markets_seen": 2},
            counts={
                "markets_seen": 2,
                "orderbooks_attempted": 2,
                "orderbooks_successful": 2,
                "orderbooks_failed": 0,
                "entries_inserted": 1,
                "rejections_recorded": 0,
                "fill_failures": 0,
            },
        )
        insert_shadow_bucket_entry(
            s,
            {
                "shadow_version": "svdash",
                "experiment_name": "expdash",
                "scan_run_id": "probe-run",
                "bucket_price_cents": 85,
                "bucket_name": "NO_85",
                "market_ticker": "M1",
                "observed_at": now,
                "contracts_requested": 10,
                "contracts_filled": 10,
                "contracts_unfilled": 0,
                "simulated_avg_no_fill_cents": 85.0,
                "target_price_cents": 85,
                "entry_tolerance_cents": 1,
                "fill_quality": "FULL_FILL",
                "gross_cost_cents": 850,
                "fee_cents": 5,
                "net_cost_cents": 855,
                "scored": True,
                "gross_pnl_cents": 150,
                "net_pnl_cents": 100,
                "fee_drag_cents": 50,
                "eligible_depth_contracts": 999,
                "best_no_fill_cents": 85,
                "created_at": now,
                "updated_at": now,
            },
        )
        upsert_shadow_execution_probe(
            s,
            {
                "scan_run_id": "probe-run",
                "shadow_version": "svdash",
                "experiment_name": "expdash",
                "market_ticker": "M1",
                "bucket_price_cents": 85,
                "observed_at": now,
                "close_time": None,
                "seconds_to_close": None,
                "event_ticker": None,
                "series_ticker": None,
                "category": None,
                "title": None,
                "contracts_requested": 10,
                "contracts_filled": 10,
                "contracts_unfilled": 0,
                "eligible_depth_contracts": 999,
                "avg_no_fill_cents": 85.0,
                "best_no_fill_cents": 85,
                "worst_no_fill_cents": 85,
                "target_price_cents": 85,
                "entry_tolerance_cents": 1,
                "slippage_cents": 0.0,
                "fill_quality": "FULL_FILL",
                "gross_cost_cents": 850,
                "fee_cents": 5,
                "skip_failure_reason": None,
                "linked_entry_id": None,
                "created_at": now,
                "updated_at": now,
            },
        )
        s.commit()

    out = tmp_path / "dash"
    with Session() as s:
        summary = build_shadow_bucket_dashboard(
            s,
            shadow_version="svdash",
            experiment_name="expdash",
            buckets=(85,),
            output_dir=out,
            scan_run_id="probe-run",
            overwrite=False,
            include_unsettled=True,
            min_settled_sample_warning=1,
        )

    for name in (
        "index.html",
        "dashboard_summary.json",
        "bucket_metrics.csv",
        "market_drilldown.csv",
        "category_metrics.csv",
        "cluster_risk.csv",
        "execution_quality.csv",
    ):
        assert (out / name).is_file()

    dj = json.loads((out / "dashboard_summary.json").read_text(encoding="utf-8"))
    assert dj["dashboard_version_meta"]["shadow_version"] == "svdash"
    assert summary["total_virtual_entries_loaded"] >= 1


def test_duckdns_script_does_not_echo_secret_substring() -> None:
    ROOT = Path(__file__).resolve().parents[1]
    text = (ROOT / "deploy" / "dashboard" / "duckdns_update.sh").read_text(encoding="utf-8")
    for ln in text.splitlines():
        st = ln.strip()
        if st.startswith("echo ") and "${DUCKDNS_TOKEN}" in ln:
            raise AssertionError("token echo pattern present")


def test_kalshi_public_client_docs_reiterate_read_only() -> None:
    doc = KalshiClient.__doc__ or ""
    assert "read-only".lower() in doc.lower()

