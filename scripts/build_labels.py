#!/usr/bin/env python3
"""Build versioned ``research_market_labels`` from ``raw_markets`` (read-only; no trading)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_LABEL_VERSION = "v0.8_market_outcome_labels"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Extract deterministic outcome Labels from stored raw markets (no live API)."
    )
    p.add_argument("--label-version", default=_DEFAULT_LABEL_VERSION)
    p.add_argument("--market-ticker", action="append", dest="market_tickers", default=None)
    p.add_argument("--status", action="append", dest="statuses", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--delete-existing",
        action="store_true",
        help="Delete labels for this label_version before insert",
    )
    p.add_argument("--create-tables", action="store_true")
    p.add_argument("--migrate", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    from kalshi_no_carry.config import get_settings
    from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url
    from kalshi_no_carry.logging_setup import configure_logging
    from kalshi_no_carry.research.outcomes import build_market_outcome_labels_from_raw_markets

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

        summary = build_market_outcome_labels_from_raw_markets(
            engine,
            label_version=str(args.label_version).strip(),
            market_tickers=args.market_tickers,
            statuses=args.statuses,
            limit=args.limit,
            delete_existing=bool(args.delete_existing),
        )
        print(json.dumps(summary, default=str, sort_keys=True), flush=True)
        return 0 if summary.get("success") else 1
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
