"""CLI for scripts/audit_collection_coverage.py."""

from __future__ import annotations

import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def test_audit_collection_coverage_requires_database_url() -> None:
    spec = importlib.util.spec_from_file_location("acc", ROOT / "scripts" / "audit_collection_coverage.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=None)):
        spec.loader.exec_module(mod)
        buf = StringIO()
        with patch("sys.stdout", buf):
            rc = mod.main([])
    assert rc == 2
    assert json.loads(buf.getvalue())["success"] is False


def test_audit_collection_coverage_prints_json_no_network() -> None:
    spec = importlib.util.spec_from_file_location("acc", ROOT / "scripts" / "audit_collection_coverage.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    from sqlalchemy import create_engine

    from kalshi_no_carry.database import create_all_tables, drop_all_tables

    eng = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_all_tables(eng)
    url = "sqlite+pysqlite:///:memory:"
    try:
        with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=url)):
            spec.loader.exec_module(mod)
            with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=eng):
                with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                    buf = StringIO()
                    with patch("sys.stdout", buf):
                        rc = mod.main(["--split-version", "sv", "--feature-version", "fv"])
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert data["success"] is True
        assert data["collection_coverage"]["coverage_version"]
    finally:
        drop_all_tables(eng)
        eng.dispose()
