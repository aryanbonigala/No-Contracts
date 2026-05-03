"""CLI tests for scripts/run_research_report.py."""

from __future__ import annotations

import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def test_run_research_report_exits_without_database_url() -> None:
    spec = importlib.util.spec_from_file_location("run_rr", ROOT / "scripts" / "run_research_report.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=None)):
        spec.loader.exec_module(mod)
        out = StringIO()
        with patch("sys.stdout", out):
            rc = mod.main([])
    assert rc == 2
    assert json.loads(out.getvalue())["success"] is False


def test_run_research_report_does_not_print_database_url(tmp_path: Path) -> None:
    secret = "NEVERLEAK918"
    url = f"sqlite+pysqlite:///{secret}_db.sqlite"
    spec = importlib.util.spec_from_file_location("run_rr", ROOT / "scripts" / "run_research_report.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    fake_pipe = {
        "success": True,
        "failed_stage": None,
        "pipeline_version": "p",
        "split_version": "s",
        "feature_version": "f",
        "label_version": "l",
        "backtest_version": "b",
        "include_test": False,
        "warnings": [],
        "stages": {"audit": {"enabled": True, "success": True}},
        "audit_summary": {"raw_markets_count": 1},
        "backtest_summary": None,
        "high_level_counts": {},
        "next_recommended_action": "x",
    }
    engine = MagicMock()
    engine.dispose = MagicMock()
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=url)):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch(
                    "kalshi_no_carry.research.pipeline_runner.run_research_pipeline",
                    return_value=fake_pipe,
                ):
                    log = StringIO()
                    with patch("sys.stdout", log):
                        rc = mod.main(["--report-name", "t1", "--output-dir", str(tmp_path)])
    assert rc == 0
    text = log.getvalue()
    assert secret not in text
    assert url not in text


