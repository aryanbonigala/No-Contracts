#!/usr/bin/env python3
"""Read-only smoke test against Kalshi public market endpoints (no orders)."""

from __future__ import annotations

import argparse
import json
import sys

from kalshi_no_carry.config import get_settings
from kalshi_no_carry.kalshi_client import KalshiClient, derive_executable_prices_from_orderbook
from kalshi_no_carry.logging_setup import configure_logging


def _pick_title(m: dict) -> str | None:
    return m.get("title") or m.get("yes_sub_title") or m.get("subtitle")


def main() -> None:
    configure_logging("INFO")
    parser = argparse.ArgumentParser(description="Fetch a small markets sample (read-only).")
    parser.add_argument(
        "--ticker",
        default=None,
        help="If set, fetch this market and its orderbook.",
    )
    args = parser.parse_args()

    settings = get_settings()
    client = KalshiClient.from_settings(settings)
    try:
        status = client.get_exchange_status()
        print("exchange_status:", json.dumps(status, sort_keys=True))
        print()

        if args.ticker:
            market = client.get_market(args.ticker)
            print("market:", json.dumps(market, sort_keys=True)[:4000])
            print()
            book = client.get_orderbook(args.ticker)
            derived = derive_executable_prices_from_orderbook(book)
            print("orderbook_derived:", json.dumps(derived, sort_keys=True))
            return

        page = client.get_markets(limit=5)
        markets = page.get("markets") or []
        print(f"markets_returned={len(markets)} cursor_present={'cursor' in page}")
        for m in markets:
            if not isinstance(m, dict):
                continue
            ticker = m.get("ticker")
            title = _pick_title(m)
            row = {
                "ticker": ticker,
                "title": title,
                "yes_bid_dollars": m.get("yes_bid_dollars"),
                "yes_ask_dollars": m.get("yes_ask_dollars"),
                "no_bid_dollars": m.get("no_bid_dollars"),
                "no_ask_dollars": m.get("no_ask_dollars"),
            }
            print(json.dumps(row, sort_keys=True))
    finally:
        client.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — CLI smoke script
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
