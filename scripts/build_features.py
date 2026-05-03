#!/usr/bin/env python3
"""Build versioned research feature rows from stored orderbook snapshots (read-only DB)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_SPLIT_VERSION = "v0.5_chronological_60_20_20"
_DEFAULT_FEATURE_VERSION = "v0.6_orderbook_snapshot_features"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Materialize research_feature_rows from raw orderbooks + splits (no trading, no PnL)."
    )
    p.add_argument("--split-version", default=_DEFAULT_SPLIT_VERSION)
    p.add_argument("--feature-version", default=_DEFAULT_FEATURE_VERSION)
    p.add_argument(
        "--label-version",
        default=None,
        help="Optional research_market_labels version to merge into feature label columns (scoring/audit only)",
    )
    p.add_argument(
        "--include-test",
        action="store_true",
        help="Include rows in the sealed test split (default: train+validation only)",
    )
    p.add_argument(
        "--splits",
        default="train,validation",
        help="Comma-separated split_name values (test ignored unless --include-test)",
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--market-ticker", action="append", dest="market_tickers", default=None)
    p.add_argument(
        "--delete-existing",
        action="store_true",
        help="Delete research_feature_rows for this split_version+feature_version before insert",
    )
    p.add_argument("--dry-run", action="store_true", help="Compute rows but do not persist")
    p.add_argument(
        "--create-tables",
        action="store_true",
        help="SQLAlchemy create_all for disposable dev DBs only",
    )
    p.add_argument(
        "--migrate",
        action="store_true",
        help="Run alembic upgrade head before building",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    from kalshi_no_carry.config import get_settings
    from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url
    from kalshi_no_carry.db.repositories import (
        bulk_upsert_research_feature_rows,
        delete_research_feature_rows_for_version,
        list_orderbook_snapshots_for_feature_building,
        load_market_outcome_labels_by_ticker,
    )
    from kalshi_no_carry.logging_setup import configure_logging
    from kalshi_no_carry.research.feature_dataset import build_feature_row_from_joined_record, validate_feature_row

    configure_logging()
    settings = get_settings()
    if not settings.database_url:
        print(json.dumps({"success": False, "error": "DATABASE_URL is required"}), flush=True)
        return 2

    split_parts = [s.strip() for s in str(args.splits).split(",") if s.strip()]
    if not split_parts:
        print(json.dumps({"success": False, "error": "--splits must list at least one split"}), flush=True)
        return 2

    engine = create_engine_from_database_url(str(settings.database_url))
    warnings: list[str] = []
    out: dict = {
        "success": True,
        "split_version": args.split_version.strip(),
        "feature_version": args.feature_version.strip(),
        "include_test": bool(args.include_test),
        "splits_requested": split_parts,
        "rows_seen": 0,
        "rows_built": 0,
        "rows_written": 0,
        "rows_skipped": 0,
        "missing_price_rows": 0,
        "missing_close_time_rows": 0,
        "label_version": (str(args.label_version).strip() if args.label_version else None),
        "warnings": warnings,
    }

    try:
        if args.migrate:
            from alembic import command
            from alembic.config import Config

            cfg = Config(str(_ROOT / "alembic.ini"))
            command.upgrade(cfg, "head")

        if args.create_tables:
            create_all_tables(engine)

        from sqlalchemy.orm import sessionmaker

        maker = sessionmaker(engine, expire_on_commit=False, future=True)

        with maker() as session:
            with session.begin():
                if args.delete_existing and not args.dry_run:
                    delete_research_feature_rows_for_version(
                        session,
                        split_version=args.split_version.strip(),
                        feature_version=args.feature_version.strip(),
                    )

                sources = list_orderbook_snapshots_for_feature_building(
                    session,
                    split_version=args.split_version.strip(),
                    include_splits=tuple(split_parts),
                    include_test=bool(args.include_test),
                    market_tickers=args.market_tickers,
                    limit=args.limit,
                )
                out["rows_seen"] = len(sources)

                label_ver = (str(args.label_version).strip() if args.label_version else None) or None
                labels_map: dict = {}
                if label_ver:
                    tickers = sorted({src.market.market_ticker for src in sources})
                    labels_map = load_market_outcome_labels_by_ticker(
                        session, label_version=label_ver, market_tickers=tickers
                    )
                    missing = [t for t in tickers if t not in labels_map]
                    if missing:
                        warnings.append(
                            f"label_version={label_ver!r} missing labels for {len(missing)} / {len(tickers)} markets in this batch"
                        )

                rows: list = []
                for src in sources:
                    ol = labels_map.get(src.market.market_ticker) if label_ver else None
                    row = build_feature_row_from_joined_record(
                        src,
                        feature_version=args.feature_version.strip(),
                        outcome_label=ol,
                    )
                    issues = validate_feature_row(row)
                    if issues:
                        out["rows_skipped"] += 1
                        warnings.append(f"skip snapshot {row.snapshot_id}: {issues}")
                        continue
                    out["rows_built"] += 1
                    if not row.has_complete_executable_prices:
                        out["missing_price_rows"] += 1
                    if row.seconds_to_close is None:
                        out["missing_close_time_rows"] += 1
                    if not args.dry_run:
                        rows.append(row)

                if not args.dry_run and rows:
                    bulk_upsert_research_feature_rows(session, rows)
                    out["rows_written"] = len(rows)
                elif args.dry_run:
                    out["rows_written"] = 0
                else:
                    out["rows_written"] = len(rows)

    except Exception as exc:
        out["success"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(out), flush=True)
        return 1
    finally:
        engine.dispose()

    print(json.dumps(out), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
