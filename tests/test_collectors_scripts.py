"""Smoke tests for collector CLI scripts (no live Kalshi/Postgres)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_collect_markets_script_requires_database_url() -> None:
    env = {**os.environ, "DATABASE_URL": ""}
    env.pop("KALSHI_PRIVATE_KEY_PATH", None)
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "collect_markets.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1
    assert "DATABASE_URL" in r.stderr


def test_collect_orderbooks_script_requires_tickers_or_active() -> None:
    env = {**os.environ, "DATABASE_URL": "sqlite+pysqlite:///:memory:"}
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "collect_orderbooks.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1
    assert "ticker" in r.stderr.lower() or "active" in r.stderr.lower()
