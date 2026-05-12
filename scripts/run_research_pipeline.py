#!/usr/bin/env python3
"""Run the full read-only research pipeline (stored DB by default; collectors opt-in)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_PIPELINE_VERSION = "v0.9_research_pipeline_runner"
_DEFAULT_SPLIT_VERSION = "v0.5_chronological_60_20_20"
_DEFAULT_FEATURE_VERSION = "v0.6_orderbook_snapshot_features"
_DEFAULT_LABEL_VERSION = "v0.8_market_outcome_labels"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Orchestrate migrations (optional), collectors (optional), splits, labels, features, "
            "audit, and optional read-only backtest. Default: stored database only; no Kalshi."
        )
    )
    p.add_argument("--pipeline-version", default=_DEFAULT_PIPELINE_VERSION)
    p.add_argument("--split-version", default=_DEFAULT_SPLIT_VERSION)
    p.add_argument("--feature-version", default=_DEFAULT_FEATURE_VERSION)
    p.add_argument("--label-version", default=_DEFAULT_LABEL_VERSION)
    p.add_argument(
        "--backtest-version",
        default="v0.7_no_carry_baseline",
        help="Only used when --run-backtest",
    )
    p.add_argument(
        "--include-test",
        action="store_true",
        help="Include sealed test split in feature build, audit, and backtest (dangerous for honest evaluation).",
    )
    p.add_argument("--migrate", action="store_true", help="Run alembic upgrade head first")
    p.add_argument("--create-tables", action="store_true")
    p.add_argument(
        "--collect-markets",
        action="store_true",
        help="Fetch events+markets from Kalshi (requires credentials; off by default)",
    )
    p.add_argument(
        "--collect-orderbooks",
        action="store_true",
        help="Fetch orderbooks from Kalshi (requires credentials; off by default)",
    )
    p.add_argument(
        "--market-status",
        action="append",
        dest="market_statuses",
        default=None,
        help="Kalshi /markets status filter (repeat for multiple; each status is a separate API pass)",
    )
    p.add_argument(
        "--collect-status-set",
        choices=["active_and_resolved", "all_basic"],
        default=None,
        help="Coverage preset: open+settled or open+closed+settled (merged with --market-status)",
    )
    p.add_argument(
        "--orderbook-source-status",
        default="open",
        help="Market listing status used to seed tickers for --collect-orderbooks (default: open)",
    )
    p.add_argument(
        "--collect-max-pages",
        type=int,
        default=1,
        metavar="N",
        help="Max API pages per collector sub-call when --collect-markets / --collect-orderbooks (default: 1)",
    )
    p.add_argument("--market-ticker", action="append", dest="market_tickers", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--skip-splits", action="store_true")
    p.add_argument("--skip-labels", action="store_true")
    p.add_argument("--skip-features", action="store_true")
    p.add_argument("--skip-audit", action="store_true")
    p.add_argument("--run-backtest", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--delete-existing-features", action="store_true")
    p.add_argument("--delete-existing-labels", action="store_true")
    p.add_argument("--overwrite-splits", action="store_true")
    p.add_argument("--max-no-ask-cents", type=int, default=95)
    p.add_argument("--min-no-ask-cents", type=int, default=1)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    from kalshi_no_carry.config import get_settings
    from kalshi_no_carry.database import create_engine_from_database_url
    from kalshi_no_carry.kalshi_client import KalshiClient
    from kalshi_no_carry.logging_setup import configure_logging
    from kalshi_no_carry.research.pipeline_runner import ResearchPipelineConfig, run_research_pipeline

    configure_logging()
    settings = get_settings()
    if not settings.database_url:
        print(json.dumps({"success": False, "error": "DATABASE_URL is required"}), flush=True)
        return 2

    tickers = None
    if args.market_tickers:
        tickers = tuple(sorted({str(t).strip() for t in args.market_tickers if str(t).strip()}))

    ms_ordered: list[str] = []
    if args.market_statuses:
        seen_ms: set[str] = set()
        for x in args.market_statuses:
            t = str(x).strip().lower()
            if t and t not in seen_ms:
                seen_ms.add(t)
                ms_ordered.append(t)

    try:
        cfg = ResearchPipelineConfig(
            pipeline_version=str(args.pipeline_version).strip(),
            split_version=str(args.split_version).strip(),
            feature_version=str(args.feature_version).strip(),
            label_version=str(args.label_version).strip(),
            backtest_version=str(args.backtest_version).strip(),
            include_test=bool(args.include_test),
            run_migrations=bool(args.migrate),
            create_tables=bool(args.create_tables),
            collect_markets=bool(args.collect_markets),
            collect_orderbooks=bool(args.collect_orderbooks),
            build_splits=not bool(args.skip_splits),
            build_labels=not bool(args.skip_labels),
            build_features=not bool(args.skip_features),
            run_audit=not bool(args.skip_audit),
            run_backtest=bool(args.run_backtest),
            dry_run=bool(args.dry_run),
            limit=args.limit,
            market_tickers=tickers,
            delete_existing_features=bool(args.delete_existing_features),
            delete_existing_labels=bool(args.delete_existing_labels),
            overwrite_splits=bool(args.overwrite_splits),
            max_no_ask_cents=int(args.max_no_ask_cents),
            min_no_ask_cents=int(args.min_no_ask_cents),
            market_statuses=tuple(ms_ordered),
            collect_status_set=args.collect_status_set,
            orderbook_source_status=str(args.orderbook_source_status).strip(),
            collect_max_pages=int(args.collect_max_pages),
        )
    except ValueError as e:
        print(json.dumps({"success": False, "error": str(e)}), flush=True)
        return 2

    engine = create_engine_from_database_url(str(settings.database_url))
    client = None
    if cfg.collect_markets or cfg.collect_orderbooks:
        client = KalshiClient.from_settings(settings)
    try:
        summary = run_research_pipeline(engine, cfg, kalshi_client=client)
        print(json.dumps(summary, default=str, sort_keys=True), flush=True)
        return 0 if summary.get("success") else 1
    except Exception as exc:
        print(
            json.dumps({"success": False, "error": f"{type(exc).__name__}: {exc}"}, default=str),
            flush=True,
        )
        return 1
    finally:
        engine.dispose()
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
