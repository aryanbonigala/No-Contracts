"""CLI smoke tests for shadow bucket scripts (no live Kalshi)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'db.sqlite'}"


def test_run_shadow_bucket_scan_main_json(sqlite_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    import importlib.util

    from kalshi_no_carry.config import reset_settings_cache
    from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url

    reset_settings_cache()
    eng = create_engine_from_database_url(sqlite_url)
    create_all_tables(eng)
    eng.dispose()

    spec = importlib.util.spec_from_file_location("rss", ROOT / "scripts" / "run_shadow_bucket_scan.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)

    class FC:
        def iter_markets(self, **kwargs):
            return iter(())

        def get_orderbook(self, ticker: str):
            raise AssertionError("no orderbook in empty universe")

        def close(self) -> None:
            return None

    spec.loader.exec_module(mod)
    with patch("kalshi_no_carry.kalshi_client.KalshiClient.from_settings", return_value=FC()):
        rc = mod.main([])
    assert rc == 0


def test_score_shadow_bucket_entries_main_json(sqlite_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    from kalshi_no_carry.config import reset_settings_cache
    from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url

    reset_settings_cache()
    eng = create_engine_from_database_url(sqlite_url)
    create_all_tables(eng)
    eng.dispose()

    import importlib.util

    spec = importlib.util.spec_from_file_location("scs", ROOT / "scripts" / "score_shadow_bucket_entries.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rc = mod.main(["--shadow-version", "sv-x"])
    assert rc == 0


def test_run_shadow_bucket_report_main_json(sqlite_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    from kalshi_no_carry.config import reset_settings_cache
    from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url

    reset_settings_cache()
    eng = create_engine_from_database_url(sqlite_url)
    create_all_tables(eng)
    eng.dispose()

    import importlib.util

    spec = importlib.util.spec_from_file_location("rsr", ROOT / "scripts" / "run_shadow_bucket_report.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    outdir = tmp_path / "rep"
    rc = mod.main(["--shadow-version", "sv-x", "--report-name", "cli-smoke", "--output-dir", str(outdir)])
    assert rc == 0
    assert (outdir / "shadow_bucket_report.json").is_file()
