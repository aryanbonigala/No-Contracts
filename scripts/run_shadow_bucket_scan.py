#!/usr/bin/env python3
"""Run NO bucket shadow scan (read-only market + orderbook GETs; paper entries only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Shadow-scan Kalshi active markets; simulate NO fills at fixed price buckets; "
            "persist compact rows — no orders, no portfolio endpoints."
        )
    )
    p.add_argument("--shadow-version", default=None)
    p.add_argument("--experiment-name", default=None)
    p.add_argument("--bucket-prices-cents", default=None, help="Comma-separated ints, e.g. 60,70,80,85,90,95")
    p.add_argument("--entry-tolerance-cents", type=int, default=None)
    p.add_argument("--paper-bankroll-cents", type=int, default=None)
    p.add_argument("--stake-cents-per-trade", type=int, default=None)
    p.add_argument("--allow-partial-fills", action="store_true")
    p.add_argument("--max-markets-per-scan", type=int, default=None)
    p.add_argument("--max-entries-per-scan", type=int, default=None)
    p.add_argument("--min-seconds-to-close", type=int, default=None)
    p.add_argument("--max-seconds-to-close", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(_ROOT / "src"))
    args = _parse_args(argv)
    from kalshi_no_carry.config import get_settings
    from kalshi_no_carry.database import create_engine_from_database_url
    from kalshi_no_carry.kalshi_client import KalshiClient
    from kalshi_no_carry.research.shadow_bucket_config import (
        DEFAULT_EXPERIMENT_NAME,
        DEFAULT_SHADOW_VERSION,
        BucketShadowConfig,
    )
    from kalshi_no_carry.research.shadow_bucket_experiment import run_bucket_shadow_scan_persisted
    from sqlalchemy.orm import sessionmaker

    settings = get_settings()
    if not settings.database_url:
        print("error: DATABASE_URL is required", file=sys.stderr)
        return 1

    buckets = None
    if args.bucket_prices_cents:
        buckets = tuple(int(x.strip()) for x in args.bucket_prices_cents.split(",") if x.strip())

    cfg = BucketShadowConfig(
        shadow_version=args.shadow_version or DEFAULT_SHADOW_VERSION,
        experiment_name=args.experiment_name or DEFAULT_EXPERIMENT_NAME,
        bucket_prices_cents=buckets or (60, 70, 80, 85, 90, 95),
        entry_tolerance_cents=args.entry_tolerance_cents
        if args.entry_tolerance_cents is not None
        else 1,
        paper_bankroll_cents=args.paper_bankroll_cents
        if args.paper_bankroll_cents is not None
        else 1_000_000,
        stake_cents_per_trade=args.stake_cents_per_trade
        if args.stake_cents_per_trade is not None
        else 10_000,
        allow_partial_fills=bool(args.allow_partial_fills),
        max_markets_per_scan=args.max_markets_per_scan,
        max_entries_per_scan=args.max_entries_per_scan,
        min_seconds_to_close=args.min_seconds_to_close,
        max_seconds_to_close=args.max_seconds_to_close,
        dry_run=bool(args.dry_run),
    )

    engine = create_engine_from_database_url(str(settings.database_url))
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    client = KalshiClient.from_settings(settings)
    try:
        with Session() as session:
            summary = run_bucket_shadow_scan_persisted(session, client, cfg)
            session.commit()
    finally:
        client.close()
        engine.dispose()

    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
