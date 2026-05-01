#!/usr/bin/env python3
"""Print resolved configuration keys (no secret values)."""

from __future__ import annotations

from kalshi_no_carry.config import get_settings, reset_settings_cache
from kalshi_no_carry.database import describe_intended_usage, redact_database_url


def main() -> None:
    reset_settings_cache()
    s = get_settings()
    print(f"KALSHI_NO_CARRY_ENV={s.kalshi_no_carry_env}")
    print(f"LOG_LEVEL={s.log_level}")
    print(f"KALSHI_ENV={s.kalshi_env}")
    print(f"KALSHI_BASE_URL_RESOLVED={s.resolved_kalshi_base_url()}")
    print(f"KALSHI_API_KEY_ID_SET={'yes' if s.kalshi_api_key_id else 'no'}")
    print(f"KALSHI_PRIVATE_KEY_PATH_SET={'yes' if s.kalshi_private_key_path is not None else 'no'}")
    print(f"KALSHI_REQUEST_TIMEOUT_SECONDS={s.kalshi_request_timeout_seconds}")
    if s.database_url:
        print(f"DATABASE_URL_CONFIGURED=yes")
        print(f"DATABASE_URL_REDACTED={redact_database_url(str(s.database_url))}")
    else:
        print("DATABASE_URL_CONFIGURED=no")
    print(describe_intended_usage(s))


if __name__ == "__main__":
    main()
