"""Pipeline CLI wiring for market statuses (offline)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def test_run_pipeline_script_passes_market_status_tuples() -> None:
    spec = importlib.util.spec_from_file_location("run_pipe", ROOT / "scripts" / "run_research_pipeline.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    captured: dict = {}

    def grab(engine, cfg, kalshi_client=None):
        captured["market_statuses"] = cfg.market_statuses
        captured["collect_status_set"] = cfg.collect_status_set
        captured["orderbook_source_status"] = cfg.orderbook_source_status
        return {
            "success": True,
            "warnings": [],
            "stages": {},
            "high_level_counts": {},
            "audit_summary": None,
            "backtest_summary": None,
            "failed_stage": None,
            "next_recommended_action": "",
            "pipeline_version": "",
            "split_version": "",
            "feature_version": "",
            "label_version": "",
            "backtest_version": "",
            "include_test": False,
        }

    engine = MagicMock()
    engine.dispose = MagicMock()
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch("kalshi_no_carry.research.pipeline_runner.run_research_pipeline", side_effect=grab):
                    mod.main(
                        [
                            "--market-status",
                            "open",
                            "--market-status",
                            "settled",
                            "--collect-status-set",
                            "active_and_resolved",
                            "--orderbook-source-status",
                            "open",
                        ]
                    )
    assert captured["market_statuses"] == ("open", "settled")
    assert captured["collect_status_set"] == "active_and_resolved"
    assert captured["orderbook_source_status"] == "open"


def test_resolve_requested_market_statuses_expansion() -> None:
    from kalshi_no_carry.research.pipeline_runner import resolve_requested_market_statuses

    assert resolve_requested_market_statuses(market_statuses=(), collect_status_set=None) is None
    assert resolve_requested_market_statuses(market_statuses=("settled",), collect_status_set=None) == ("settled",)
    assert resolve_requested_market_statuses(market_statuses=(), collect_status_set="active_and_resolved") == (
        "open",
        "settled",
    )
    assert resolve_requested_market_statuses(market_statuses=(), collect_status_set="all_basic") == (
        "open",
        "closed",
        "settled",
    )
    assert resolve_requested_market_statuses(
        market_statuses=("closed",),
        collect_status_set="active_and_resolved",
    ) == ("open", "settled", "closed")


def test_research_pipeline_config_rejects_bad_collect_status_set() -> None:
    import pytest

    from kalshi_no_carry.research.pipeline_runner import ResearchPipelineConfig

    with pytest.raises(ValueError):
        ResearchPipelineConfig(collect_status_set="not_a_real_preset")
