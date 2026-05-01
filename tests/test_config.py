"""Tests for environment-driven configuration."""

from __future__ import annotations

import pytest

from kalshi_no_carry.config import Settings, get_settings, reset_settings_cache


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_settings_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KALSHI_NO_CARRY_ENV", "staging")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("KALSHI_BASE_URL", "https://example.test/trade-api/v2")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_settings_cache()
    s = get_settings()
    assert s.kalshi_no_carry_env == "staging"
    assert s.log_level == "DEBUG"
    assert s.kalshi_base_url == "https://example.test/trade-api/v2"
    assert s.database_url is None


def test_kalshi_api_base_url_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KALSHI_BASE_URL", raising=False)
    monkeypatch.setenv("KALSHI_API_BASE_URL", "https://legacy.example/trade-api/v2")
    reset_settings_cache()
    assert get_settings().kalshi_base_url == "https://legacy.example/trade-api/v2"


def test_database_url_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@localhost:5432/dbtest",
    )
    reset_settings_cache()
    s = get_settings()
    assert s.database_url is not None
    assert "localhost" in str(s.database_url)


def test_production_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KALSHI_NO_CARRY_ENV", "production")
    reset_settings_cache()
    assert get_settings().is_production is True
