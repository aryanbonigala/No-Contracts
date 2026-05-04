#!/usr/bin/env python3
"""Run read-only NO-carry baseline backtests over ``research_feature_rows`` (no live trading)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_BACKTEST_VERSION = "v0.7_no_carry_baseline"
_DEFAULT_SPLIT_VERSION = "v0.5_chronological_60_20_20"
_DEFAULT_FEATURE_VERSION = "v0.6_orderbook_snapshot_features"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Hypothetical NO-carry backtest from stored feature rows only — "
            "no orders, no Kalshi execution, no portfolio."
        )
    )
    p.add_argument("--backtest-version", default=_DEFAULT_BACKTEST_VERSION)
    p.add_argument(
        "--strategy-name",
        default="no_carry_price_threshold_v0",
        help="Baseline strategy id (see research.backtest_config.SUPPORTED_STRATEGIES)",
    )
    p.add_argument("--split-version", default=_DEFAULT_SPLIT_VERSION)
    p.add_argument("--feature-version", default=_DEFAULT_FEATURE_VERSION)
    p.add_argument(
        "--include-test",
        action="store_true",
        help="Include sealed test split rows (default: train+validation only)",
    )
    p.add_argument("--splits", default="train,validation", help="Comma-separated split_name values")
    p.add_argument("--max-no-ask-cents", type=int, default=95)
    p.add_argument("--min-no-ask-cents", type=int, default=1)
    p.add_argument("--min-seconds-to-close", type=float, default=None)
    p.add_argument("--max-seconds-to-close", type=float, default=None)
    p.add_argument(
        "--allow-multiple-per-market",
        dest="one_trade_per_market",
        action="store_false",
        help="Allow multiple hypothetical entries per market (default: one per market)",
    )
    p.set_defaults(one_trade_per_market=True)
    p.add_argument(
        "--one-trade-per-cluster",
        action="store_true",
        help="Keep first eligible row per cluster_id",
    )
    p.add_argument("--limit", type=int, default=None, help="Max feature rows loaded from DB")
    p.add_argument("--market-ticker", action="append", dest="market_tickers", default=None)
    p.add_argument("--stake-cents", type=int, default=100)
    p.add_argument("--dry-run", action="store_true", help="Do not persist backtest_runs / backtest_trades")
    p.add_argument(
        "--delete-existing-run",
        action="store_true",
        help="Deprecated: ignored; same deterministic run_id is replaced automatically when persisting.",
    )
    p.add_argument(
        "--no-overwrite-existing-run",
        action="store_true",
        help="Do not delete an existing backtest_runs row first; a rerun with the same config raises IntegrityError.",
    )
    p.add_argument(
        "--create-tables",
        action="store_true",
        help="SQLAlchemy create_all for disposable dev DBs only",
    )
    p.add_argument(
        "--migrate",
        action="store_true",
        help="Run alembic upgrade head before backtest",
    )
    return p.parse_args(argv)


def _json_safe(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    from kalshi_no_carry.config import get_settings
    from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url
    from kalshi_no_carry.logging_setup import configure_logging
    from kalshi_no_carry.research.backtest_config import BacktestConfig
    from kalshi_no_carry.research.backtest_no_carry import compute_backtest_run_id, run_no_carry_backtest_persisted

    configure_logging()
    settings = get_settings()
    if not settings.database_url:
        print(_json_safe({"success": False, "error": "DATABASE_URL is required"}), flush=True)
        return 2

    split_parts = tuple(s.strip() for s in str(args.splits).split(",") if s.strip())
    if not split_parts:
        print(_json_safe({"success": False, "error": "--splits must list at least one split"}), flush=True)
        return 2

    one_per_market = bool(args.one_trade_per_market)

    try:
        config = BacktestConfig(
            backtest_version=str(args.backtest_version).strip(),
            strategy_name=str(args.strategy_name).strip(),
            split_version=str(args.split_version).strip(),
            feature_version=str(args.feature_version).strip(),
            include_splits=split_parts,
            include_test=bool(args.include_test),
            max_no_ask_cents=int(args.max_no_ask_cents),
            min_no_ask_cents=int(args.min_no_ask_cents),
            min_seconds_to_close=args.min_seconds_to_close,
            max_seconds_to_close=args.max_seconds_to_close,
            max_rows=args.limit,
            one_trade_per_market=one_per_market,
            one_trade_per_cluster=bool(args.one_trade_per_cluster),
            stake_cents=int(args.stake_cents),
        )
    except ValueError as e:
        print(_json_safe({"success": False, "error": str(e)}), flush=True)
        return 2

    run_id = compute_backtest_run_id(config)
    engine = create_engine_from_database_url(str(settings.database_url))

    try:
        if args.migrate:
            from alembic import command
            from alembic.config import Config

            cfg = Config(str(_ROOT / "alembic.ini"))
            command.upgrade(cfg, "head")

        if args.create_tables:
            create_all_tables(engine)

        out = run_no_carry_backtest_persisted(
            engine,
            config,
            dry_run=bool(args.dry_run),
            overwrite_existing_run=not bool(args.no_overwrite_existing_run),
            market_tickers=args.market_tickers,
        )
        out.pop("stage_name", None)
        print(_json_safe(out), flush=True)
        return 0 if out.get("success") else 1
    except Exception as e:
        print(_json_safe({"success": False, "error": str(e), "run_id": run_id}), flush=True)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
