"""CLI tests for scripts/run_backtest.py."""

from __future__ import annotations

import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def test_run_backtest_exits_without_database_url() -> None:
    spec = importlib.util.spec_from_file_location("run_backtest_cli", ROOT / "scripts" / "run_backtest.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=None)):
        spec.loader.exec_module(mod)
        out = StringIO()
        with patch("sys.stdout", out):
            rc = mod.main([])
    assert rc == 2
    payload = json.loads(out.getvalue())
    assert payload["success"] is False


def test_run_backtest_dry_run_does_not_print_database_url() -> None:
    secret = "NEVERLEAKTHIS459"
    url = f"sqlite+pysqlite:///{secret}_path/mem.db"
    settings = MagicMock(database_url=url)
    spec = importlib.util.spec_from_file_location("run_backtest_cli", ROOT / "scripts" / "run_backtest.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    engine = MagicMock()
    engine.dispose = MagicMock()

    out_payload = {
        "success": True,
        "stage_name": "backtest",
        "run_id": "rid",
        "rows_seen": 0,
        "warnings": [],
        "summary": {},
        "dry_run": True,
        "trades_persisted": 0,
    }

    with patch("kalshi_no_carry.config.get_settings", return_value=settings):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch(
                    "kalshi_no_carry.research.backtest_no_carry.run_no_carry_backtest_persisted",
                    return_value=out_payload,
                ):
                    buf = StringIO()
                    with patch("sys.stdout", buf):
                        rc = mod.main(["--dry-run"])

    assert rc == 0
    text = buf.getvalue()
    assert secret not in text
    assert url not in text
    payload = json.loads(text)
    assert payload["success"] is True
