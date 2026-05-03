"""CLI tests for scripts/audit_research_dataset.py."""

from __future__ import annotations

import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def test_audit_script_exits_without_database_url() -> None:
    spec = importlib.util.spec_from_file_location(
        "audit_ds_cli",
        ROOT / "scripts" / "audit_research_dataset.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=None)):
        spec.loader.exec_module(mod)
        out = StringIO()
        with patch("sys.stdout", out):
            rc = mod.main([])
    assert rc == 2
    assert json.loads(out.getvalue())["success"] is False


def test_audit_script_does_not_print_database_url() -> None:
    secret = "NEVERLEAK789"
    url = f"sqlite+pysqlite:///{secret}_db.sqlite"
    spec = importlib.util.spec_from_file_location(
        "audit_ds_cli",
        ROOT / "scripts" / "audit_research_dataset.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=url)):
        spec.loader.exec_module(mod)
    engine = MagicMock()
    engine.dispose = MagicMock()
    fake_audit = {
        "success": True,
        "research_feature_rows_count": 0,
        "warnings": [],
        "audit_version": "v0.8_dataset_audit",
    }
    with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
        with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
            with patch(
                "kalshi_no_carry.research.dataset_audit.audit_research_dataset",
                return_value=fake_audit,
            ):
                buf = StringIO()
                with patch("sys.stdout", buf):
                    rc = mod.main([])
    assert rc == 0
    text = buf.getvalue()
    assert secret not in text
    assert url not in text
