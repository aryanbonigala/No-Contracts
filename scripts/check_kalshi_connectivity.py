#!/usr/bin/env python3
"""Read-only Kalshi connectivity diagnostics (no DATABASE_URL, no DB writes, no orders)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from kalshi_no_carry.config import get_settings, reset_settings_cache
from kalshi_no_carry.diagnostics.kalshi_connectivity import run_kalshi_connectivity_diagnostics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", action="append", default=[], help="Optional ticker symbol (repeatable)")
    parser.add_argument("--max-tickers", type=int, default=25, help="Cap ticker batch size (default: 25)")
    parser.add_argument("--timeout-seconds", type=float, default=None, help="Override Kalshi HTTP timeout for this run")
    parser.add_argument(
        "--show-sample-tickers",
        action="store_true",
        help="Include a small sanitized ticker sample in JSON output",
    )
    parser.add_argument(
        "--skip-auth-check",
        action="store_true",
        help="Skip authenticated read-only GET /events smoke (RSA signing)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Write the same JSON object to this path (optional)",
    )
    args = parser.parse_args(argv)

    reset_settings_cache()
    settings = get_settings()
    result: dict[str, Any] = run_kalshi_connectivity_diagnostics(
        settings=settings,
        tickers=args.ticker,
        timeout_seconds=args.timeout_seconds,
        include_auth_check=not args.skip_auth_check,
        max_tickers=int(args.max_tickers),
        include_ticker_sample=bool(args.show_sample_tickers),
    )

    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    sys.stdout.write(text)
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(text, encoding="utf-8")

    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
