#!/usr/bin/env python3
"""Create database tables via SQLAlchemy ``create_all`` (no Alembic revision tracking).

For versioned schema management on databases with data you care about, use
``scripts/db_migrate.py`` instead. Exits non-zero if DATABASE_URL is missing.
"""

from __future__ import annotations

import sys

from kalshi_no_carry.config import get_settings
from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url


def main() -> None:
    settings = get_settings()
    if not settings.database_url:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        raise SystemExit(1)
    engine = create_engine_from_database_url(str(settings.database_url))
    try:
        create_all_tables(engine)
    finally:
        engine.dispose()
    print("ok: database tables created (or already present).")


if __name__ == "__main__":
    main()
