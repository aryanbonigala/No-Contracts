"""CLI tests for scripts/run_research_pipeline.py."""

from __future__ import annotations

import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def test_run_pipeline_exits_without_database_url() -> None:
    spec = importlib.util.spec_from_file_location("run_research_pipeline_cli", ROOT / "scripts" / "run_research_pipeline.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=None)):
        spec.loader.exec_module(mod)
        out = StringIO()
        with patch("sys.stdout", out):
            rc = mod.main([])
    assert rc == 2
    assert json.loads(out.getvalue())["success"] is False


def test_run_pipeline_does_not_print_database_url() -> None:
    secret = "NEVERLEAK825"
    url = f"sqlite+pysqlite:///{secret}_db.sqlite"
    spec = importlib.util.spec_from_file_location("run_research_pipeline_cli", ROOT / "scripts" / "run_research_pipeline.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    engine = MagicMock()
    engine.dispose = MagicMock()
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=url)):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                fake_summary = {
                    "success": True,
                    "pipeline_version": "v0.9_research_pipeline_runner",
                    "warnings": [],
                    "stages": {},
                    "high_level_counts": {},
                    "audit_summary": None,
                    "backtest_summary": None,
                    "failed_stage": None,
                    "next_recommended_action": "ok",
                    "split_version": "",
                    "feature_version": "",
                    "label_version": "",
                    "backtest_version": "",
                    "include_test": False,
                }
                with patch("kalshi_no_carry.research.pipeline_runner.run_research_pipeline", return_value=fake_summary):
                    log = StringIO()
                    with patch("sys.stdout", log):
                        rc = mod.main([])
    assert rc == 0
    text = log.getvalue()
    assert secret not in text
    assert url not in text


def test_run_pipeline_default_does_not_enable_collection() -> None:
    spec = importlib.util.spec_from_file_location("run_research_pipeline_cli", ROOT / "scripts" / "run_research_pipeline.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    engine = MagicMock()
    engine.dispose = MagicMock()
    seen: dict = {}

    def capture(engine, cfg, kalshi_client=None):
        seen["collect_markets"] = cfg.collect_markets
        seen["collect_orderbooks"] = cfg.collect_orderbooks
        return {
            "success": True,
            "warnings": [],
            "stages": {},
            "high_level_counts": {},
            "failed_stage": None,
            "next_recommended_action": "",
            "pipeline_version": "",
            "split_version": "",
            "feature_version": "",
            "label_version": "",
            "backtest_version": "",
            "include_test": False,
            "audit_summary": None,
            "backtest_summary": None,
        }

    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch("kalshi_no_carry.research.pipeline_runner.run_research_pipeline", side_effect=capture):
                    mod.main([])
    assert seen["collect_markets"] is False
    assert seen["collect_orderbooks"] is False


def test_run_pipeline_run_backtest_flag() -> None:
    spec = importlib.util.spec_from_file_location("run_research_pipeline_cli", ROOT / "scripts" / "run_research_pipeline.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    engine = MagicMock()
    engine.dispose = MagicMock()
    seen: dict = {}

    def capture(engine, cfg, kalshi_client=None):
        seen["run_backtest"] = cfg.run_backtest
        return {
            "success": True,
            "warnings": [],
            "stages": {},
            "high_level_counts": {},
            "audit_summary": None,
            "backtest_summary": {},
            "failed_stage": None,
            "next_recommended_action": "",
            "pipeline_version": "",
            "split_version": "",
            "feature_version": "",
            "label_version": "",
            "backtest_version": "",
            "include_test": False,
        }

    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch("kalshi_no_carry.research.pipeline_runner.run_research_pipeline", side_effect=capture):
                    mod.main(["--run-backtest", "--skip-splits", "--skip-labels", "--skip-features", "--skip-audit"])
    assert seen["run_backtest"] is True


def test_run_pipeline_collect_max_pages_flag() -> None:
    spec = importlib.util.spec_from_file_location("run_research_pipeline_cli", ROOT / "scripts" / "run_research_pipeline.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    engine = MagicMock()
    engine.dispose = MagicMock()
    seen: dict = {}

    def capture(engine, cfg, kalshi_client=None):
        seen["collect_max_pages"] = cfg.collect_max_pages
        return {
            "success": True,
            "warnings": [],
            "stages": {},
            "high_level_counts": {},
            "audit_summary": None,
            "backtest_summary": {},
            "failed_stage": None,
            "next_recommended_action": "",
            "pipeline_version": "",
            "split_version": "",
            "feature_version": "",
            "label_version": "",
            "backtest_version": "",
            "include_test": False,
        }

    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch("kalshi_no_carry.research.pipeline_runner.run_research_pipeline", side_effect=capture):
                    mod.main(["--collect-max-pages", "12"])
    assert seen["collect_max_pages"] == 12


def test_run_pipeline_refresh_lifecycle_enables_kalshi_client() -> None:
    spec = importlib.util.spec_from_file_location("run_research_pipeline_cli", ROOT / "scripts" / "run_research_pipeline.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    engine = MagicMock()
    engine.dispose = MagicMock()
    seen: dict = {}

    def capture(engine, cfg, kalshi_client=None):
        seen["has_client"] = kalshi_client is not None
        return {
            "success": True,
            "warnings": [],
            "stages": {},
            "high_level_counts": {},
            "audit_summary": None,
            "backtest_summary": {},
            "failed_stage": None,
            "next_recommended_action": "",
            "pipeline_version": "",
            "split_version": "",
            "feature_version": "",
            "label_version": "",
            "backtest_version": "",
            "include_test": False,
        }

    fake_client = MagicMock()
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch("kalshi_no_carry.kalshi_client.KalshiClient.from_settings", return_value=fake_client):
                    with patch("kalshi_no_carry.research.pipeline_runner.run_research_pipeline", side_effect=capture):
                        mod.main(
                            [
                                "--refresh-lifecycle-markets",
                                "--skip-splits",
                                "--skip-labels",
                                "--skip-features",
                                "--skip-audit",
                            ]
                        )
    assert seen["has_client"] is True
