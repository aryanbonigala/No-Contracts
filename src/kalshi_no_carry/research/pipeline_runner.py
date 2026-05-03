"""End-to-end read-only research pipeline orchestration (v0.9)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.engine import Engine

from kalshi_no_carry.collectors.common import safe_error_message
from kalshi_no_carry.research.backtest_config import (
    STRATEGY_NO_CARRY_PRICE_THRESHOLD_V0,
    BacktestConfig,
)
from kalshi_no_carry.research.build_splits import (
    SplitVersionExistsError,
    assign_chronological_splits,
    build_event_clusters_from_raw_data,
)
from kalshi_no_carry.research.dataset_audit import audit_research_dataset
from kalshi_no_carry.research.feature_dataset import build_research_feature_rows_pipeline
from kalshi_no_carry.research.outcomes import build_market_outcome_labels_from_raw_markets
from kalshi_no_carry.research.backtest_no_carry import run_no_carry_backtest_persisted

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PIPELINE_VERSION = "v0.9_research_pipeline_runner"


class ResearchPipelineConfig(BaseModel):
    """Ordered stages for materializing research artifacts from stored (or freshly collected) DB state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pipeline_version: str = Field(default=_DEFAULT_PIPELINE_VERSION, min_length=1)
    split_version: str = Field(default="v0.5_chronological_60_20_20", min_length=1)
    feature_version: str = Field(default="v0.6_orderbook_snapshot_features", min_length=1)
    label_version: str = Field(default="v0.8_market_outcome_labels", min_length=1)
    backtest_version: str = Field(default="v0.7_no_carry_baseline", min_length=1)

    include_test: bool = False
    run_migrations: bool = False
    collect_markets: bool = False
    collect_orderbooks: bool = False
    build_splits: bool = True
    build_labels: bool = True
    build_features: bool = True
    run_audit: bool = True
    run_backtest: bool = False
    dry_run: bool = False
    create_tables: bool = False
    limit: int | None = None
    market_tickers: tuple[str, ...] | None = None
    delete_existing_features: bool = False
    delete_existing_labels: bool = False
    overwrite_splits: bool = False
    max_no_ask_cents: int = Field(default=95, ge=0, le=100)
    min_no_ask_cents: int = Field(default=1, ge=0, le=100)
    collect_max_pages: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _ask_bounds(self) -> ResearchPipelineConfig:
        if int(self.min_no_ask_cents) > int(self.max_no_ask_cents):
            raise ValueError("min_no_ask_cents must be <= max_no_ask_cents")
        return self


def _disabled(stage_name: str) -> dict[str, Any]:
    return {
        "stage_name": stage_name,
        "enabled": False,
        "success": True,
        "skipped": True,
        "warnings": [],
    }


def _alembic_upgrade_head() -> None:
    import os

    from alembic import command
    from alembic.config import Config

    from kalshi_no_carry.config import get_settings

    settings = get_settings()
    if settings.database_url:
        os.environ["DATABASE_URL"] = str(settings.database_url)
    ini = _PROJECT_ROOT / "alembic.ini"
    if not ini.is_file():
        raise FileNotFoundError("alembic.ini not found at project root")
    cfg = Config(str(ini))
    command.upgrade(cfg, "head")