def test_run_research_report_writes_files(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("run_rr", ROOT / "scripts" / "run_research_report.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    fake_pipe = {
        "success": True,
        "failed_stage": None,
        "pipeline_version": "p",
        "split_version": "s",
        "feature_version": "f",
        "label_version": "l",
        "backtest_version": "b",
        "include_test": False,
        "warnings": [],
        "stages": {},
        "audit_summary": {
            "raw_markets_count": 1,
            "raw_orderbook_snapshots_count": 1,
            "event_clusters_count": 1,
            "strategy_splits_count": 1,
            "market_labels_count": 1,
            "research_feature_rows_count": 200,
            "scorable_feature_rows": 120,
            "feature_rows_with_label": 150,
            "feature_rows_by_split": {"train": 100, "validation": 100},
        },
        "backtest_summary": None,
        "high_level_counts": {},
        "next_recommended_action": "x",
    }
    engine = MagicMock()
    engine.dispose = MagicMock()
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch(
                    "kalshi_no_carry.research.pipeline_runner.run_research_pipeline",
                    return_value=fake_pipe,
                ):
                    outd = tmp_path / "out"
                    rc = mod.main(["--output-dir", str(outd), "--report-name", "r1"])
    assert rc == 0
    sdir = outd / "r1"
    assert (sdir / "summary.json").is_file()
    assert (sdir / "report.md").is_file()


def test_run_research_report_dry_run_no_files_and_no_pipeline(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("run_rr", ROOT / "scripts" / "run_research_report.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    audit_out = {"success": True, "warnings": [], "raw_markets_count": 1}
    engine = MagicMock()
    engine.dispose = MagicMock()
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch(
                    "kalshi_no_carry.research.dataset_audit.audit_research_dataset",
                    return_value=audit_out,
                ) as aud:
                    with patch("kalshi_no_carry.research.pipeline_runner.run_research_pipeline") as pipe:
                        outd = tmp_path / "dry"
                        log = StringIO()
                        with patch("sys.stdout", log):
                            mod.main(["--output-dir", str(outd), "--report-name", "r2", "--dry-run"])
                        pipe.assert_not_called()
                        aud.assert_called_once()
    assert not (outd / "r2").exists()
    data = json.loads(log.getvalue())
    assert data["files_written"] is False
    assert data["database_writes_performed"] is False


def test_dry_run_does_not_run_migrations_or_create_tables(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("run_rr", ROOT / "scripts" / "run_research_report.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    audit_out = {"success": True, "warnings": [], "raw_markets_count": 0}
    engine = MagicMock()
    engine.dispose = MagicMock()
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch(
                    "kalshi_no_carry.research.dataset_audit.audit_research_dataset",
                    return_value=audit_out,
                ):
                    with patch("alembic.command.upgrade") as up:
                        with patch("kalshi_no_carry.database.create_all_tables") as ca:
                            with patch("sys.stdout", StringIO()):
                                mod.main(
                                    [
                                        "--dry-run",
                                        "--migrate",
                                        "--create-tables",
                                        "--output-dir",
                                        str(tmp_path),
                                    ]
                                )
    up.assert_not_called()
    ca.assert_not_called()


def test_dry_run_migrate_and_delete_labels_in_ignored_flags(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("run_rr", ROOT / "scripts" / "run_research_report.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    audit_out = {"success": True, "warnings": [], "raw_markets_count": 1}
    engine = MagicMock()
    engine.dispose = MagicMock()
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch(
                    "kalshi_no_carry.research.dataset_audit.audit_research_dataset",
                    return_value=audit_out,
                ):
                    buf = StringIO()
                    with patch("sys.stdout", buf):
                        mod.main(
                            [
                                "--dry-run",
                                "--migrate",
                                "--delete-existing-labels",
                                "--delete-existing-features",
                                "--output-dir",
                                str(tmp_path),
                            ]
                        )
    data = json.loads(buf.getvalue())
    ign = data["ignored_write_flags"]
    assert "migrate" in ign
    assert "delete_existing_labels" in ign
    assert "delete_existing_features" in ign
    ws = data.get("warnings") or []
    assert any("migrate" in x.lower() for x in ign) or any("DRY_RUN" in x for x in ws)


def test_dry_run_no_backtest_persist(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("run_rr", ROOT / "scripts" / "run_research_report.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    audit_out = {"success": True, "warnings": [], "raw_markets_count": 1}
    engine = MagicMock()
    engine.dispose = MagicMock()
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch(
                    "kalshi_no_carry.research.dataset_audit.audit_research_dataset",
                    return_value=audit_out,
                ):
                    with patch(
                        "kalshi_no_carry.research.backtest_no_carry.run_no_carry_backtest_persisted"
                    ) as bt:
                        with patch("sys.stdout", StringIO()):
                            mod.main(["--dry-run", "--run-backtest", "--output-dir", str(tmp_path)])
    bt.assert_not_called()


def test_run_research_report_include_test_and_backtest_suppressed_in_dry_run(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("run_rr", ROOT / "scripts" / "run_research_report.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    captured: dict = {}
    audit_out = {"success": True, "warnings": [], "raw_markets_count": 5}

    def grab(engine, **kwargs):
        captured.update(kwargs)
        return audit_out

    engine = MagicMock()
    engine.dispose = MagicMock()
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch(
                    "kalshi_no_carry.research.dataset_audit.audit_research_dataset",
                    side_effect=grab,
                ):
                    with patch("kalshi_no_carry.research.pipeline_runner.run_research_pipeline") as pipe:
                        buf = StringIO()
                        with patch("sys.stdout", buf):
                            mod.main(
                                [
                                    "--include-test",
                                    "--run-backtest",
                                    "--dry-run",
                                    "--output-dir",
                                    str(tmp_path),
                                ]
                            )
                        pipe.assert_not_called()
    assert captured.get("include_test") is True
    data = json.loads(buf.getvalue())
    assert "persist_backtest" in data["ignored_write_flags"]


def test_run_research_report_default_exclude_test_dry_run(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("run_rr", ROOT / "scripts" / "run_research_report.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    captured: dict = {}
    audit_out = {"success": True, "warnings": [], "raw_markets_count": 5}

    def grab(engine, **kwargs):
        captured.update(kwargs)
        return audit_out

    engine = MagicMock()
    engine.dispose = MagicMock()
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch(
                    "kalshi_no_carry.research.dataset_audit.audit_research_dataset",
                    side_effect=grab,
                ):
                    with patch("sys.stdout", StringIO()):
                        mod.main(["--dry-run", "--output-dir", str(tmp_path)])
    assert captured.get("include_test") is False


def test_non_dry_run_prints_files_and_db_writes_true(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("run_rr", ROOT / "scripts" / "run_research_report.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    fake_pipe = {
        "success": True,
        "failed_stage": None,
        "pipeline_version": "p",
        "split_version": "s",
        "feature_version": "f",
        "label_version": "l",
        "backtest_version": "b",
        "include_test": False,
        "warnings": [],
        "stages": {},
        "audit_summary": {
            "raw_markets_count": 1,
            "raw_orderbook_snapshots_count": 1,
            "event_clusters_count": 1,
            "strategy_splits_count": 1,
            "market_labels_count": 1,
            "research_feature_rows_count": 200,
            "scorable_feature_rows": 120,
            "feature_rows_with_label": 150,
            "feature_rows_by_split": {"train": 100, "validation": 100},
        },
        "backtest_summary": None,
        "high_level_counts": {},
        "next_recommended_action": "x",
    }
    engine = MagicMock()
    engine.dispose = MagicMock()
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch(
                    "kalshi_no_carry.research.pipeline_runner.run_research_pipeline",
                    return_value=fake_pipe,
                ):
                    buf = StringIO()
                    with patch("sys.stdout", buf):
                        mod.main(["--output-dir", str(tmp_path), "--report-name", "nr"])
    out = json.loads(buf.getvalue())
    assert out["dry_run"] is False
    assert out["files_written"] is True
    assert out["database_writes_performed"] is True
