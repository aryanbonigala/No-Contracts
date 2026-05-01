"""DATABASE_URL redaction and optional integration gate."""

from __future__ import annotations

import os

import pytest

from kalshi_no_carry.config import get_settings, reset_settings_cache
from kalshi_no_carry.database import redact_database_url


def test_redact_database_url_strips_password() -> None:
    raw = "postgresql://dbuser:supersecret@db.example.com:5432/mydb?sslmode=require"
    safe = redact_database_url(raw)
    assert "supersecret" not in safe
    assert "***" in safe
    assert "db.example.com" in safe


def test_redact_masks_password_query_param() -> None:
    raw = "postgresql://db.example.com/db?password=abc"
    safe = redact_database_url(raw)
    assert "abc" not in safe
    assert "password=***" in safe


def test_settings_without_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_settings_cache()
    assert get_settings().database_url is None


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL") or os.environ.get("RUN_DB_INTEGRATION_TESTS") != "1",
    reason="Set RUN_DB_INTEGRATION_TESTS=1 and DATABASE_URL to run",
)
def test_integration_postgres_healthcheck():
    from kalshi_no_carry.database import create_engine_from_database_url, healthcheck

    engine = create_engine_from_database_url(os.environ["DATABASE_URL"])
    try:
        healthcheck(engine)
    finally:
        engine.dispose()
