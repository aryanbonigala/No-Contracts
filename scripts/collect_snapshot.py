#!/usr/bin/env python3
"""Small end-to-end read-only snapshot: events, markets, a few orderbooks. Requires DATABASE_URL."""

from __future__ import annotations

import argparse
import json
import sys

from kalshi_no_carry.collectors.events import collect_events
from kalshi_no_carry.collectors.markets import collect_markets
from kalshi_no_carry.collectors.orderbooks import collect_orderbooks_for_markets
from kalshi_no_carry.config import get_settings
from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url
from kalshi_no_carry.kalshi_client import KalshiClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke: events + markets + N orderbooks (read-only).")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--orderbook-count", type=int, default=10)
    parser.add_argument("--create-tables", action="store_true")
    parser.add_argument("--skip-exchange", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.database_url:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        raise SystemExit(1)

    engine = create_engine_from_database_url(str(settings.database_url))
    result: dict = {}
    try:
        if args.create_tables:
            create_all_tables(engine)

        client = KalshiClient.from_settings(settings)
        try:
            if not args.skip_exchange:
                st = client.get_exchange_status()
                result["exchange_status_ok"] = True
                result["exchange_active"] = st.get("exchange_active")
                result["trading_active"] = st.get("trading_active")

            ev = collect_events(
                client, engine, limit=args.limit, max_pages=args.max_pages
            )
            mk = collect_markets(
                client, engine, limit=args.limit, max_pages=args.max_pages
            )
            tickers = mk.ids_collected[: max(0, args.orderbook_count)]
            ob = collect_orderbooks_for_markets(
                client, engine, tickers, fail_fast=False, sleep_seconds=0.0
            )
            result["events"] = ev.to_public_dict()
            result["markets"] = mk.to_public_dict()
            result["orderbooks"] = ob.to_public_dict()
        finally:
            client.close()
    finally:
        engine.dispose()

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
