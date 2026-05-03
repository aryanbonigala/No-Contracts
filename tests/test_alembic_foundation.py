"""Offline checks for Alembic layout and migration wiring (no live Postgres required)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parents[1]


def test_alembic_layout_files_exist() -> None:
    assert (ROOT / "alembic.ini").is_file()
    assert (ROOT / "alembic" / "env.py").is_file()
    assert (ROOT / "alembic" / "script.py.mako").is_file()
    assert (ROOT / "alembic" / "versions").is_dir()
    assert (ROOT / "scripts" / "db_migrate.py").is_file()
    assert (ROOT / "scripts" / "db_revision.py").is_file()


def test_alembic_ini_script_location() -> None:
    text = (ROOT / "alembic.ini").read_text(encoding="utf-8")
    assert "script_location" in text
    assert "%(here)s/alembic" in text


def test_env_py_wires_sqlalchemy_metadata() -> None:
    src = (ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "from kalshi_no_carry.db.schema import Base" in src
    assert "target_metadata = Base.metadata" in src
    assert "_get_database_url" in src


def test_initial_migration_is_frozen_explicit_ddl() -> None:
    path = ROOT / "alembic" / "versions" / "0001_initial_schema.py"
    assert path.is_file()
    body = path.read_text(encoding="utf-8")
    assert "revision = " in body and "0001_initial_schema" in body
    assert "down_revision = None" in body
    assert "Base.metadata.create_all" not in body
    assert "Base.metadata.drop_all" not in body
    assert "from kalshi_no_carry.db.schema import Base" not in body
    assert "op.create_table" in body
    assert "strategy_splits" in body
    assert "cluster_id" in body and "split_version" in body
    assert "PrimaryKeyConstraint(\"cluster_id\", \"split_version\")" in body
    assert 'ondelete="CASCADE"' in body
    assert "def json_type" in body
    assert "with_variant" in body
    assert "postgresql.JSONB" in body


def test_initial_migration_json_type_compiles_to_jsonb_for_postgresql() -> None:
    import importlib.util

    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql as pg
    from sqlalchemy.schema import CreateColumn

    path = ROOT / "alembic" / "versions" / "0001_initial_schema.py"
    spec = importlib.util.spec_from_file_location("initial_0001_json", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    col = sa.Column("probe_json", mod.json_type(), nullable=True)
    ddl = str(CreateColumn(col).compile(dialect=pg.dialect()))
    assert "JSONB" in ddl.upper()


def test_alembic_heads_runs_without_database_url() -> None:
    """Listing script heads must not require a database connection."""
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env.pop("DATABASE_URL", None)
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "heads"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "0004_market_outcome_labels" in out
    assert (ROOT / "alembic" / "versions" / "0001_initial_schema.py").is_file()


def test_db_migrate_exits_when_database_url_missing() -> None:
    spec = importlib.util.spec_from_file_location(
        "db_migrate_cli",
        ROOT / "scripts" / "db_migrate.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=None)):
        spec.loader.exec_module(mod)
        rc = mod.main()
    assert rc == 1


def test_db_migrate_does_not_echo_database_url() -> None:
    spec = importlib.util.spec_from_file_location(
        "db_migrate_cli",
        ROOT / "scripts" / "db_migrate.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    secret = "NEVER_PRINT_THIS_DB_SECRET"
    fake_url = f"postgresql://user:{secret}@localhost:5432/research"
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=fake_url)):
        spec.loader.exec_module(mod)
        with patch("alembic.command.upgrade"):
            from io import StringIO

            out = StringIO()
            err = StringIO()
            with patch("sys.stdout", out), patch("sys.stderr", err):
                rc = mod.main()
    assert rc == 0
    combined = out.getvalue() + err.getvalue()
    assert secret not in combined
    assert fake_url not in combined


def test_alembic_upgrade_sqlite_file_creates_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alembic import command
    from alembic.config import Config

    from kalshi_no_carry.config import reset_settings_cache

    url = f"sqlite+pysqlite:///{tmp_path / 'm.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    reset_settings_cache()
    try:
        cfg = Config(str(ROOT / "alembic.ini"))
        command.upgrade(cfg, "head")
    finally:
        reset_settings_cache()

    eng = create_engine(url)
    try:
        insp = inspect(eng)
        names = set(insp.get_table_names())

        pk = insp.get_pk_constraint("strategy_splits")
        assert set(pk["constrained_columns"]) == {"cluster_id", "split_version"}

        pk_fr = insp.get_pk_constraint("research_feature_rows")
        assert set(pk_fr["constrained_columns"]) == {"snapshot_id", "split_version", "feature_version"}

        pk_bt = insp.get_pk_constraint("backtest_trades")
        assert set(pk_bt["constrained_columns"]) == {"run_id", "trade_index"}

        pk_m = insp.get_pk_constraint("research_market_labels")
        assert set(pk_m["constrained_columns"]) == {"market_ticker", "label_version"}
    finally:
        eng.dispose()

    assert "strategy_splits" in names
    assert "event_clusters" in names
    assert "raw_events" in names
    assert "research_feature_rows" in names
    assert "research_market_labels" in names
    assert "backtest_runs" in names
    assert "backtest_trades" in names
    assert "alembic_version" in names


def test_alembic_sqlite_tables_match_orm_table_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alembic import command
    from alembic.config import Config

    from kalshi_no_carry.config import reset_settings_cache
    from kalshi_no_carry.db.schema import Base

    url = f"sqlite+pysqlite:///{tmp_path / 'orm_check.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    reset_settings_cache()
    try:
        cfg = Config(str(ROOT / "alembic.ini"))
        command.upgrade(cfg, "head")
    finally:
        reset_settings_cache()

    orm_tables = set(Base.metadata.tables.keys())
    eng = create_engine(url)
    try:
        migrated = set(inspect(eng).get_table_names()) - {"alembic_version"}
    finally:
        eng.dispose()

    assert orm_tables == migrated
