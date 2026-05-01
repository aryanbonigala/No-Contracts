#!/usr/bin/env python3
"""Ingest Kalshi orderbook snapshots (read-only). Requires DATABASE_URL."""

from __future__ import annotations

import argparse
import json
import sys

from kalshi_no_carry.collectors.orderbooks import (
    collect_orderbooks_for_active_markets,
    collect_orderbooks_for_markets,
)
from kalshi_no_carry.config import get_settings
from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url
from kalshi_no_carry.kalshi_client import KalshiClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect orderbook snapshots (read-only).")
    parser.add_argument("--ticker", action="append", default=[], dest="tickers")
    parser.add_argument("--active-markets", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--depth", type=int, default=None)
    parser.add_argument("--create-tables", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    args = parser.parse_args()

    if not args.active_markets and not args.tickers:
        print(
            "error: pass --ticker one or more times or use --active-markets",
            file=sys.stderr,
        )
        raise SystemExit(1)

    settings = get_settings()
    if not settings.database_url:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        raise SystemExit(1)

    engine = create_engine_from_database_url(str(settings.database_url))
    try:
        if args.create_tables:
            create_all_tables(engine)

        client = KalshiClient.from_settings(settings)
        try:
            if args.active_markets:
                out = collect_orderbooks_for_active_markets(
                    client,
                    engine,
                    limit=args.limit,
                    max_pages=args.max_pages,
                    depth=args.depth,
                    fail_fast=args.fail_fast,
                    sleep_seconds=args.sleep_seconds,
                )
                print(json.dumps(out.to_public_dict(), indent=2))
            else:
                ob = collect_orderbooks_for_markets(
                    client,
                    engine,
                    args.tickers,
                    depth=args.depth,
                    fail_fast=args.fail_fast,
                    sleep_seconds=args.sleep_seconds,
                )
                print(json.dumps(ob.to_public_dict(), indent=2))
        finally:
            client.close()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
