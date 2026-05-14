"""Settlement scoring for shadow bucket entries (read-only DB updates)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from kalshi_no_carry.db.repositories import fetch_unscored_shadow_bucket_entries
from kalshi_no_carry.db.schema import (
    RawMarket,
    ResearchMarketLabel,
    ShadowBucketEntry,
    ShadowBucketMarketObservation,
)
from kalshi_no_carry.research.outcomes import (
    DEFAULT_LABEL_VERSION,
    LABEL_NO,
    LABEL_UNKNOWN,
    LABEL_VOID,
    LABEL_YES,
    extract_market_outcome_label_from_row,
)

WIN_AFTER_FEES = "WIN_AFTER_FEES"
WON_BUT_FEES_ERASED_PROFIT = "WON_BUT_FEES_ERASED_PROFIT"
WON_BUT_BAD_FILL_ERASED_PROFIT = "WON_BUT_BAD_FILL_ERASED_PROFIT"
LOST_RESOLVED_YES = "LOST_RESOLVED_YES"
UNRESOLVED = "UNRESOLVED"
DATA_ERROR = "DATA_ERROR"
SPECIAL_OR_AMBIGUOUS_RESOLUTION = "SPECIAL_OR_AMBIGUOUS_RESOLUTION"

MARKET_NOT_RESOLVED = "MARKET_NOT_RESOLVED"
LABEL_MISSING = "LABEL_MISSING"
OUTCOME_AMBIGUOUS = "OUTCOME_AMBIGUOUS"
INVALID_ENTRY = "INVALID_ENTRY"
DATA_ERROR_REASON = "DATA_ERROR"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fetch_label_row(session: Session, market_ticker: str, label_version: str) -> ResearchMarketLabel | None:
    stmt = select(ResearchMarketLabel).where(
        ResearchMarketLabel.market_ticker == market_ticker.strip(),
        ResearchMarketLabel.label_version == label_version.strip(),
    )
    return session.execute(stmt).scalar_one_or_none()


def resolve_shadow_market_outcome(
    session: Session,
    *,
    market_ticker: str,
    label_version: str | None,
) -> dict[str, Any]:
    mt = market_ticker.strip()
    out: dict[str, Any] = {
        "no_won": None,
        "yes_won": None,
        "is_void": False,
        "ambiguous": False,
        "unresolved": False,
        "settlement_status": None,
        "settlement_result": None,
        "resolved_at": None,
        "label_missing": False,
    }

    lv_use = (label_version or "").strip()
    lbl: ResearchMarketLabel | None = None
    if lv_use:
        lbl = _fetch_label_row(session, mt, lv_use)
        if lbl is not None:
            out["settlement_result"] = lbl.label_market_result
            if lbl.label_is_void or lbl.label_market_result == LABEL_VOID:
                out["is_void"] = True
                out["ambiguous"] = True
                out["resolved_at"] = lbl.extracted_at
                return out
            if lbl.label_is_resolved:
                if lbl.label_no_won is True:
                    out["no_won"] = True
                    out["yes_won"] = False
                    out["resolved_at"] = lbl.extracted_at
                    return out
                if lbl.label_yes_won is True:
                    out["no_won"] = False
                    out["yes_won"] = True
                    out["resolved_at"] = lbl.extracted_at
                    return out
            lm = str(lbl.label_market_result or "").strip().lower()
            if lm == LABEL_YES:
                out["no_won"] = False
                out["yes_won"] = True
                out["resolved_at"] = lbl.extracted_at
                return out
            if lm == LABEL_NO:
                out["no_won"] = True
                out["yes_won"] = False
                out["resolved_at"] = lbl.extracted_at
                return out

    rm = session.get(RawMarket, mt)
    if rm is None:
        out["unresolved"] = True
        if lv_use and lbl is None:
            out["label_missing"] = True
        return out

    out["settlement_status"] = rm.status
    out["settlement_result"] = rm.result or out["settlement_result"]
    extracted = extract_market_outcome_label_from_row(
        rm,
        label_version=lv_use or DEFAULT_LABEL_VERSION,
        extracted_at=_utcnow(),
    )
    if extracted.get("label_is_void"):
        out["is_void"] = True
        out["ambiguous"] = True
        out["resolved_at"] = rm.settlement_time or extracted.get("extracted_at")
        return out

    lm = str(extracted.get("label_market_result") or LABEL_UNKNOWN).strip().lower()
    if lm == LABEL_VOID:
        out["is_void"] = True
        out["ambiguous"] = True
        out["resolved_at"] = rm.settlement_time or extracted.get("extracted_at")
        return out

    if extracted.get("label_is_resolved"):
        nw = extracted.get("label_no_won")
        yw = extracted.get("label_yes_won")
        if nw is True:
            out["no_won"] = True
            out["yes_won"] = False
            out["resolved_at"] = rm.settlement_time or extracted.get("extracted_at")
            return out
        if yw is True:
            out["no_won"] = False
            out["yes_won"] = True
            out["resolved_at"] = rm.settlement_time or extracted.get("extracted_at")
            return out

    if lm == LABEL_YES:
        out["no_won"] = False
        out["yes_won"] = True
        out["resolved_at"] = rm.settlement_time or extracted.get("extracted_at")
        return out
    if lm == LABEL_NO:
        out["no_won"] = True
        out["yes_won"] = False
        out["resolved_at"] = rm.settlement_time or extracted.get("extracted_at")
        return out

    status_s = str(rm.status or "").strip().lower()
    if not status_s and isinstance(rm.raw_json, dict):
        status_s = str(rm.raw_json.get("status") or "").strip().lower()
    if status_s in {"open", "active", "initialized", "unopened", "pre_open", "created"}:
        out["unresolved"] = True
        return out

    out["ambiguous"] = True
    return out


def _sync_observation_for_market(
    session: Session,
    entry: ShadowBucketEntry,
    *,
    settlement_status: str | None,
    settlement_result: str | None,
    scored_obs: bool,
) -> None:
    stmt = select(ShadowBucketMarketObservation).where(
        and_(
            ShadowBucketMarketObservation.shadow_version == entry.shadow_version,
            ShadowBucketMarketObservation.experiment_name == entry.experiment_name,
            ShadowBucketMarketObservation.market_ticker == entry.market_ticker,
        )
    )
    obs = session.execute(stmt).scalar_one_or_none()
    if obs is None:
        return
    obs.settlement_status = settlement_status or obs.settlement_status
    obs.settlement_result = settlement_result or obs.settlement_result
    obs.scored = scored_obs
    obs.updated_at = _utcnow()
    session.add(obs)


def score_shadow_bucket_entries(
    session: Session,
    shadow_version: str,
    *,
    label_version: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    entries = fetch_unscored_shadow_bucket_entries(session, shadow_version, limit=limit)
    summary: dict[str, Any] = {
        "shadow_version": shadow_version,
        "label_version": label_version,
        "entries_considered": len(entries),
        "entries_scored": 0,
        "entries_unresolved": 0,
        "entries_ambiguous": 0,
        "entries_error": 0,
        "gross_pnl_cents": 0,
        "fee_cents": 0,
        "net_pnl_cents": 0,
        "scored_by_bucket": {},
        "result_categories": {},
    }

    by_bucket: dict[str, dict[str, Any]] = {}
    for b in (60, 70, 80, 85, 90, 95):
        by_bucket[str(b)] = {
            "entries_scored": 0,
            "wins": 0,
            "losses": 0,
            "gross_pnl_cents": 0,
            "fees_cents": 0,
            "net_pnl_cents": 0,
        }

    def bump_cat(cat: str, gp: int, fee: int, net: int) -> None:
        rc = summary["result_categories"]
        if cat not in rc:
            rc[cat] = {"count": 0, "gross_pnl_cents": 0, "fees_cents": 0, "net_pnl_cents": 0}
        rc[cat]["count"] += 1
        rc[cat]["gross_pnl_cents"] += gp
        rc[cat]["fees_cents"] += fee
        rc[cat]["net_pnl_cents"] += net

    for ent in entries:
        now = _utcnow()
        cf = int(ent.contracts_filled or 0)
        gross_cost = int(ent.gross_cost_cents or 0)
        fee_cents = int(ent.fee_cents or 0)

        if cf <= 0 or gross_cost < 0 or fee_cents < 0:
            ent.result_category = DATA_ERROR
            ent.unscored_reason = INVALID_ENTRY
            ent.scored = False
            ent.updated_at = now
            session.add(ent)
            summary["entries_error"] += 1
            bump_cat(DATA_ERROR, 0, 0, 0)
            continue

        meta = resolve_shadow_market_outcome(session, market_ticker=ent.market_ticker, label_version=label_version)
        ent.settlement_status = meta.get("settlement_status")
        ent.settlement_result = meta.get("settlement_result")

        if meta.get("label_missing"):
            ent.result_category = UNRESOLVED
            ent.unscored_reason = LABEL_MISSING
            ent.scored = False
            ent.updated_at = now
            session.add(ent)
            summary["entries_unresolved"] += 1
            bump_cat(UNRESOLVED, 0, 0, 0)
            _sync_observation_for_market(
                session,
                ent,
                settlement_status=ent.settlement_status,
                settlement_result=ent.settlement_result,
                scored_obs=False,
            )
            continue

        if meta.get("is_void") or meta.get("ambiguous"):
            ent.result_category = SPECIAL_OR_AMBIGUOUS_RESOLUTION
            ent.unscored_reason = OUTCOME_AMBIGUOUS
            ent.scored = False
            ent.resolved_at = meta.get("resolved_at")
            ent.updated_at = now
            session.add(ent)
            summary["entries_ambiguous"] += 1
            bump_cat(SPECIAL_OR_AMBIGUOUS_RESOLUTION, 0, 0, 0)
            _sync_observation_for_market(
                session,
                ent,
                settlement_status=ent.settlement_status,
                settlement_result=ent.settlement_result,
                scored_obs=False,
            )
            continue

        if meta.get("unresolved") or meta.get("no_won") is None:
            ent.result_category = UNRESOLVED
            ent.unscored_reason = MARKET_NOT_RESOLVED
            ent.scored = False
            ent.updated_at = now
            session.add(ent)
            summary["entries_unresolved"] += 1
            bump_cat(UNRESOLVED, 0, 0, 0)
            _sync_observation_for_market(session, ent, settlement_status=ent.settlement_status, settlement_result=ent.settlement_result, scored_obs=False)
            continue

        no_won = bool(meta.get("no_won"))
        max_payout = cf * 100
        if max_payout <= 0:
            ent.result_category = DATA_ERROR
            ent.unscored_reason = DATA_ERROR_REASON
            ent.scored = False
            ent.updated_at = now
            session.add(ent)
            summary["entries_error"] += 1
            bump_cat(DATA_ERROR, 0, 0, 0)
            continue

        if no_won:
            gross_pnl = max_payout - gross_cost
        else:
            gross_pnl = -gross_cost
        net_pnl = gross_pnl - fee_cents
        fee_drag = gross_pnl - net_pnl

        ent.gross_pnl_cents = gross_pnl
        ent.net_pnl_cents = net_pnl
        ent.fee_drag_cents = fee_drag
        ent.resolved_at = meta.get("resolved_at")
        ent.scored = True
        ent.unscored_reason = None

        if no_won:
            if net_pnl > 0:
                ent.result_category = WIN_AFTER_FEES
            elif gross_pnl > 0:
                ent.result_category = WON_BUT_FEES_ERASED_PROFIT
            else:
                ent.result_category = WON_BUT_BAD_FILL_ERASED_PROFIT
        else:
            ent.result_category = LOST_RESOLVED_YES

        ent.updated_at = now
        session.add(ent)

        summary["entries_scored"] += 1
        summary["gross_pnl_cents"] += gross_pnl
        summary["fee_cents"] += fee_cents
        summary["net_pnl_cents"] += net_pnl
        bump_cat(str(ent.result_category), gross_pnl, fee_cents, net_pnl)

        bk = str(ent.bucket_price_cents)
        if bk in by_bucket:
            bb = by_bucket[bk]
            bb["entries_scored"] += 1
            bb["gross_pnl_cents"] += gross_pnl
            bb["fees_cents"] += fee_cents
            bb["net_pnl_cents"] += net_pnl
            if net_pnl > 0:
                bb["wins"] += 1
            elif net_pnl < 0:
                bb["losses"] += 1

        _sync_observation_for_market(
            session,
            ent,
            settlement_status=ent.settlement_status,
            settlement_result=ent.settlement_result,
            scored_obs=True,
        )

    summary["scored_by_bucket"] = by_bucket
    return summary
