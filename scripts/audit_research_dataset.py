#!/usr/bin/env python3
"""Audit research dataset coverage (feature rows, labels, joins; read-only)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_SPLIT_VERSION = "v0.5_chronological_60_20_20"
_DEFAULT_FEATURE_VERSION = "v0.6_orderbook_snapshot_features"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="JSON audit summary for research tables (offline-safe).")
    p.add_argument("--split-version", default=_DEFAULT_SPLIT_VERSION)
    p.add_argument("--feature-version", default=_DEFAULT_FEATURE_VERSION)
    p.add_argument("--label-version", default=None)
    p.add_argument(
        "--include-test",
        action="store_true",
        help="Include sealed test split rows in feature-row audit scope",
    )
    p.add_argument("--migrate", action="store_true")
    p.add_argument("--create-tables", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    from kalshi_no_carry.config import get_settings
    from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url
    from kalshi_no_carry.logging_setup import configure_logging
    from kalshi_no_carry.research.dataset_audit import audit_research_dataset

    configure_logging()
    settings = get_settings()
    if not settings.database_url:
        print(json.dumps({"success": False, "error": "DATABASE_URL is required"}), flush=True)
        return 2

    engine = create_engine_from_database_url(str(settings.database_url))
    try:
        if args.migrate:
            from alembic import command
            from alembic.config import Config

            cfg = Config(str(_ROOT / "alembic.ini"))
            command.upgrade(cfg, "head")

        if args.create_tables:
            create_all_tables(engine)

        lv = str(args.label_version).strip() if args.label_version else None
        out = audit_research_dataset(
            engine,
            split_version=str(args.split_version).strip(),
            feature_version=str(args.feature_version).strip(),
            label_version=lv or None,
            include_test=bool(args.include_test),
        )
        print(json.dumps(out, default=str, sort_keys=True), flush=True)
        return 0 if out.get("success") else 1
    except Exception as exc:
        print(
            json.dumps({"success": False, "error": f"{type(exc).__name__}: {exc}"}, default=str),
            flush=True,
        )
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
