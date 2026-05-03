"""CLI tests for scripts/build_labels.py."""

from __future__ import annotations

import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def test_build_labels_exits_without_database_url() -> None:
    spec = importlib.util.spec_from_file_location("build_labels_cli", ROOT / "scripts" / "build_labels.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=None)):
        spec.loader.exec_module(mod)
        out = StringIO()
        with patch("sys.stdout", out):
            rc = mod.main([])
    assert rc == 2
    assert json.loads(out.getvalue())["success"] is False


def test_build_labels_does_not_print_database_url() -> None:
    secret = "NEVERLEAK459"
    url = f"sqlite+pysqlite:///{secret}_db.sqlite"
    spec = importlib.util.spec_from_file_location("build_labels_cli", ROOT / "scripts" / "build_labels.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=url)):
        spec.loader.exec_module(mod)
    engine = MagicMock()
    engine.dispose = MagicMock()
    with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
        with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
            with patch(
                "kalshi_no_carry.research.outcomes.build_market_outcome_labels_from_raw_markets",
                return_value={"success": True, "labels_written": 0},
            ):
                log = StringIO()
                with patch("sys.stdout", log):
                    rc = mod.main([])
    assert rc == 0
    text = log.getvalue()
    assert secret not in text
    assert url not in text
