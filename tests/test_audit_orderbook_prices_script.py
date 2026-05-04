"""CLI tests for scripts/audit_orderbook_prices.py."""

from __future__ import annotations

import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def test_audit_orderbook_script_requires_database_url() -> None:
    spec = importlib.util.spec_from_file_location("aud_ob", ROOT / "scripts" / "audit_orderbook_prices.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=None)):
        spec.loader.exec_module(mod)
        err = StringIO()
        with patch("sys.stderr", err):
            rc = mod.main([])
    assert rc == 2
    assert "DATABASE_URL" in err.getvalue()


def test_audit_orderbook_script_prints_json(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("aud_ob", ROOT / "scripts" / "audit_orderbook_prices.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    fake = {"success": True, "counts": {"snapshots_seen": 0}}
    eng = MagicMock()
    eng.dispose = MagicMock()
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=eng):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch.object(mod, "audit_orderbook_price_extraction", return_value=fake):
                    out = StringIO()
                    with patch("sys.stdout", out):
                        rc = mod.main([])
    assert rc == 0
    assert json.loads(out.getvalue())["counts"]["snapshots_seen"] == 0


def test_audit_orderbook_writes_output_json(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("aud_ob", ROOT / "scripts" / "audit_orderbook_prices.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    fake = {"success": True, "counts": {"snapshots_seen": 2}}
    eng = MagicMock()
    eng.dispose = MagicMock()
    outp = tmp_path / "a.json"
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=eng):
            with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                with patch.object(mod, "audit_orderbook_price_extraction", return_value=fake):
                    out = StringIO()
                    with patch("sys.stdout", out):
                        rc = mod.main(["--output-json", str(outp)])
    assert rc == 0
    assert outp.is_file()
    assert json.loads(outp.read_text())["counts"]["snapshots_seen"] == 2
