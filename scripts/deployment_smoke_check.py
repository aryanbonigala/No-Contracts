#!/usr/bin/env python3
"""Post-deploy smoke check: DATABASE_URL connectivity, settings, optional schema/reports-dir checks.

Does not call Kalshi by default. Never prints raw credentials or full DATABASE_URL.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import SQLAlchemyError

from kalshi_no_carry.config import get_settings, reset_settings_cache
from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, healthcheck
from kalshi_no_carry.db.schema import Base


def _dialect_label(url: str) -> str:
    try:
        return str(make_url(url).get_dialect().name)
    except Exception:
        return "unknown"


def _safe_error_message(exc: BaseException) -> str:
    """Avoid echoing connection strings or secrets from driver exceptions."""
    if isinstance(exc, SQLAlchemyError):
        return "database_error"
    return type(exc).__name__


def _ensure_imports_ok() -> None:
    import kalshi_no_carry.config  # noqa: F401
    import kalshi_no_carry.database  # noqa: F401
    import kalshi_no_carry.db.schema  # noqa: F401


def _expected_table_names() -> list[str]:
    return sorted(Base.metadata.tables.keys())


def _reports_dir_writable(path: Path) -> tuple[bool, str | None]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".kalshi_no_carry_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, None
    except OSError as e:
        return False, type(e).__name__


def run(*, check_tables: bool, create_tables: bool, reports_dir: Path | None) -> dict[str, Any]:
    reset_settings_cache()
    warnings: list[str] = []

    out: dict[str, Any] = {
        "success": False,
        "database_url_set": False,
        "database_dialect": None,
        "database_connection_ok": False,
        "settings_loaded": False,
        "imports_ok": False,
        "tables_checked": False,
        "tables_present": [],
        "missing_tables": [],
        "reports_dir_writable": None,
        "warnings": warnings,
        "error_type": None,
        "error_message": None,
    }

    try:
        _ensure_imports_ok()
        out["imports_ok"] = True
    except Exception as e:  # noqa: BLE001 — aggregate as smoke failure
        out["error_type"] = "ImportError"
        out["error_message"] = _safe_error_message(e)
        return out

    try:
        settings = get_settings()
        out["settings_loaded"] = True
        url = settings.database_url
        out["database_url_set"] = bool(url)
        if not url:
            out["error_type"] = "MissingDatabaseUrl"
            out["error_message"] = "DATABASE_URL is not set"
            return out
        out["database_dialect"] = _dialect_label(str(url))
    except Exception as e:  # noqa: BLE001
        out["settings_loaded"] = False
        out["error_type"] = type(e).__name__
        out["error_message"] = _safe_error_message(e)
        return out

    engine = create_engine_from_database_url(str(settings.database_url))
    try:
        try:
            healthcheck(engine)
            out["database_connection_ok"] = True
        except Exception as e:  # noqa: BLE001
            out["error_type"] = "DatabaseConnectionFailed"
            out["error_message"] = _safe_error_message(e)
            return out

        if create_tables:
            try:
                create_all_tables(engine)
            except Exception as e:  # noqa: BLE001
                out["error_type"] = "CreateTablesFailed"
                out["error_message"] = _safe_error_message(e)
                return out

        if check_tables:
            out["tables_checked"] = True
            expected = set(_expected_table_names())
            try:
                insp = inspect(engine)
                existing = set(insp.get_table_names())
            except Exception as e:  # noqa: BLE001
                out["error_type"] = "TableInspectionFailed"
                out["error_message"] = _safe_error_message(e)
                return out
            present = sorted(expected & existing)
            missing = sorted(expected - existing)
            out["tables_present"] = present
            out["missing_tables"] = missing
            if missing:
                warnings.append("missing_expected_tables")

        if reports_dir is not None:
            ok, err = _reports_dir_writable(reports_dir)
            out["reports_dir_writable"] = ok
            if not ok:
                out["error_type"] = "ReportsDirNotWritable"
                out["error_message"] = err or "reports_dir_not_writable"
                return out

        out["success"] = True
        return out
    finally:
        engine.dispose()


def main() -> None:
    p = argparse.ArgumentParser(description="Deployment smoke check (no Kalshi calls by default).")
    p.add_argument("--check-tables", action="store_true", help="Verify expected ORM tables exist")
    p.add_argument("--create-tables", action="store_true", help="Create tables via SQLAlchemy create_all (dev bootstrap)")
    p.add_argument("--reports-dir", type=Path, default=None, help="Verify directory is writable")
    args = p.parse_args()

    payload = run(check_tables=args.check_tables, create_tables=args.create_tables, reports_dir=args.reports_dir)
    print(json.dumps(payload, indent=2, sort_keys=True))
    raise SystemExit(0 if payload.get("success") else 1)


if __name__ == "__main__":
    main()
