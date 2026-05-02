#!/usr/bin/env python3
"""Materialize ``event_clusters`` from raw tables and assign chronological ``strategy_splits``."""

from __future__ import annotations

import argparse
import json

from kalshi_no_carry.config import get_settings
from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url
from kalshi_no_carry.logging_setup import configure_logging
from kalshi_no_carry.research.build_splits import (
    SplitVersionExistsError,
    _DEFAULT_SPLIT_VERSION,
    assign_chronological_splits,
    build_event_clusters_from_raw_data,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build event clusters and strategy splits (read-only research).")
    p.add_argument(
        "--split-version",
        default=_DEFAULT_SPLIT_VERSION,
        help=f"Version label stored on strategy_splits rows (default: {_DEFAULT_SPLIT_VERSION!r})",
    )
    p.add_argument("--train-fraction", type=float, default=0.60)
    p.add_argument("--validation-fraction", type=float, default=0.20)
    p.add_argument("--test-fraction", type=float, default=0.20)
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing strategy_splits rows for --split-version only",
    )
    p.add_argument(
        "--create-tables",
        action="store_true",
        help="Create tables via SQLAlchemy create_all before running",
    )
    p.add_argument(
        "--clusters-only",
        action="store_true",
        help="Only run event cluster upserts from raw_events/raw_markets",
    )
    p.add_argument(
        "--splits-only",
        action="store_true",
        help="Only assign strategy_splits from existing event_clusters",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)
    if args.clusters_only and args.splits_only:
        print(
            json.dumps({"success": False, "error": "use at most one of --clusters-only, --splits-only"}),
            flush=True,
        )
        return 2

    settings = get_settings()
    url = settings.database_url
    if not url:
        print(json.dumps({"success": False, "error": "DATABASE_URL is required"}), flush=True)
        return 2

    engine = create_engine_from_database_url(url)
    out: dict = {"success": True}
    try:
        if args.create_tables:
            create_all_tables(engine)

        if args.splits_only:
            out["clusters"] = None
        else:
            out["clusters"] = build_event_clusters_from_raw_data(engine)

        if args.clusters_only:
            out["splits"] = None
        else:
            out["splits"] = assign_chronological_splits(
                engine,
                args.split_version,
                train_fraction=args.train_fraction,
                validation_fraction=args.validation_fraction,
                test_fraction=args.test_fraction,
                overwrite=args.overwrite,
            )
    except SplitVersionExistsError as e:
        print(
            json.dumps({"success": False, "error": str(e), "split_version": e.split_version}),
            flush=True,
        )
        return 1
    except ValueError as e:
        print(json.dumps({"success": False, "error": str(e)}), flush=True)
        return 1
    finally:
        engine.dispose()

    print(json.dumps(out, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
