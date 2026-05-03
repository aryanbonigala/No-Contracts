#!/usr/bin/env python3
"""Run the research pipeline and write a Markdown + JSON audit report (read-only; no live trading)."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_REPORT_VERSION = "v0.10_research_report"
_DEFAULT_SPLIT_VERSION = "v0.5_chronological_60_20_20"
_DEFAULT_FEATURE_VERSION = "v0.6_orderbook_snapshot_features"
_DEFAULT_LABEL_VERSION = "v0.8_market_outcome_labels"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Execute the stored-data research pipeline, compute readiness, and write report.md + summary.json. "
            "Test split excluded unless --include-test. "
            "--dry-run runs a read-only audit preview only (no DB mutations, no report files)."
        )
    )
    p.add_argument("--output-dir", default="reports", help="Directory under cwd for report folders")
    p.add_argument(
        "--report-name",
        default=None,
        help="Subfolder name under output-dir (default: UTC timestamp yyyymmdd_HHMMSS)",
    )
    p.add_argument("--pipeline-version", default=_DEFAULT_REPORT_VERSION)
    p.add_argument("--split-version", default=_DEFAULT_SPLIT_VERSION)
    p.add_argument("--feature-version", default=_DEFAULT_FEATURE_VERSION)
    p.add_argument("--label-version", default=_DEFAULT_LABEL_VERSION)
    p.add_argument(
        "--backtest-version",
        default="v0.7_no_carry_baseline",
        help="Only when --run-backtest (suppressed under --dry-run)",
    )
    p.add_argument(
        "--include-test",
        action="store_true",
        help="Include sealed test split in audit scope (document why)",
    )
    p.add_argument("--run-backtest", action="store_true")
    p.add_argument("--migrate", action="store_true")
    p.add_argument("--create-tables", action="store_true")
    p.add_argument("--skip-splits", action="store_true")
    p.add_argument("--skip-labels", action="store_true")
    p.add_argument("--skip-features", action="store_true")
    p.add_argument("--skip-audit", action="store_true")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Read-only preview: audit only if not skipped; no DB writes, no migrations, no report files",
    )
    p.add_argument("--delete-existing-features", action="store_true")
    p.add_argument("--delete-existing-labels", action="store_true")
    p.add_argument("--overwrite-splits", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--market-ticker", action="append", dest="market_tickers", default=None)
    p.add_argument("--max-no-ask-cents", type=int, default=95)
    p.add_argument("--min-no-ask-cents", type=int, default=1)
    return p.parse_args(argv)


def _disabled_stage(stage_name: str) -> dict[str, Any]:
    return {
        "stage_name": stage_name,
        "enabled": False,
        "success": True,
        "skipped": True,
        "warnings": [],
    }


def _suppressed_write_stage(stage_name: str, *, user_requested: bool, reason: str) -> dict[str, Any]:
    return {
        "stage_name": stage_name,
        "enabled": bool(user_requested),
        "success": True,
        "skipped": True,
        "dry_run_no_database_writes": True,
        "warnings": [reason],
    }


def collect_ignored_write_flags_for_dry_run(args: argparse.Namespace) -> list[str]:
    """Stable ids for write-oriented CLI requests suppressed under ``--dry-run``."""
    out: list[str] = []
    if args.migrate:
        out.append("migrate")
    if args.create_tables:
        out.append("create_tables")
    if args.delete_existing_labels:
        out.append("delete_existing_labels")
    if args.delete_existing_features:
        out.append("delete_existing_features")
    if args.overwrite_splits:
        out.append("overwrite_splits")
    if not args.skip_splits:
        out.append("build_splits")
    if not args.skip_labels:
        out.append("build_labels")
    if not args.skip_features:
        out.append("build_features")
    if args.run_backtest:
        out.append("persist_backtest")
    return out


def build_dry_run_preview_summary(
    engine: Any,
    args: argparse.Namespace,
    *,
    ignored_write_flags: list[str],
) -> dict[str, Any]:
    """Read-only preview: ``audit_research_dataset`` only (unless audit skipped). No mutations."""
    from kalshi_no_carry.research.dataset_audit import audit_research_dataset
    from kalshi_no_carry.research.pipeline_runner import recommend_next_action

    warnings: list[str] = [
        "DRY_RUN_PREVIEW: no report files written; no database writes (migrations, DDL, labels, features, splits, backtest persistence all suppressed).",
    ]
    if ignored_write_flags:
        warnings.append(
            "Suppressed write-oriented CLI requests due to dry_run=true: " + ", ".join(sorted(set(ignored_write_flags)))
        )

    stages: dict[str, Any] = {}

    if args.migrate:
        stages["migrate"] = _suppressed_write_stage(
            "migrate",
            user_requested=True,
            reason="dry_run=true: Alembic migrations are not run.",
        )
    else:
        stages["migrate"] = _disabled_stage("migrate")

    if args.create_tables:
        stages["create_tables"] = _suppressed_write_stage(
            "create_tables",
            user_requested=True,
            reason="dry_run=true: create_all_tables is not run.",
        )
    else:
        stages["create_tables"] = _disabled_stage("create_tables")

    stages["collect_markets"] = _disabled_stage("collect_markets")
    stages["collect_orderbooks"] = _disabled_stage("collect_orderbooks")

    if not args.skip_splits:
        stages["build_splits"] = _suppressed_write_stage(
            "build_splits",
            user_requested=True,
            reason="dry_run=true: event clusters / strategy_splits materialization skipped.",
        )
    else:
        stages["build_splits"] = _disabled_stage("build_splits")

    if not args.skip_labels:
        stages["build_labels"] = _suppressed_write_stage(
            "build_labels",
            user_requested=True,
            reason="dry_run=true: research_market_labels writes skipped.",
        )
    else:
        stages["build_labels"] = _disabled_stage("build_labels")

    if not args.skip_features:
        stages["build_features"] = _suppressed_write_stage(
            "build_features",
            user_requested=True,
            reason="dry_run=true: research_feature_rows writes skipped.",
        )
    else:
        stages["build_features"] = _disabled_stage("build_features")

    audit_summary: dict[str, Any] | None = None
    failed_stage: str | None = None
    audit_ok = True

    if args.skip_audit:
        stages["audit"] = _disabled_stage("audit")
        warnings.append(
            "Audit skipped (--skip-audit); preview uses no fresh audit payload — readiness verdict may be incomplete."
        )
    else:
        try:
            audit_summary = audit_research_dataset(
                engine,
                split_version=str(args.split_version).strip(),
                feature_version=str(args.feature_version).strip(),
                label_version=str(args.label_version).strip() or None,
                include_test=bool(args.include_test),
            )
            stages["audit"] = {
                "stage_name": "audit",
                "enabled": True,
                "success": bool(audit_summary.get("success", True)),
                "skipped": False,
                "dry_run_readonly": True,
                "warnings": list(audit_summary.get("warnings") or []),
            }
            warnings.extend(audit_summary.get("warnings") or [])
        except Exception as exc:
            audit_ok = False
            failed_stage = "audit"
            stages["audit"] = {
                "stage_name": "audit",
                "enabled": True,
                "success": False,
                "skipped": False,
                "dry_run_readonly": True,
                "warnings": [f"{type(exc).__name__}: {exc}"],
            }
            warnings.append(f"audit_research_dataset failed during dry-run preview: {type(exc).__name__}: {exc}")

    if args.run_backtest:
        stages["backtest"] = _suppressed_write_stage(
            "backtest",
            user_requested=True,
            reason="dry_run=true: read-only backtest persistence (backtest_runs/backtest_trades) skipped.",
        )
    else:
        stages["backtest"] = _disabled_stage("backtest")

    high_level_counts: dict[str, Any] = {}
    if audit_summary:
        for key in (
            "raw_markets_count",
            "raw_orderbook_snapshots_count",
            "event_clusters_count",
            "strategy_splits_count",
            "market_labels_count",
            "research_feature_rows_count",
            "scorable_feature_rows",
            "unscorable_feature_rows",
        ):
            if key in audit_summary:
                high_level_counts[key] = audit_summary[key]

    body: dict[str, Any] = {
        "pipeline_version": str(args.pipeline_version).strip(),
        "split_version": str(args.split_version).strip(),
        "feature_version": str(args.feature_version).strip(),
        "label_version": str(args.label_version).strip(),
        "backtest_version": str(args.backtest_version).strip(),
        "include_test": bool(args.include_test),
        "success": audit_ok and failed_stage is None,
        "failed_stage": failed_stage,
        "stages": stages,
        "warnings": warnings,
        "audit_summary": audit_summary,
        "backtest_summary": None,
        "high_level_counts": high_level_counts,
        "dry_run_preview": True,
        "files_written": False,
        "database_writes_performed": False,
        "ignored_write_flags": list(ignored_write_flags),
    }
    body["next_recommended_action"] = recommend_next_action(body)
    return body


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    from kalshi_no_carry.config import get_settings
    from kalshi_no_carry.database import create_engine_from_database_url
    from kalshi_no_carry.logging_setup import configure_logging
    from kalshi_no_carry.research.pipeline_runner import ResearchPipelineConfig, run_research_pipeline
    from kalshi_no_carry.research.reporting import (
        build_research_audit_report,
        compute_research_readiness,
    )

    configure_logging()
    settings = get_settings()
    if not settings.database_url:
        print(json.dumps({"success": False, "error": "DATABASE_URL is required"}), flush=True)
        return 2

    tickers = None
    if args.market_tickers:
        tickers = tuple(sorted({str(t).strip() for t in args.market_tickers if str(t).strip()}))

    engine = create_engine_from_database_url(str(settings.database_url))
    ignored_for_stdout: list[str] = []
    try:
        if args.dry_run:
            ignored_for_stdout = collect_ignored_write_flags_for_dry_run(args)
            pipeline_summary = build_dry_run_preview_summary(
                engine, args, ignored_write_flags=ignored_for_stdout
            )
        else:
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
                    collect_markets=False,
                    collect_orderbooks=False,
                    build_splits=not bool(args.skip_splits),
                    build_labels=not bool(args.skip_labels),
                    build_features=not bool(args.skip_features),
                    run_audit=not bool(args.skip_audit),
                    run_backtest=bool(args.run_backtest),
                    dry_run=False,
                    limit=args.limit,
                    market_tickers=tickers,
                    delete_existing_features=bool(args.delete_existing_features),
                    delete_existing_labels=bool(args.delete_existing_labels),
                    overwrite_splits=bool(args.overwrite_splits),
                    max_no_ask_cents=int(args.max_no_ask_cents),
                    min_no_ask_cents=int(args.min_no_ask_cents),
                )
            except ValueError as e:
                print(json.dumps({"success": False, "error": str(e)}), flush=True)
                return 2
            pipeline_summary = run_research_pipeline(engine, cfg, kalshi_client=None)
    except Exception as exc:
        print(
            json.dumps({"success": False, "error": f"{type(exc).__name__}: {exc}"}, default=str),
            flush=True,
        )
        return 1
    finally:
        engine.dispose()

    readiness = compute_research_readiness(pipeline_summary)
    markdown = build_research_audit_report(pipeline_summary)

    report_version = _DEFAULT_REPORT_VERSION
    if args.report_name:
        sub = Path(str(args.report_name).strip()).name.replace("/", "_").replace("..", "_")
    else:
        sub = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    base = Path(args.output_dir).expanduser().resolve() / sub
    summary_path = base / "summary.json"
    report_path = base / "report.md"

    artifact: dict[str, Any] = {
        "report_version": report_version,
        "dry_run": bool(args.dry_run),
        "readiness": readiness,
        "pipeline_summary": pipeline_summary,
        "ignored_write_flags": list(ignored_for_stdout) if args.dry_run else [],
        "files_written": not bool(args.dry_run),
        "database_writes_performed": not bool(args.dry_run),
    }

    files_written = False
    if not args.dry_run:
        base.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(artifact, indent=2, sort_keys=True, default=str), encoding="utf-8")
        report_path.write_text(markdown, encoding="utf-8")
        files_written = True

    printed: dict[str, Any] = {
        "database_writes_performed": False if args.dry_run else True,
        "dry_run": bool(args.dry_run),
        "files_written": files_written,
        "include_test": bool(args.include_test),
        "ignored_write_flags": list(ignored_for_stdout) if args.dry_run else [],
        "output_dir": str(base) if files_written else None,
        "pipeline_success": bool(pipeline_summary.get("success")),
        "readiness_level": readiness.get("readiness_level"),
        "report_md": str(report_path) if files_written else None,
        "report_version": report_version,
        "success": bool(pipeline_summary.get("success")),
        "summary_json": str(summary_path) if files_written else None,
        "warnings": list(pipeline_summary.get("warnings") or [])[:24],
    }
    print(json.dumps(printed, indent=2, sort_keys=True, default=str), flush=True)
    return 0 if pipeline_summary.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