def recommend_next_action(summary: dict[str, Any] | None = None) -> str:
    """Suggest the next offline research step from a pipeline JSON summary (never live trading)."""
    if summary is None:
        summary = {}
    h = summary.get("high_level_counts") or {}
    aud = summary.get("audit_summary") or {}
    stages = summary.get("stages") or {}

    def _ic(key: str) -> int:
        for src in (h, aud):
            v = src.get(key)
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return 0
        return 0

    rm = _ic("raw_markets_count")
    ro = _ic("raw_orderbook_snapshots_count")
    ec = _ic("event_clusters_count")
    ss = _ic("strategy_splits_count")
    ml = _ic("market_labels_count")
    fr = _ic("research_feature_rows_count")
    scorable = _ic("scorable_feature_rows")
    unknown_lab = _ic("unknown_label_count")

    if rm == 0 and not (stages.get("collect_markets") or {}).get("enabled"):
        return "Run collectors with collect_markets enabled (or load raw_markets another offline way)."
    if ro == 0 and not (stages.get("collect_orderbooks") or {}).get("enabled"):
        return "Ingest orderbook snapshots (collect_orderbooks) before feature rows."
    if ec == 0 or ss == 0:
        return "Build event clusters and splits (build_splits stage) once raw_events/raw_markets exist."
    if ml == 0 and not (stages.get("build_labels") or {}).get("enabled"):
        return "Materialize research_market_labels from raw_markets (build_labels)."
    if fr == 0:
        return "Build research_feature_rows (build_features) for the chosen split_version and feature_version."
    if unknown_lab > max(10, fr // 5) and fr > 0:
        return "Inspect raw market result/status fields; many labels are unknown — improve source data or extraction rules (new label_version)."
    if scorable < max(50, fr // 10) and fr > 0:
        return "Increase coverage of resolved markets and linked orderbook snapshots to grow scorable rows (read-only collection or imports)."
    if scorable >= 200:
        return "Dataset is reasonably sized for a v1.0 probability baseline or deeper read-only backtest analysis (train/validation first)."
    return "Review audit_summary warnings and stage outputs; iterate on collectors or label quality before modeling."


def run_research_pipeline(
    engine: Engine,
    config: ResearchPipelineConfig,
    kalshi_client: Any | None = None,
) -> dict[str, Any]:
    """
    Execute enabled stages in order; returns one JSON-safe summary dict.

    Network collectors run **only** when ``collect_markets`` or ``collect_orderbooks`` is true;
    pass a real ``kalshi_client`` from production CLIs, or tests may inject a stub.
    """
    warnings: list[str] = []
    if config.include_test:
        warnings.append(
            "TEST_SPLIT_INCLUDED: sealed test rows are included — do not tune strategy thresholds to fit this split."
        )

    stages: dict[str, Any] = {}
    failed_stage: str | None = None
    audit_summary: dict[str, Any] | None = None
    backtest_summary: dict[str, Any] | None = None

    def _fail(stage: str, exc: BaseException) -> dict[str, Any]:
        return {
            "stage_name": stage,
            "enabled": True,
            "success": False,
            "warnings": [],
            "error_type": type(exc).__name__,
            "error_message": safe_error_message(exc),
        }

    # 1 migrate
    if config.run_migrations:
        try:
            _alembic_upgrade_head()
            stages["migrate"] = {
                "stage_name": "migrate",
                "enabled": True,
                "success": True,
                "warnings": [],
                "detail": "alembic upgrade head",
            }
        except Exception as exc:
            stages["migrate"] = _fail("migrate", exc)
            failed_stage = "migrate"
    else:
        stages["migrate"] = _disabled("migrate")

    if failed_stage:
        return _finalize(
            config=config,
            success=False,
            failed_stage=failed_stage,
            stages=stages,
            warnings=warnings,
            audit_summary=None,
            backtest_summary=None,
        )

    from kalshi_no_carry.database import create_all_tables

    if config.create_tables:
        try:
            create_all_tables(engine)
            stages["create_tables"] = {
                "stage_name": "create_tables",
                "enabled": True,
                "success": True,
                "warnings": [],
            }
        except Exception as exc:
            stages["create_tables"] = _fail("create_tables", exc)
            failed_stage = "create_tables"
    else:
        stages["create_tables"] = _disabled("create_tables")

    if failed_stage:
        return _finalize(
            config=config,
            success=False,
            failed_stage=failed_stage,
            stages=stages,
            warnings=warnings,
            audit_summary=None,
            backtest_summary=None,
        )

    # 2 collect markets / events
    if config.collect_markets:
        if kalshi_client is None:
            exc = ValueError("collect_markets requires kalshi_client (explicit collector stage)")
            stages["collect_markets"] = _fail("collect_markets", exc)
            failed_stage = "collect_markets"
        else:
            try:
                from kalshi_no_carry.collectors.events import collect_events
                from kalshi_no_carry.collectors.markets import collect_markets

                lim = int(config.limit or 100)
                ev = collect_events(
                    kalshi_client,
                    engine,
                    limit=lim,
                    max_pages=config.collect_max_pages,
                )
                mk = collect_markets(
                    kalshi_client,
                    engine,
                    limit=lim,
                    max_pages=config.collect_max_pages,
                )
                stages["collect_markets"] = {
                    "stage_name": "collect_markets",
                    "enabled": True,
                    "success": bool(ev.success and mk.success),
                    "warnings": list(ev.errors) + list(mk.errors),
                    "events": ev.to_public_dict(),
                    "markets": mk.to_public_dict(),
                }
                if not stages["collect_markets"]["success"]:
                    failed_stage = "collect_markets"
            except Exception as exc:
                stages["collect_markets"] = _fail("collect_markets", exc)
                failed_stage = "collect_markets"
    else:
        stages["collect_markets"] = _disabled("collect_markets")

    if failed_stage:
        return _finalize(
            config=config,
            success=False,
            failed_stage=failed_stage,
            stages=stages,
            warnings=warnings,
            audit_summary=None,
            backtest_summary=None,
        )

    # 3 collect orderbooks
    if config.collect_orderbooks:
        if kalshi_client is None:
            exc = ValueError("collect_orderbooks requires kalshi_client (explicit collector stage)")
            stages["collect_orderbooks"] = _fail("collect_orderbooks", exc)
            failed_stage = "collect_orderbooks"
        else:
            try:
                from kalshi_no_carry.collectors.orderbooks import (
                    collect_orderbooks_for_active_markets,
                    collect_orderbooks_for_markets,
                )

                lim = int(config.limit or 100)
                if config.market_tickers:
                    ob = collect_orderbooks_for_markets(
                        kalshi_client,
                        engine,
                        list(config.market_tickers),
                    )
                    stages["collect_orderbooks"] = {
                        "stage_name": "collect_orderbooks",
                        "enabled": True,
                        "success": ob.success,
                        "warnings": list(ob.errors),
                        "orderbooks": ob.to_public_dict(),
                    }
                else:
                    ob = collect_orderbooks_for_active_markets(
                        kalshi_client,
                        engine,
                        limit=lim,
                        max_pages=config.collect_max_pages,
                    )
                    stages["collect_orderbooks"] = {
                        "stage_name": "collect_orderbooks",
                        "enabled": True,
                        "success": ob.success,
                        "warnings": list(ob.errors),
                        "orderbooks": ob.to_public_dict(),
                    }
                if not stages["collect_orderbooks"]["success"]:
                    failed_stage = "collect_orderbooks"
            except Exception as exc:
                stages["collect_orderbooks"] = _fail("collect_orderbooks", exc)
                failed_stage = "collect_orderbooks"
    else:
        stages["collect_orderbooks"] = _disabled("collect_orderbooks")

    if failed_stage:
        return _finalize(
            config=config,
            success=False,
            failed_stage=failed_stage,
            stages=stages,
            warnings=warnings,
            audit_summary=None,
            backtest_summary=None,
        )

    # 4 splits
    if config.build_splits:
        try:
            clusters = build_event_clusters_from_raw_data(engine)
            splits = assign_chronological_splits(
                engine,
                config.split_version,
                overwrite=config.overwrite_splits,
            )
            stages["build_splits"] = {
                "stage_name": "build_splits",
                "enabled": True,
                "success": bool(clusters.get("success") and splits.get("success")),
                "warnings": list(clusters.get("warnings") or []) + list(splits.get("warnings") or []),
                "clusters": {k: v for k, v in clusters.items() if k != "warnings"},
                "splits": {k: v for k, v in splits.items() if k != "warnings"},
            }
        except SplitVersionExistsError as exc:
            stages["build_splits"] = {
                "stage_name": "build_splits",
                "enabled": True,
                "success": False,
                "warnings": [],
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
            failed_stage = "build_splits"
        except Exception as exc:
            stages["build_splits"] = _fail("build_splits", exc)
            failed_stage = "build_splits"
    else:
        stages["build_splits"] = _disabled("build_splits")

    if failed_stage:
        return _finalize(
            config=config,
            success=False,
            failed_stage=failed_stage,
            stages=stages,
            warnings=warnings,
            audit_summary=None,
            backtest_summary=None,
        )

    # 5 labels
    if config.build_labels:
        try:
            lb = build_market_outcome_labels_from_raw_markets(
                engine,
                label_version=config.label_version,
                market_tickers=list(config.market_tickers) if config.market_tickers else None,
                limit=config.limit,
                delete_existing=config.delete_existing_labels,
            )
            stages["build_labels"] = {
                "stage_name": "build_labels",
                "enabled": True,
                "success": bool(lb.get("success", True)),
                "warnings": list(lb.get("warnings") or []),
                **{k: v for k, v in lb.items() if k not in ("warnings", "success")},
            }
            if not stages["build_labels"]["success"]:
                failed_stage = "build_labels"
        except Exception as exc:
            stages["build_labels"] = _fail("build_labels", exc)
            failed_stage = "build_labels"
    else:
        stages["build_labels"] = _disabled("build_labels")

    if failed_stage:
        return _finalize(
            config=config,
            success=False,
            failed_stage=failed_stage,
            stages=stages,
            warnings=warnings,
            audit_summary=None,
            backtest_summary=None,
        )

    # 6 features
    if config.build_features:
        try:
            feat = build_research_feature_rows_pipeline(
                engine,
                split_version=config.split_version,
                feature_version=config.feature_version,
                label_version=config.label_version,
                include_splits=None,
                include_test=config.include_test,
                market_tickers=list(config.market_tickers) if config.market_tickers else None,
                limit=config.limit,
                delete_existing=config.delete_existing_features,
                dry_run=config.dry_run,
            )
            stages["build_features"] = {
                "stage_name": "build_features",
                "enabled": True,
                "success": bool(feat.get("success", True)),
                "warnings": list(feat.get("warnings") or []),
                **{k: v for k, v in feat.items() if k not in ("warnings", "success", "stage_name")},
            }
            if not stages["build_features"]["success"]:
                failed_stage = "build_features"
        except Exception as exc:
            stages["build_features"] = _fail("build_features", exc)
            failed_stage = "build_features"
    else:
        stages["build_features"] = _disabled("build_features")

    if failed_stage:
        return _finalize(
            config=config,
            success=False,
            failed_stage=failed_stage,
            stages=stages,
            warnings=warnings,
            audit_summary=None,
            backtest_summary=None,
        )

    # 7 audit
    if config.run_audit:
        try:
            audit_summary = audit_research_dataset(
                engine,
                split_version=config.split_version,
                feature_version=config.feature_version,
                label_version=config.label_version,
                include_test=config.include_test,
            )
            stages["audit"] = {
                "stage_name": "audit",
                "enabled": True,
                "success": bool(audit_summary.get("success", True)),
                "warnings": list(audit_summary.get("warnings") or []),
            }
            if not stages["audit"]["success"]:
                failed_stage = "audit"
        except Exception as exc:
            stages["audit"] = _fail("audit", exc)
            failed_stage = "audit"
            audit_summary = None
    else:
        stages["audit"] = _disabled("audit")

    if failed_stage:
        return _finalize(
            config=config,
            success=False,
            failed_stage=failed_stage,
            stages=stages,
            warnings=warnings,
            audit_summary=audit_summary,
            backtest_summary=None,
        )

    # 8 backtest
    if config.run_backtest:
        try:
            inc = ("train", "validation", "test") if config.include_test else ("train", "validation")
            btc = BacktestConfig(
                backtest_version=config.backtest_version,
                strategy_name=STRATEGY_NO_CARRY_PRICE_THRESHOLD_V0,
                split_version=config.split_version,
                feature_version=config.feature_version,
                include_splits=inc,
                include_test=config.include_test,
                max_no_ask_cents=config.max_no_ask_cents,
                min_no_ask_cents=config.min_no_ask_cents,
                max_rows=config.limit,
            )
            bt = run_no_carry_backtest_persisted(
                engine,
                btc,
                dry_run=config.dry_run,
                delete_existing_run=False,
                market_tickers=list(config.market_tickers) if config.market_tickers else None,
            )
            backtest_summary = bt
            stages["backtest"] = {
                "stage_name": "backtest",
                "enabled": True,
                "success": bool(bt.get("success", True)),
                "warnings": list(bt.get("warnings") or []),
                "run_id": bt.get("run_id"),
                "rows_seen": bt.get("rows_seen"),
                "scored_trades": bt.get("scored_trades"),
                "dry_run": bt.get("dry_run"),
            }
            if not stages["backtest"]["success"]:
                failed_stage = "backtest"
        except Exception as exc:
            stages["backtest"] = _fail("backtest", exc)
            failed_stage = "backtest"
    else:
        stages["backtest"] = _disabled("backtest")

    success = failed_stage is None
    return _finalize(
        config=config,
        success=success,
        failed_stage=failed_stage,
        stages=stages,
        warnings=warnings,
        audit_summary=audit_summary,
        backtest_summary=backtest_summary if config.run_backtest else None,
    )


def _finalize(
    *,
    config: ResearchPipelineConfig,
    success: bool,
    failed_stage: str | None,
    stages: dict[str, Any],
    warnings: list[str],
    audit_summary: dict[str, Any] | None,
    backtest_summary: dict[str, Any] | None,
) -> dict[str, Any]:
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
        "pipeline_version": config.pipeline_version,
        "split_version": config.split_version,
        "feature_version": config.feature_version,
        "label_version": config.label_version,
        "backtest_version": config.backtest_version,
        "include_test": config.include_test,
        "success": success,
        "failed_stage": failed_stage,
        "stages": stages,
        "warnings": warnings,
        "audit_summary": audit_summary,
        "backtest_summary": backtest_summary,
        "high_level_counts": high_level_counts,
    }
    body["next_recommended_action"] = recommend_next_action(body)
    return body


__all__ = [
    "ResearchPipelineConfig",
    "recommend_next_action",
    "run_research_pipeline",
]
