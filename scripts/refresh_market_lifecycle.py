#!/usr/bin/env python3
"""Read-only lifecycle refresh CLI: re-fetch ``GET /markets/{ticker}`` and upsert ``raw_markets``."""

from __future__ import annotations

import argparse
import json
import sys


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generic lifecycle refresh: ticker-based raw_markets upsert (read-only GETs only)."
    )
    p.add_argument("--label-version", default="v0.8_market_outcome_labels")
    p.add_argument(
        "--ticker",
        action="append",
        dest="tickers",
        default=None,
        help="Explicit ticker (repeatable; order preserved)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Max refresh candidates from DB when --ticker is not set",
    )
    p.add_argument("--batch-size", type=int, default=100)
    p.add_argument(
        "--include-already-labeled",
        action="store_true",
        help="Include tickers that already have definitive stored labels when selecting candidates",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Skip database writes (no upserts, no api_fetch_log rows). "
            "May still call Kalshi to preview batch/per-ticker refresh availability."
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    from kalshi_no_carry.config import get_settings
    from kalshi_no_carry.database import create_engine_from_database_url
    from kalshi_no_carry.kalshi_client import KalshiClient
    from kalshi_no_carry.logging_setup import configure_logging
    from kalshi_no_carry.collectors.market_lifecycle import (
        find_lifecycle_refresh_candidates,
        refresh_markets_by_ticker,
    )

    configure_logging()
    settings = get_settings()
    if not settings.database_url:
        print(json.dumps({"success": False, "error": "DATABASE_URL is required"}), flush=True)
        return 2

    engine = create_engine_from_database_url(str(settings.database_url))
    client = KalshiClient.from_settings(settings)
    try:
        explicit = tuple(str(x).strip() for x in (args.tickers or []) if str(x).strip())
        if explicit:
            tickers_to_refresh = list(explicit)
            used_explicit = True
        else:
            tickers_to_refresh = find_lifecycle_refresh_candidates(
                engine,
                limit=args.limit,
                require_orderbook_snapshot=True,
                label_version=str(args.label_version).strip(),
                include_already_labeled=bool(args.include_already_labeled),
            )
            used_explicit = False

        summary = refresh_markets_by_ticker(
            engine,
            client,
            tickers_to_refresh,
            batch_size=int(args.batch_size),
            dry_run=bool(args.dry_run),
        )
        payload = {
            "success": True,
            "used_explicit_tickers": used_explicit,
            "label_version": str(args.label_version).strip(),
            "summary": summary,
        }
        print(json.dumps(payload, indent=2, sort_keys=True, default=str), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error": f"{type(exc).__name__}: {exc}"}, default=str), flush=True)
        return 1
    finally:
        engine.dispose()
        client.close()


if __name__ == "__main__":
    sys.exit(main())
