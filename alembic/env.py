"""Alembic migration environment — uses ``kalshi_no_carry.db.schema.Base.metadata``."""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Project root (parent of this ``alembic/`` package)
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from kalshi_no_carry.db.schema import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_database_url() -> str:
    """
    Resolve the database URL for migrations.

    Never logs or prints the raw URL. Raises if no URL is configured.
    """
    raw = os.environ.get("DATABASE_URL")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    try:
        from kalshi_no_carry.config import get_settings

        db = get_settings().database_url
    except Exception:
        db = None
    if db is not None and str(db).strip():
        return str(db).strip()
    raise RuntimeError(
        "DATABASE_URL is required for Alembic migrations. "
        "Set the environment variable (or define DATABASE_URL in .env for local runs)."
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout ('alembic upgrade <rev> --sql') using a configured URL."""
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in-process against DATABASE_URL."""
    url = _get_database_url()
    section = config.get_section(config.config_ini_section) or {}
    configuration = dict(section)
    configuration["sqlalchemy.url"] = url
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
