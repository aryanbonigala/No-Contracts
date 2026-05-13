"""Read-only summaries of stored ingestion coverage (v0.15); no Kalshi HTTP."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.collectors.market_lifecycle import count_lifecycle_refresh_candidates
from kalshi_no_carry.db.schema import RawMarket, RawOrderbookSnapshot, ResearchFeatureRow, ResearchMarketLabel
from kalshi_no_carry.research.outcomes import DEFAULT_LABEL_VERSION


def feature_row_is_scorable(r: ResearchFeatureRow) -> bool:
    """Scorable predicate aligned with ``audit_research_dataset`` (executable quotes + usable label)."""
    lm = (r.label_market_result or "").strip().lower()
    return bool(
        r.has_complete_executable_prices
        and r.no_ask_cents is not None
        and not (r.label_is_void or (lm == "void"))
        and ((r.label_no_won is True or r.label_no_won is False) or (lm in ("yes", "no")))
    )


def summarize_collection_coverage(
    engine: Any,
    *,
    split_version: str,
    feature_version: str,
    label_version: str | None = None,
    include_test: bool = False,
) -> dict[str, Any]:
    """
    Aggregate counts for **data readiness** (not trading advice): market status mix, labels,
    orderbook executable-quote coverage, and scorable feature-row ratio for the audit slice.
    """
    sv = (split_version or "").strip()
    fv = (feature_version or "").strip()
    lv_opt = (label_version or "").strip() or None

    allowed_splits = {"train", "validation"}
    if include_test:
        allowed_splits.add("test")

    lv_eff = lv_opt or DEFAULT_LABEL_VERSION

    out: dict[str, Any] = {
        "coverage_version": "v0.15_collection_coverage",
        "split_version": sv,
        "feature_version": fv,
        "label_version": lv_opt,
        "raw_markets_by_status": {},
        "raw_markets_by_api_status_field": {},
        "labels_by_result": {},
        "orderbook_snapshots_total": 0,
        "orderbook_snapshots_with_yes_bids": 0,
        "orderbook_snapshots_with_no_bids": 0,
        "orderbook_snapshots_empty_executable": 0,
        "executable_no_ask_coverage_ratio": None,
        "executable_yes_ask_coverage_ratio": None,
        "markets_with_orderbook_snapshots": 0,
        "markets_with_orderbook_and_label": 0,
        "markets_with_orderbook_and_resolved_label": 0,
        "markets_with_orderbook_and_unknown_label": 0,
        "lifecycle_refresh_candidate_count": 0,
        "scorable_overlap_ratio": None,
        "research_feature_rows_in_scope": 0,
        "scorable_feature_rows_in_scope": 0,
        "scorable_feature_row_ratio": None,
        "data_readiness_notes": [],
    }

    maker = sessionmaker(engine, expire_on_commit=False, future=True)
    raw_n = 0
    with maker() as session:
        raw_n = int(session.scalar(select(func.count()).select_from(RawMarket)) or 0)

        # --- raw_markets_by_status (normalized ORM column)
        stmt_rm = select(RawMarket.status, func.count()).group_by(RawMarket.status)
        for k, n in session.execute(stmt_rm).all():
            key = str(k).strip().lower() if k is not None else "unknown"
            out["raw_markets_by_status"][key] = int(n or 0)

        # --- raw_markets_by_api_status_field (payload field; best-effort SQL group_by)
        api_status_counter: Counter[str] = Counter()
        try:
            js = RawMarket.raw_json["status"]
            stmt_js = select(js, func.count()).group_by(js)
            for k, n in session.execute(stmt_js).all():
                key = str(k).strip().lower() if k is not None and str(k).strip() else "unknown"
                api_status_counter[key] += int(n or 0)
        except Exception:
            for (rj,) in session.execute(select(RawMarket.raw_json)).all():
                if isinstance(rj, dict):
                    v = rj.get("status")
                    api_status_counter[str(v).strip().lower() if v is not None else "unknown"] += 1
        out["raw_markets_by_api_status_field"] = dict(sorted(api_status_counter.items()))

        # --- labels_by_result
        stmt_lb = select(ResearchMarketLabel.label_market_result, func.count()).group_by(
            ResearchMarketLabel.label_market_result
        )
        if lv_opt:
            stmt_lb = stmt_lb.where(ResearchMarketLabel.label_version == lv_opt)
        for k, n in session.execute(stmt_lb).all():
            key = str(k).strip().lower() if k is not None else "unknown"
            out["labels_by_result"][key] = int(n or 0)

        # --- orderbook columns (aggregates)
        total_ob = int(session.scalar(select(func.count()).select_from(RawOrderbookSnapshot)) or 0)
        out["orderbook_snapshots_total"] = total_ob
        yes_b = int(
            session.scalar(
                select(func.count()).select_from(RawOrderbookSnapshot).where(
                    RawOrderbookSnapshot.best_yes_bid_cents.isnot(None)
                )
            )
            or 0
        )
        no_b = int(
            session.scalar(
                select(func.count()).select_from(RawOrderbookSnapshot).where(
                    RawOrderbookSnapshot.best_no_bid_cents.isnot(None)
                )
            )
            or 0
        )
        ex_no = int(
            session.scalar(
                select(func.count()).select_from(RawOrderbookSnapshot).where(
                    RawOrderbookSnapshot.best_no_ask_cents.isnot(None)
                )
            )
            or 0
        )
        ex_yes = int(
            session.scalar(
                select(func.count()).select_from(RawOrderbookSnapshot).where(
                    RawOrderbookSnapshot.best_yes_ask_cents.isnot(None)
                )
            )
            or 0
        )
        out["orderbook_snapshots_with_yes_bids"] = yes_b
        out["orderbook_snapshots_with_no_bids"] = no_b
        # Empty with respect to derived executable bests (both asks missing)
        empty_ex = int(
            session.scalar(
                select(func.count())
                .select_from(RawOrderbookSnapshot)
                .where(
                    RawOrderbookSnapshot.best_no_ask_cents.is_(None),
                    RawOrderbookSnapshot.best_yes_ask_cents.is_(None),
                )
            )
            or 0
        )
        out["orderbook_snapshots_empty_executable"] = empty_ex

        if total_ob > 0:
            out["executable_no_ask_coverage_ratio"] = round(ex_no / total_ob, 6)
            out["executable_yes_ask_coverage_ratio"] = round(ex_yes / total_ob, 6)

        # --- lifecycle / label alignment on stored orderbook tickers (data readiness; not trading advice)
        ob_markets = int(
            session.scalar(select(func.count(func.distinct(RawOrderbookSnapshot.market_ticker)))) or 0
        )
        out["markets_with_orderbook_snapshots"] = ob_markets

        resolved_yes_no = and_(
            ResearchMarketLabel.label_is_resolved.is_(True),
            ResearchMarketLabel.label_market_result.in_(("yes", "no")),
            ResearchMarketLabel.label_is_void.is_(False),
        )
        lbl_join = and_(
            ResearchMarketLabel.market_ticker == RawOrderbookSnapshot.market_ticker,
            ResearchMarketLabel.label_version == lv_eff,
        )
        with_label = int(
            session.scalar(
                select(func.count(func.distinct(RawOrderbookSnapshot.market_ticker)))
                .select_from(RawOrderbookSnapshot)
                .join(ResearchMarketLabel, lbl_join)
            )
            or 0
        )
        out["markets_with_orderbook_and_label"] = with_label

        resolved_n = int(
            session.scalar(
                select(func.count(func.distinct(RawOrderbookSnapshot.market_ticker)))
                .select_from(RawOrderbookSnapshot)
                .join(ResearchMarketLabel, lbl_join)
                .where(resolved_yes_no)
            )
            or 0
        )
        out["markets_with_orderbook_and_resolved_label"] = resolved_n

        definitive = or_(
            and_(
                ResearchMarketLabel.label_is_resolved.is_(True),
                ResearchMarketLabel.label_market_result.in_(("yes", "no")),
            ),
            ResearchMarketLabel.label_is_void.is_(True),
            func.lower(func.coalesce(ResearchMarketLabel.label_market_result, "")) == "void",
        )
        unknown_align = int(
            session.scalar(
                select(func.count(func.distinct(RawOrderbookSnapshot.market_ticker)))
                .select_from(RawOrderbookSnapshot)
                .outerjoin(ResearchMarketLabel, lbl_join)
                .where(or_(ResearchMarketLabel.market_ticker.is_(None), not_(definitive)))
            )
            or 0
        )
        out["markets_with_orderbook_and_unknown_label"] = unknown_align

        out["lifecycle_refresh_candidate_count"] = count_lifecycle_refresh_candidates(
            engine,
            label_version=lv_eff,
            include_already_labeled=False,
            require_orderbook_snapshot=True,
        )

        if ob_markets > 0:
            out["scorable_overlap_ratio"] = round(resolved_n / ob_markets, 6)

        # --- feature rows in audit slice
        if sv and fv:
            fr_stmt = select(ResearchFeatureRow).where(
                ResearchFeatureRow.split_version == sv,
                ResearchFeatureRow.feature_version == fv,
                ResearchFeatureRow.split_name.in_(tuple(sorted(allowed_splits))),
            )
            fr_rows = list(session.scalars(fr_stmt).all())
            out["research_feature_rows_in_scope"] = len(fr_rows)
            scorable_n = sum(1 for r in fr_rows if feature_row_is_scorable(r))
            out["scorable_feature_rows_in_scope"] = scorable_n
            if fr_rows:
                out["scorable_feature_row_ratio"] = round(scorable_n / len(fr_rows), 6)

    notes: list[str] = []
    if total_ob > 0 and out["executable_no_ask_coverage_ratio"] is not None:
        if float(out["executable_no_ask_coverage_ratio"]) <= 0.0:
            notes.append(
                "DATA_READINESS: stored orderbook snapshots rarely expose a derived executable NO ask "
                "(often empty YES bid side or inactive books)."
            )
    if total_ob > 0 and empty_ex / total_ob > 0.5:
        notes.append(
            "DATA_READINESS: many snapshots lack both derived executable asks — orderbook liquidity "
            "may be thin or inactive at capture time."
        )
    fr_tot = int(out["research_feature_rows_in_scope"] or 0)
    if fr_tot > 0 and int(out["scorable_feature_rows_in_scope"] or 0) == 0:
        notes.append(
            "DATA_READINESS: no scorable feature rows in audit scope — check resolved labels merged "
            "into features and executable NO quotes."
        )
    lbl_total = sum(out["labels_by_result"].values()) if out["labels_by_result"] else 0
    if lbl_total == 0 and lv_opt and raw_n > 0:
        notes.append(
            f"DATA_READINESS: no rows in research_market_labels for label_version={lv_opt!r} — "
            "run label materialization after ingesting settled/closed markets."
        )
    out["data_readiness_notes"] = notes

    return out


__all__ = ["feature_row_is_scorable", "summarize_collection_coverage"]
