"""Dataset coverage and label-quality audit over stored research tables (v0.8; read-only)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from kalshi_no_carry.research.collection_coverage import feature_row_is_scorable, summarize_collection_coverage
from kalshi_no_carry.db.schema import (
    EventCluster,
    RawMarket,
    RawOrderbookSnapshot,
    ResearchFeatureRow,
    ResearchMarketLabel,
    StrategySplit,
)


def audit_research_dataset(
    engine: Any,
    *,
    split_version: str,
    feature_version: str,
    label_version: str | None = None,
    include_test: bool = False,
) -> dict[str, Any]:
    """
    Summarize row counts, join coverage, and label scorability.

    **Limitations:** orphan-path counts are best-effort single-hop diagnostics (see ``warnings``).
    Feature rows always respect ``include_test`` on ``split_name`` the same way as
    ``list_feature_rows_for_backtest`` (test omitted from filters unless ``include_test=True``).
    """
    sv = (split_version or "").strip()
    fv = (feature_version or "").strip()
    if not sv or not fv:
        raise ValueError("split_version and feature_version are required")

    warnings: list[str] = []
    lv_opt = (label_version or "").strip() or None

    allowed_splits = {"train", "validation"}
    if include_test:
        allowed_splits.add("test")
    else:
        warnings.append("TEST_SPLIT_EXCLUDED: audit metrics for feature rows omit sealed test by default.")

    out: dict[str, Any] = {
        "audit_version": "v0.8_dataset_audit",
        "split_version": sv,
        "feature_version": fv,
        "label_version": lv_opt,
        "include_test": include_test,
        "test_rows_included": include_test,
        "raw_markets_count": 0,
        "raw_orderbook_snapshots_count": 0,
        "event_clusters_count": 0,
        "strategy_splits_count": 0,
        "research_feature_rows_count": 0,
        "market_labels_count": 0,
        "feature_rows_by_split": {},
        "feature_rows_by_category": {},
        "feature_rows_with_complete_prices": 0,
        "feature_rows_missing_prices": 0,
        "feature_rows_with_label": 0,
        "feature_rows_without_label": 0,
        "resolved_yes_count": 0,
        "resolved_no_count": 0,
        "void_count": 0,
        "unknown_label_count": 0,
        "scorable_feature_rows": 0,
        "unscorable_feature_rows": 0,
        "snapshots_without_raw_market": 0,
        "markets_missing_cluster_by_event_ticker": 0,
        "clusters_missing_split_for_version": 0,
        "feature_rows_missing_no_ask": 0,
        "feature_rows_missing_close_time_reference": 0,
        "warnings": warnings,
        "success": True,
    }

    maker = sessionmaker(engine, expire_on_commit=False, future=True)
    with maker() as session:
        out["raw_markets_count"] = int(session.scalar(select(func.count()).select_from(RawMarket)) or 0)
        out["raw_orderbook_snapshots_count"] = int(
            session.scalar(select(func.count()).select_from(RawOrderbookSnapshot)) or 0
        )
        out["event_clusters_count"] = int(session.scalar(select(func.count()).select_from(EventCluster)) or 0)
        out["strategy_splits_count"] = int(
            session.scalar(select(func.count()).select_from(StrategySplit).where(StrategySplit.split_version == sv))
            or 0
        )

        fr_stmt = select(ResearchFeatureRow).where(
            ResearchFeatureRow.split_version == sv,
            ResearchFeatureRow.feature_version == fv,
            ResearchFeatureRow.split_name.in_(tuple(sorted(allowed_splits))),
        )
        fr_rows = list(session.scalars(fr_stmt).all())
        out["research_feature_rows_count"] = len(fr_rows)

        if lv_opt:
            out["market_labels_count"] = int(
                session.scalar(
                    select(func.count()).select_from(ResearchMarketLabel).where(
                        ResearchMarketLabel.label_version == lv_opt
                    )
                )
                or 0
            )

        by_split = Counter()
        by_cat = Counter()
        for r in fr_rows:
            by_split[r.split_name] += 1
            by_cat[str(r.category or "unknown")] += 1
            if r.has_complete_executable_prices:
                out["feature_rows_with_complete_prices"] += 1
            else:
                out["feature_rows_missing_prices"] += 1
            if r.no_ask_cents is None:
                out["feature_rows_missing_no_ask"] += 1
            if r.seconds_to_close is None:
                out["feature_rows_missing_close_time_reference"] += 1

            lm = (r.label_market_result or "").strip().lower()
            has_label_info = bool(r.outcome_label_version) or bool(lm)

            if has_label_info:
                out["feature_rows_with_label"] += 1
            else:
                out["feature_rows_without_label"] += 1

            if lm == "yes":
                out["resolved_yes_count"] += 1
            elif lm == "no":
                out["resolved_no_count"] += 1
            elif lm == "void" or r.label_is_void:
                out["void_count"] += 1
            else:
                out["unknown_label_count"] += 1

            scorable = feature_row_is_scorable(r)
            if scorable:
                out["scorable_feature_rows"] += 1
            else:
                out["unscorable_feature_rows"] += 1

        out["feature_rows_by_split"] = dict(sorted(by_split.items()))
        out["feature_rows_by_category"] = dict(sorted(by_cat.items()))

        # Coverage diagnostics (approximate)
        out["snapshots_without_raw_market"] = _count_snapshots_without_market(session)
        out["markets_missing_cluster_by_event_ticker"] = _count_markets_missing_cluster(session)
        out["clusters_missing_split_for_version"] = _count_clusters_missing_split(session, sv)

    cc = summarize_collection_coverage(
        engine,
        split_version=sv,
        feature_version=fv,
        label_version=lv_opt,
        include_test=include_test,
    )
    out["collection_coverage"] = cc
    for note in cc.get("data_readiness_notes") or []:
        if isinstance(note, str) and note.strip():
            warnings.append(note)

    return out


def _count_snapshots_without_market(session: Session) -> int:
    stmt = (
        select(func.count())
        .select_from(RawOrderbookSnapshot)
        .outerjoin(RawMarket, RawOrderbookSnapshot.market_ticker == RawMarket.market_ticker)
        .where(RawMarket.market_ticker.is_(None))
    )
    return int(session.scalar(stmt) or 0)


def _count_markets_missing_cluster(session: Session) -> int:
    stmt = (
        select(func.count())
        .select_from(RawMarket)
        .outerjoin(EventCluster, EventCluster.event_ticker == RawMarket.event_ticker)
        .where(RawMarket.event_ticker.is_not(None), EventCluster.cluster_id.is_(None))
    )
    return int(session.scalar(stmt) or 0)


def _count_clusters_missing_split(session: Session, split_version: str) -> int:
    stmt = (
        select(func.count())
        .select_from(EventCluster)
        .outerjoin(
            StrategySplit,
            (StrategySplit.cluster_id == EventCluster.cluster_id)
            & (StrategySplit.split_version == split_version),
        )
        .where(StrategySplit.cluster_id.is_(None))
    )
    return int(session.scalar(stmt) or 0)
