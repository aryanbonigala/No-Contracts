"""Build validated ``ResearchFeatureRow`` payloads from joined raw data (v0.6)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.db.schema import (
    EventCluster,
    RawMarket,
    RawOrderbookSnapshot,
    ResearchFeatureRow,
    ResearchMarketLabel,
    StrategySplit,
)
from kalshi_no_carry.research.features import (
    compute_mid_cents,
    compute_no_carry_fields,
    compute_spread_cents,
    compute_time_to_close_seconds,
    market_side_crossed_or_locked,
    missing_price_reason_code,
    near_close_flags,
    seconds_to_time_bucket_features,
    summarize_orderbook_depth,
    utc_hour_and_weekday,
    has_complete_executable_quotes,
)

@dataclass(frozen=True)
class JoinedFeatureSource:
    """ORM join path: orderbook snapshot + market + cluster + split (+ optional event title)."""

    snapshot: RawOrderbookSnapshot
    market: RawMarket
    cluster: EventCluster
    split: StrategySplit
    event_title: str | None


def build_feature_row_from_joined_record(
    source: JoinedFeatureSource,
    *,
    feature_version: str,
    outcome_label: ResearchMarketLabel | None = None,
) -> ResearchFeatureRow:
    """
    Deterministic feature row at ``snapshot.fetched_at`` using only information
    knowable from stored rows at snapshot time.

    **Labels:** Orderbook/market structure feeds *features*; outcomes never enter
    pricing math. When ``outcome_label`` is set, normalized label columns are copied
    from ``research_market_labels`` (scoring / audit only). When omitted, legacy
    ``label_market_result = raw_markets.result`` is kept and extended label columns
    stay unset (v0.6-compatible).
    """
    ob = source.snapshot
    rm = source.market
    ec = source.cluster
    sp = source.split
    now = datetime.now(timezone.utc)

    ref_close = rm.close_time or ec.close_time or rm.expiration_time
    sec_to_close = compute_time_to_close_seconds(ob.fetched_at, ref_close)
    minutes_tc, hours_tc, days_tc = seconds_to_time_bucket_features(sec_to_close)
    n1, n6, n24 = near_close_flags(sec_to_close)
    hour_utc, dow_utc = utc_hour_and_weekday(ob.fetched_at)

    y_mid = compute_mid_cents(ob.best_yes_bid_cents, ob.best_yes_ask_cents)
    n_mid = compute_mid_cents(ob.best_no_bid_cents, ob.best_no_ask_cents)
    y_sp = compute_spread_cents(ob.best_yes_bid_cents, ob.best_yes_ask_cents)
    n_sp = compute_spread_cents(ob.best_no_bid_cents, ob.best_no_ask_cents)

    nc = compute_no_carry_fields(
        no_ask_cents=ob.best_no_ask_cents,
        no_bid_cents=ob.best_no_bid_cents,
    )
    complete = has_complete_executable_quotes(
        best_yes_bid_cents=ob.best_yes_bid_cents,
        best_yes_ask_cents=ob.best_yes_ask_cents,
        best_no_bid_cents=ob.best_no_bid_cents,
        best_no_ask_cents=ob.best_no_ask_cents,
    )
    miss = missing_price_reason_code(
        best_yes_bid_cents=ob.best_yes_bid_cents,
        best_yes_ask_cents=ob.best_yes_ask_cents,
        best_no_bid_cents=ob.best_no_bid_cents,
        best_no_ask_cents=ob.best_no_ask_cents,
    )

    depth = summarize_orderbook_depth(ob.raw_json if isinstance(ob.raw_json, dict) else None)

    if outcome_label is not None:
        label_market_result = outcome_label.label_market_result
        label_no_won = outcome_label.label_no_won
        label_yes_won = outcome_label.label_yes_won
        label_is_resolved = outcome_label.label_is_resolved
        label_is_void = outcome_label.label_is_void
        label_confidence = outcome_label.label_confidence
        outcome_label_version = outcome_label.label_version
    else:
        label_market_result = rm.result
        label_no_won = None
        label_yes_won = None
        label_is_resolved = None
        label_is_void = None
        label_confidence = None
        outcome_label_version = None

    return ResearchFeatureRow(
        snapshot_id=ob.id,
        split_version=sp.split_version,
        feature_version=feature_version.strip(),
        market_ticker=ob.market_ticker,
        event_ticker=rm.event_ticker,
        cluster_id=ec.cluster_id,
        split_name=sp.split_name,
        fetched_at=ob.fetched_at,
        market_title=rm.title,
        event_title=source.event_title,
        representative_title=ec.representative_title,
        series_ticker=rm.series_ticker or ec.series_ticker,
        category=rm.category or ec.category,
        market_status=rm.status,
        market_close_time=rm.close_time,
        market_expiration_time=rm.expiration_time,
        market_settlement_time=rm.settlement_time,
        best_yes_bid_cents=ob.best_yes_bid_cents,
        best_yes_ask_cents=ob.best_yes_ask_cents,
        best_no_bid_cents=ob.best_no_bid_cents,
        best_no_ask_cents=ob.best_no_ask_cents,
        yes_bid_size=ob.best_yes_bid_size,
        yes_ask_size=ob.best_yes_ask_size,
        no_bid_size=ob.best_no_bid_size,
        no_ask_size=ob.best_no_ask_size,
        yes_mid_cents=y_mid,
        no_mid_cents=n_mid,
        yes_spread_cents=y_sp,
        no_spread_cents=n_sp,
        yes_market_crossed_or_locked=market_side_crossed_or_locked(
            ob.best_yes_bid_cents, ob.best_yes_ask_cents
        ),
        no_market_crossed_or_locked=market_side_crossed_or_locked(
            ob.best_no_bid_cents, ob.best_no_ask_cents
        ),
        seconds_to_close=sec_to_close,
        minutes_to_close=minutes_tc,
        hours_to_close=hours_tc,
        days_to_close=days_tc,
        snapshot_hour_utc=hour_utc,
        snapshot_day_of_week_utc=dow_utc,
        is_near_close_1h=n1,
        is_near_close_6h=n6,
        is_near_close_24h=n24,
        no_ask_cents=ob.best_no_ask_cents,
        no_bid_cents=ob.best_no_bid_cents,
        no_cost_cents=nc.no_cost_cents,
        no_payout_cents=nc.no_payout_cents,
        gross_no_profit_if_correct_cents=nc.gross_no_profit_if_correct_cents,
        gross_no_loss_if_wrong_cents=nc.gross_no_loss_if_wrong_cents,
        required_no_probability_before_fees=nc.required_no_probability_before_fees,
        estimated_taker_fee_cents=nc.estimated_taker_fee_cents,
        required_no_probability_after_fees=nc.required_no_probability_after_fees,
        no_edge_placeholder=None,
        has_complete_executable_prices=complete,
        missing_price_reason=miss,
        raw_orderbook_depth_summary=depth,
        label_market_result=label_market_result,
        label_no_won=label_no_won,
        label_yes_won=label_yes_won,
        label_is_resolved=label_is_resolved,
        label_is_void=label_is_void,
        label_confidence=label_confidence,
        outcome_label_version=outcome_label_version,
        created_at=now,
    )


def validate_feature_row(row: ResearchFeatureRow) -> list[str]:
    """Return a list of human-readable issues (empty if row passes minimal checks)."""
    issues: list[str] = []
    if not row.feature_version or not row.feature_version.strip():
        issues.append("feature_version must be non-empty")
    if not row.split_version or not row.split_version.strip():
        issues.append("split_version must be non-empty")
    if row.split_name not in ("train", "validation", "test"):
        issues.append("split_name must be train, validation, or test")
    if row.snapshot_id is None or int(row.snapshot_id) < 1:
        issues.append("snapshot_id must be positive")
    if row.no_payout_cents < 1:
        issues.append("no_payout_cents must be positive")
    if row.outcome_label_version and row.label_market_result:
        allowed = {"yes", "no", "void", "unknown"}
        if str(row.label_market_result).strip().lower() not in allowed:
            issues.append("label_market_result must be yes, no, void, or unknown when outcome_label_version is set")
    return issues


def build_research_feature_rows_pipeline(
    engine: Engine,
    *,
    split_version: str,
    feature_version: str,
    label_version: str | None = None,
    include_splits: Sequence[str] | None = None,
    include_test: bool = False,
    market_tickers: list[str] | None = None,
    limit: int | None = None,
    delete_existing: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Materialize ``research_feature_rows`` from stored snapshots (shared by CLI and v0.9 pipeline).

    When ``include_splits`` is omitted, defaults to **train** and **validation**; **test** is included
    only when ``include_test=True`` (mirrors ``list_orderbook_snapshots_for_feature_building``).
    """
    from kalshi_no_carry.db.repositories import (
        bulk_upsert_research_feature_rows,
        delete_research_feature_rows_for_version,
        list_orderbook_snapshots_for_feature_building,
        load_market_outcome_labels_by_ticker,
    )

    sv = (split_version or "").strip()
    fv = (feature_version or "").strip()
    if not sv or not fv:
        return {"success": False, "error": "split_version and feature_version are required", "warnings": []}

    if include_splits is None:
        parts: list[str] = ["train", "validation"]
        if include_test:
            parts.append("test")
        split_parts: tuple[str, ...] = tuple(parts)
    else:
        split_parts = tuple(str(x).strip() for x in include_splits if str(x).strip())
        if not split_parts:
            return {"success": False, "error": "include_splits must list at least one split", "warnings": []}

    warnings: list[str] = []
    out: dict[str, Any] = {
        "success": True,
        "stage_name": "build_features",
        "split_version": sv,
        "feature_version": fv,
        "include_test": bool(include_test),
        "splits_requested": list(split_parts),
        "rows_seen": 0,
        "rows_built": 0,
        "rows_written": 0,
        "rows_skipped": 0,
        "missing_price_rows": 0,
        "missing_close_time_rows": 0,
        "label_version": (str(label_version).strip() if label_version else None),
        "warnings": warnings,
        "dry_run": bool(dry_run),
    }

    maker = sessionmaker(engine, expire_on_commit=False, future=True)
    with maker() as session:
        with session.begin():
            if delete_existing and not dry_run:
                delete_research_feature_rows_for_version(
                    session,
                    split_version=sv,
                    feature_version=fv,
                )

            sources = list_orderbook_snapshots_for_feature_building(
                session,
                split_version=sv,
                include_splits=split_parts,
                include_test=bool(include_test),
                market_tickers=market_tickers,
                limit=limit,
            )
            out["rows_seen"] = len(sources)

            label_ver = (str(label_version).strip() if label_version else None) or None
            labels_map: dict[str, Any] = {}
            if label_ver:
                tickers = sorted({src.market.market_ticker for src in sources})
                labels_map = load_market_outcome_labels_by_ticker(
                    session, label_version=label_ver, market_tickers=tickers
                )
                missing = [t for t in tickers if t not in labels_map]
                if missing:
                    warnings.append(
                        f"label_version={label_ver!r} missing labels for {len(missing)} / {len(tickers)} markets in this batch"
                    )

            rows: list[ResearchFeatureRow] = []
            for src in sources:
                ol = labels_map.get(src.market.market_ticker) if label_ver else None
                row = build_feature_row_from_joined_record(
                    src,
                    feature_version=fv,
                    outcome_label=ol,
                )
                issues = validate_feature_row(row)
                if issues:
                    out["rows_skipped"] += 1
                    warnings.append(f"skip snapshot {row.snapshot_id}: {issues}")
                    continue
                out["rows_built"] += 1
                if not row.has_complete_executable_prices:
                    out["missing_price_rows"] += 1
                if row.seconds_to_close is None:
                    out["missing_close_time_rows"] += 1
                if not dry_run:
                    rows.append(row)

            if not dry_run and rows:
                bulk_upsert_research_feature_rows(session, rows)
                out["rows_written"] = len(rows)
            elif dry_run:
                out["rows_written"] = 0
            else:
                out["rows_written"] = len(rows)

    return out
