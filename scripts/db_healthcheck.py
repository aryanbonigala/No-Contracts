#!/usr/bin/env python3
"""Run SELECT 1 against the configured database."""

from __future__ import annotations

import sys

from kalshi_no_carry.config import get_settings
from kalshi_no_carry.database import create_engine_from_database_url, healthcheck


def main() -> None:
    settings = get_settings()
    if not settings.database_url:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        raise SystemExit(1)
    engine = create_engine_from_database_url(str(settings.database_url))
    try:
        healthcheck(engine)
    finally:
        engine.dispose()
    print("ok: database connection healthy.")


if __name__ == "__main__":
    main()
