"""Deterministic market outcome labeling from stored raw market payloads (v0.8; read-only)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import sessionmaker

# Normalized label_market_result values stored on rows
LABEL_YES = "yes"
LABEL_NO = "no"
LABEL_VOID = "void"
LABEL_UNKNOWN = "unknown"

_DEFAULT_LABEL_VERSION = "v0.8_market_outcome_labels"

# Status / result tokens implying no tradable outcome (conservative void family)
_VOID_STATUS_TOKENS = frozenset(
    {
        "void",
        "voided",
        "canceled",
        "cancelled",
        "annulled",
        "no_contest",
        "no contest",
        "abandoned",
        "scnd",
        "settled_cancel",
    }
)

_VOID_RESULT_TOKENS = frozenset(
    {
        "void",
        "scnd",
        "canceled",
        "cancelled",
        "none",
        "null",
    }
)

_YES_TOKENS = frozenset({"yes", "y"})
_NO_TOKENS = frozenset({"no", "n"})

_UNRESOLVED_STATUS_TOKENS = frozenset(
    {
        "open",
        "active",
        "initialized",
        "unopened",
        "pre_open",
        "created",
    }
)


def _lower(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    return s if s else None


def _coerce_lookup_dict(raw_market: Mapping[str, Any]) -> dict[str, Any]:
    """Single shallow dict: explicit keys beat duplicate keys inside ``raw_json`` when both exist."""
    out: dict[str, Any] = {}
    inner = raw_market.get("raw_json")
    if isinstance(inner, dict):
        out.update(inner)
    for k, v in raw_market.items():
        if k == "raw_json":
            continue
        if v is not None and v != "":
            out[k] = v
    return out


def _first_present(d: dict[str, Any], keys: tuple[str, ...]) -> tuple[Any, str | None]:
    for k in keys:
        if k in d and d[k] is not None and str(d[k]).strip() != "":
            return d[k], k
    return None, None


def _normalize_yes_no_token(token: str | None) -> str | None:
    if token is None:
        return None
    t = token.strip().lower()
    if t in _YES_TOKENS:
        return LABEL_YES
    if t in _NO_TOKENS:
        return LABEL_NO
    if t in ("1", "true"):
        return LABEL_YES
    return None


def extract_market_outcome_label(
    raw_market: Mapping[str, Any],
    *,
    label_version: str = _DEFAULT_LABEL_VERSION,
    market_ticker: str | None = None,
    extracted_at: datetime | None = None,
) -> dict[str, Any]:
    """
    Derive a conservative outcome label from API-shaped market data.

    Does **not** read ``title`` / ``subtitle`` / ``representative_title`` for resolution.
    Does **not** call HTTP.
    """
    d = _coerce_lookup_dict(raw_market)
    tkr = market_ticker or _lower(d.get("ticker")) or _lower(raw_market.get("market_ticker"))
    if not tkr:
        tkr = ""

    ext_at = extracted_at or datetime.now(timezone.utc)
    label_version_clean = (label_version or "").strip() or _DEFAULT_LABEL_VERSION

    ticker_display = tkr or str(d.get("ticker") or raw_market.get("market_ticker") or "")

    status_s = _lower(d.get("status"))
    result_raw, result_key = _first_present(d, ("result", "market_result", "outcome"))
    outcome_raw, outcome_key = _first_present(d, ("outcome",))
    settle_raw, settle_key = _first_present(d, ("settlement_value", "settlement_value_cents"))

    source_field: str | None = None
    source_value: str | None = None
    label_market_result = LABEL_UNKNOWN
    label_no_won: bool | None = None
    label_yes_won: bool | None = None
    label_is_resolved = False
    label_is_void = False
    label_confidence = "low"
    label_reason = ""

    # 1) Explicit void / cancel from status
    if status_s and status_s in _VOID_STATUS_TOKENS:
        label_market_result = LABEL_VOID
        label_is_void = True
        label_confidence = "high"
        source_field, source_value = "status", status_s
        label_reason = "status_indicates_void_or_cancel"

    # 2) Explicit void-like result string
    elif result_raw is not None and _lower(result_raw) in _VOID_RESULT_TOKENS:
        label_market_result = LABEL_VOID
        label_is_void = True
        label_confidence = "high"
        source_field, source_value = result_key or "result", str(result_raw)
        label_reason = "result_token_void_like"

    # 3) Clear yes/no from result field
    elif result_raw is not None:
        norm = _normalize_yes_no_token(str(result_raw))
        if norm == LABEL_YES:
            label_market_result = LABEL_YES
            label_yes_won = True
            label_no_won = False
            label_is_resolved = True
            label_confidence = "high"
            source_field, source_value = result_key or "result", str(result_raw)
            label_reason = "result_yes_won"
        elif norm == LABEL_NO:
            label_market_result = LABEL_NO
            label_yes_won = False
            label_no_won = True
            label_is_resolved = True
            label_confidence = "high"
            source_field, source_value = result_key or "result", str(result_raw)
            label_reason = "result_no_won"
        else:
            # Unrecognized result token
            label_reason = "result_not_recognized"

    # 4) outcome field as secondary (medium confidence)
    if label_market_result == LABEL_UNKNOWN and outcome_raw is not None:
        norm = _normalize_yes_no_token(str(outcome_raw))
        if norm == LABEL_YES:
            label_market_result = LABEL_YES
            label_yes_won = True
            label_no_won = False
            label_is_resolved = True
            label_confidence = "medium"
            source_field, source_value = outcome_key or "outcome", str(outcome_raw)
            label_reason = "outcome_yes_won"
        elif norm == LABEL_NO:
            label_market_result = LABEL_NO
            label_yes_won = False
            label_no_won = True
            label_is_resolved = True
            label_confidence = "medium"
            source_field, source_value = outcome_key or "outcome", str(outcome_raw)
            label_reason = "outcome_no_won"

    # 5) settlement_value — only when no yes/no from above; conservative
    if label_market_result == LABEL_UNKNOWN and settle_raw is not None and status_s not in _UNRESOLVED_STATUS_TOKENS:
        try:
            sv = int(float(settle_raw))
        except (TypeError, ValueError):
            sv = None
        if sv == 100 or sv == 1:
            label_market_result = LABEL_YES
            label_yes_won = True
            label_no_won = False
            label_is_resolved = True
            label_confidence = "low"
            source_field, source_value = settle_key or "settlement_value", str(settle_raw)
            label_reason = "settlement_value_implies_yes"
        elif sv == 0:
            label_market_result = LABEL_NO
            label_yes_won = False
            label_no_won = True
            label_is_resolved = True
            label_confidence = "low"
            source_field, source_value = settle_key or "settlement_value", str(settle_raw)
            label_reason = "settlement_value_implies_no"

    # 6) Unresolved market (still open) — we are confident it is *not* resolved yet
    if label_market_result == LABEL_UNKNOWN and status_s and status_s in _UNRESOLVED_STATUS_TOKENS:
        label_reason = label_reason or "market_not_resolved_by_status"
        label_confidence = "high"

    if not label_reason:
        label_reason = "insufficient_fields"

    now = datetime.now(timezone.utc)
    return {
        "market_ticker": ticker_display,
        "label_version": label_version_clean,
        "label_market_result": label_market_result,
        "label_no_won": label_no_won,
        "label_yes_won": label_yes_won,
        "label_is_resolved": label_is_resolved,
        "label_is_void": label_is_void,
        "label_confidence": label_confidence,
        "label_source_field": source_field,
        "label_source_value": source_value,
        "label_reason": label_reason,
        "extracted_at": ext_at,
        "raw_json": {k: v for k, v in d.items() if k in ("result", "status", "outcome", "market_result", "settlement_value", "settlement_ts")},
        "created_at": now,
    }


def extract_market_outcome_label_from_row(
    raw_market_row: Any,
    *,
    label_version: str = _DEFAULT_LABEL_VERSION,
    extracted_at: datetime | None = None,
) -> dict[str, Any]:
    """Build label dict from a ``RawMarket`` ORM instance or mapping with ``market_ticker`` + ``raw_json``."""
    if hasattr(raw_market_row, "market_ticker"):
        rm = raw_market_row
        merged: dict[str, Any] = dict(rm.raw_json) if isinstance(rm.raw_json, dict) else {}
        merged["ticker"] = rm.market_ticker
        if rm.result is not None:
            merged["result"] = rm.result
        if rm.status is not None:
            merged["status"] = rm.status
        if rm.settlement_time is not None:
            merged["settlement_ts"] = rm.settlement_time.isoformat() if hasattr(rm.settlement_time, "isoformat") else rm.settlement_time
        return extract_market_outcome_label(
            merged,
            label_version=label_version,
            market_ticker=rm.market_ticker,
            extracted_at=extracted_at,
        )
    return extract_market_outcome_label(
        raw_market_row,
        label_version=label_version,
        extracted_at=extracted_at,
    )


def build_market_outcome_labels_from_raw_markets(
    engine: Any,
    *,
    label_version: str = _DEFAULT_LABEL_VERSION,
    market_tickers: list[str] | None = None,
    statuses: list[str] | None = None,
    limit: int | None = None,
    delete_existing: bool = False,
) -> dict[str, Any]:
    """
    Read ``raw_markets``, extract deterministic labels, upsert ``research_market_labels``.

    Returns a JSON-serializable summary (caller should use ``default=str`` for datetimes if needed).
    """
    from kalshi_no_carry.db.repositories import (
        bulk_upsert_market_outcome_labels,
        delete_market_outcome_labels_for_version,
        list_raw_markets_for_labeling,
    )
    from kalshi_no_carry.db.schema import ResearchMarketLabel

    lv = (label_version or "").strip() or _DEFAULT_LABEL_VERSION
    warnings: list[str] = []
    summary: dict[str, Any] = {
        "success": True,
        "label_version": lv,
        "markets_seen": 0,
        "labels_written": 0,
        "resolved_yes": 0,
        "resolved_no": 0,
        "void": 0,
        "unknown": 0,
        "high_confidence": 0,
        "medium_confidence": 0,
        "low_confidence": 0,
        "warnings": warnings,
    }

    maker = sessionmaker(engine, expire_on_commit=False, future=True)
    with maker() as session:
        with session.begin():
            if delete_existing:
                n = delete_market_outcome_labels_for_version(session, label_version=lv)
                if n:
                    warnings.append(f"deleted_{n}_prior_labels_for_version")

            rows = list_raw_markets_for_labeling(
                session,
                market_tickers=market_tickers,
                statuses=statuses,
                limit=limit,
            )
            summary["markets_seen"] = len(rows)

            to_persist: list[ResearchMarketLabel] = []
            for rm in rows:
                payload = extract_market_outcome_label_from_row(rm, label_version=lv)
                if not str(payload.get("market_ticker") or "").strip():
                    continue
                to_persist.append(
                    ResearchMarketLabel(
                        market_ticker=payload["market_ticker"],
                        label_version=payload["label_version"],
                        label_market_result=payload["label_market_result"],
                        label_no_won=payload["label_no_won"],
                        label_yes_won=payload["label_yes_won"],
                        label_is_resolved=payload["label_is_resolved"],
                        label_is_void=payload["label_is_void"],
                        label_confidence=payload["label_confidence"],
                        label_source_field=payload["label_source_field"],
                        label_source_value=payload["label_source_value"],
                        label_reason=payload["label_reason"],
                        extracted_at=payload["extracted_at"],
                        raw_json=payload.get("raw_json") if isinstance(payload.get("raw_json"), dict) else None,
                        created_at=payload["created_at"],
                    )
                )

            summary["labels_written"] = bulk_upsert_market_outcome_labels(session, to_persist)

            for p in to_persist:
                if p.label_is_void or p.label_market_result == LABEL_VOID:
                    summary["void"] += 1
                elif p.label_market_result == LABEL_YES:
                    summary["resolved_yes"] += 1
                elif p.label_market_result == LABEL_NO:
                    summary["resolved_no"] += 1
                else:
                    summary["unknown"] += 1

                conf = (p.label_confidence or "").lower()
                if conf == "high":
                    summary["high_confidence"] += 1
                elif conf == "medium":
                    summary["medium_confidence"] += 1
                else:
                    summary["low_confidence"] += 1

    return summary
