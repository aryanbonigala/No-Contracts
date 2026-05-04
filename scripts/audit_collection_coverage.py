#!/usr/bin/env python3
"""Read-only JSON summary of stored market/orderbook/label coverage (no Kalshi HTTP; no DB writes)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Summarize generic ingestion coverage from DATABASE_URL (read-only). "
        "Does not call Kalshi or mutate the database.",
    )
    p.add_argument(
        "--split-version",
        default="v0.5_chronological_60_20_20",
        help="Feature-row slice for scorable ratio",
    )
    p.add_argument(
        "--feature-version",
        default="v0.6_orderbook_snapshot_features",
        help="Feature-row slice for scorable ratio",
    )
    p.add_argument("--label-version", default="v0.8_market_outcome_labels", help="Filter labels_by_result")
    p.add_argument(
        "--include-test",
        action="store_true",
        help="Include sealed test split rows in feature-row coverage counts",
    )
    p.add_argument("--output-json", type=Path, default=None, help="Optional path to write JSON (no secrets)")
    p.add_argument(
        "--show-breakdown",
        action="store_true",
        help="Include full summary (default stdout is already complete JSON)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    from kalshi_no_carry.config import get_settings
    from kalshi_no_carry.database import create_engine_from_database_url
    from kalshi_no_carry.logging_setup import configure_logging
    from kalshi_no_carry.research.collection_coverage import summarize_collection_coverage

    configure_logging()
    settings = get_settings()
    if not settings.database_url:
        print(json.dumps({"success": False, "error": "DATABASE_URL is required"}), flush=True)
        return 2

    engine = create_engine_from_database_url(str(settings.database_url))
    try:
        payload = summarize_collection_coverage(
            engine,
            split_version=str(args.split_version).strip(),
            feature_version=str(args.feature_version).strip(),
            label_version=str(args.label_version).strip() or None,
            include_test=bool(args.include_test),
        )
        body = {"success": True, "collection_coverage": payload}
        if args.show_breakdown:
            body["detail_level"] = "breakdown"
        text = json.dumps(body, indent=2, sort_keys=True, default=str)
        if args.output_json:
            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            args.output_json.write_text(text, encoding="utf-8")
        print(text, flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error": f"{type(exc).__name__}: {exc}"}, default=str), flush=True)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
