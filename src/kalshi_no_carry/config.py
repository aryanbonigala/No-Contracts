"""Load application settings from the environment (no secrets in repo)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration; values come from environment variables only."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    kalshi_no_carry_env: Literal["development", "staging", "production"] = Field(
        default="development",
        validation_alias="KALSHI_NO_CARRY_ENV",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    kalshi_env: Literal["prod", "demo"] = Field(default="prod", validation_alias="KALSHI_ENV")
    kalshi_base_url: str = Field(
        default="https://api.elections.kalshi.com/trade-api/v2",
        validation_alias=AliasChoices("KALSHI_BASE_URL", "KALSHI_API_BASE_URL"),
    )
    kalshi_demo_base_url: str = Field(
        default="https://demo-api.kalshi.co/trade-api/v2",
        validation_alias="KALSHI_DEMO_BASE_URL",
    )
    kalshi_api_key_id: str | None = Field(default=None, validation_alias="KALSHI_API_KEY_ID")
    kalshi_private_key_path: Path | None = Field(
        default=None,
        validation_alias="KALSHI_PRIVATE_KEY_PATH",
    )
    kalshi_request_timeout_seconds: float = Field(
        default=20.0,
        validation_alias="KALSHI_REQUEST_TIMEOUT_SECONDS",
    )

    # str (not PostgresDsn-only) so SQLite test URLs and managed-Postgres URLs both work.
    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")

    @field_validator("kalshi_api_key_id", mode="before")
    @classmethod
    def _blank_api_key_to_none(cls, v: object) -> object:
        if v == "":
            return None
        return v

    @field_validator("kalshi_private_key_path", mode="before")
    @classmethod
    def _blank_key_path_to_none(cls, v: object) -> object:
        if v == "":
            return None
        return v

    @field_validator("database_url", mode="before")
    @classmethod
    def _blank_database_url_to_none(cls, v: object) -> object:
        if v == "":
            return None
        return v

    @property
    def is_production(self) -> bool:
        return self.kalshi_no_carry_env == "production"

    def resolved_kalshi_base_url(self) -> str:
        """Base URL for Kalshi Trade API v2 (prod or demo host)."""
        if self.kalshi_env == "demo":
            return str(self.kalshi_demo_base_url).rstrip("/")
        return str(self.kalshi_base_url).rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings (single process). Call `get_settings.cache_clear()` in tests."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the settings cache (intended for tests)."""
    get_settings.cache_clear()
