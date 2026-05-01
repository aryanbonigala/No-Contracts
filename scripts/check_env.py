#!/usr/bin/env python3
"""Print resolved configuration keys (no secret values)."""

from __future__ import annotations

from kalshi_no_carry.config import get_settings, reset_settings_cache
from kalshi_no_carry.database import describe_intended_usage


def main() -> None:
    reset_settings_cache()
    s = get_settings()
    print(f"KALSHI_NO_CARRY_ENV={s.kalshi_no_carry_env}")
    print(f"LOG_LEVEL={s.log_level}")
    print(f"KALSHI_API_BASE_URL={s.kalshi_api_base_url}")
    print(f"DATABASE_URL_SET={'yes' if s.database_url is not None else 'no'}")
    print(describe_intended_usage(s))


if __name__ == "__main__":
    main()
