#!/usr/bin/env python3
"""Ingest Kalshi events and markets into Postgres (read-only). Requires DATABASE_URL."""

from __future__ import annotations

import argparse
import json
import sys

from kalshi_no_carry.collectors.events import collect_events
from kalshi_no_carry.collectors.markets import collect_markets
from kalshi_no_carry.config import get_settings
from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url
from kalshi_no_carry.kalshi_client import KalshiClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect events + markets (read-only).")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--status", type=str, default=None)
    parser.add_argument("--series-ticker", type=str, default=None)
    parser.add_argument("--create-tables", action="store_true")
    args = parser.parse_args()

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
            ev = collect_events(
                client,
                engine,
                limit=args.limit,
                max_pages=args.max_pages,
                status=args.status,
                series_ticker=args.series_ticker,
            )
            mk = collect_markets(
                client,
                engine,
                limit=args.limit,
                max_pages=args.max_pages,
                status=args.status,
                series_ticker=args.series_ticker,
            )
        finally:
            client.close()
        print(json.dumps({"events": ev.to_public_dict(), "markets": mk.to_public_dict()}, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
