"""
PostgreSQL access layer — planned persistence for markets, order books, trades, and research artifacts.

This module is intentionally minimal. A future version should:
- Use a connection pool (e.g. `asyncpg` or SQLAlchemy) configured from `DATABASE_URL`.
- Store immutable raw API payloads and normalized tables for downstream research.
- Support idempotent backfills and provenance (source request id, ingested_at).
- Run migrations via a dedicated tool (Alembic or similar), not ad-hoc DDL in application code.

No schema or queries are defined in v0.1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kalshi_no_carry.config import Settings


def describe_intended_usage(settings: Settings) -> str:
    """
    Return a short description string for debugging/documentation.

    The real database module will open connections using settings.database_url.
    """
    if settings.database_url is None:
        return "DATABASE_URL is not set; persistence is disabled in this process."
    return "DATABASE_URL is set; connection pooling is not implemented in v0.1."
