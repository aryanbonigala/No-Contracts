#!/usr/bin/env python3
"""Read-only audit of stored orderbook JSON and implied executable prices (v0.12)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kalshi_no_carry.config import get_settings
from kalshi_no_carry.database import create_engine_from_database_url
from kalshi_no_carry.logging_setup import configure_logging
from kalshi_no_carry.research.orderbook_audit import audit_orderbook_price_extraction


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Inspect raw_orderbook_snapshots for JSON shape and executable NO/YES ask derivation. "
            "Read-only; does not call Kalshi."
        )
    )
    p.add_argument("--limit", type=int, default=None, help="Max snapshots (most recent first)")
    p.add_argument("--feature-version", default=None, help="Filter feature rows for join diagnostic")
    p.add_argument("--split-version", default=None, help="Filter feature rows for join diagnostic")
    p.add_argument("--output-json", default=None, help="Write JSON to this path (otherwise stdout only)")
    p.add_argument(
        "--show-samples",
        action="store_true",
        help="Include slightly richer shape_samples in output (still no full raw books)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_logging()
    settings = get_settings()
    if not settings.database_url:
        print(
            json.dumps({"success": False, "error": "DATABASE_URL is required"}),
            file=sys.stderr,
        )
        return 2

    engine = create_engine_from_database_url(str(settings.database_url))
    try:
        report = audit_orderbook_price_extraction(
            engine,
            limit=args.limit,
            feature_version=args.feature_version,
            split_version=args.split_version,
            max_shape_samples=12 if args.show_samples else 5,
        )
        if not args.show_samples:
            report = dict(report)
            report["shape_samples"] = report.get("shape_samples", [])[:2]
        text = json.dumps(report, indent=2, sort_keys=True)
        if args.output_json:
            Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output_json).write_text(text + "\n", encoding="utf-8")
        print(text)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
