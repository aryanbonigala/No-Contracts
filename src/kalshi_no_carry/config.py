"""Load application settings from the environment (no secrets in repo)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn
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
    kalshi_api_base_url: str = Field(
        default="https://api.elections.kalshi.com",
        validation_alias="KALSHI_API_BASE_URL",
    )
    database_url: PostgresDsn | None = Field(default=None, validation_alias="DATABASE_URL")

    @property
    def is_production(self) -> bool:
        return self.kalshi_no_carry_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings (single process). Call `get_settings.cache_clear()` in tests."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the settings cache (intended for tests)."""
    get_settings.cache_clear()
