"""Read-only diagnostics for stored orderbook JSON and executable price extraction (v0.12)."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.db.schema import RawOrderbookSnapshot, ResearchFeatureRow
from kalshi_no_carry.kalshi_client import derive_executable_prices_from_orderbook


def orderbook_json_coverage_flags(orderbook_json: Mapping[str, Any]) -> dict[str, Any]:
    """
    Single-orderbook coverage flags for collector summaries (read-only; no HTTP).

    Executable NO ask is counted only when derived ``best_no_ask_cents`` is present
    (typically requires a YES bid side for Kalshi bid-implied asks).
    """
    raw = dict(orderbook_json)
    inner = _orderbook_inner(raw)
    yes_nonempty = False
    no_nonempty = False
    if inner is not None:
        yl, nl = _level_lists(inner)
        yes_nonempty = _nonempty_level_rows(yl) > 0
        no_nonempty = _nonempty_level_rows(nl) > 0

    ex: dict[str, Any] = {}
    parse_ok = True
    try:
        ex = derive_executable_prices_from_orderbook(raw)
    except Exception:
        parse_ok = False

    byb = ex.get("best_yes_bid_cents")
    bnb = ex.get("best_no_bid_cents")
    no_ask = ex.get("best_no_ask_cents")
    yes_ask = ex.get("best_yes_ask_cents")

    books_with_yes_bids = bool(yes_nonempty or (byb is not None))
    books_with_no_bids = bool(no_nonempty or (bnb is not None))
    books_empty_both_sides = bool(inner is None or (not books_with_yes_bids and not books_with_no_bids))
    books_with_executable_no_ask = bool(no_ask is not None)
    books_with_executable_yes_ask = bool(yes_ask is not None)

    return {
        "parse_ok": parse_ok,
        "books_with_yes_bids": books_with_yes_bids,
        "books_with_no_bids": books_with_no_bids,
        "books_empty_both_sides": books_empty_both_sides,
        "books_with_executable_no_ask": books_with_executable_no_ask,
        "books_with_executable_yes_ask": books_with_executable_yes_ask,
    }


def _fingerprint_keys(d: dict[str, Any] | None) -> tuple[str, ...]:
    if not d:
        return ()
    return tuple(sorted(d.keys()))


def _orderbook_inner(raw: dict[str, Any]) -> dict[str, Any] | None:
    fp = raw.get("orderbook_fp")
    if isinstance(fp, dict):
        return fp
    if "yes_dollars" in raw or "no_dollars" in raw:
        return raw
    return None


def _level_lists(inner: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    y = inner.get("yes_dollars")
    n = inner.get("no_dollars")
    if not isinstance(y, list):
        y = []
    if not isinstance(n, list):
        n = []
    return y, n


def _nonempty_level_rows(levels: list[Any]) -> int:
    n = 0
    for lv in levels:
        if isinstance(lv, (list, tuple)) and len(lv) >= 2:
            n += 1
    return n


def audit_orderbook_price_extraction(
    engine: Engine,
    *,
    limit: int | None = None,
    feature_version: str | None = None,
    split_version: str | None = None,
    join_feature_row_limit: int = 2000,
    max_shape_samples: int = 5,
) -> dict[str, Any]:
    """
    Inspect ``raw_orderbook_snapshots`` (and optional join to ``research_feature_rows``).

    Read-only: no mutations. Does not call Kalshi.
    """
    maker = sessionmaker(engine, expire_on_commit=False, future=True)
    top_key_counts: Counter[str] = Counter()
    nested_key_counts: Counter[str] = Counter()
    shape_samples: list[dict[str, Any]] = []

    counts: dict[str, int] = {
        "snapshots_seen": 0,
        "snapshots_with_raw_json": 0,
        "snapshots_missing_raw_json": 0,
        "snapshots_with_yes_book": 0,
        "snapshots_with_no_book": 0,
        "snapshots_with_nonempty_yes_book": 0,
        "snapshots_with_nonempty_no_book": 0,
        "snapshots_with_any_bid": 0,
        "snapshots_with_executable_no_ask": 0,
        "snapshots_with_executable_yes_ask": 0,
        "snapshots_empty_both_sides": 0,
        "snapshots_unrecognized_shape": 0,
        "rows_best_yes_bid_present": 0,
        "rows_derived_no_ask_present": 0,
        "rows_best_no_bid_present": 0,
        "rows_derived_yes_ask_present": 0,
        "feature_join_snapshots": 0,
        "feature_raw_executable_no_ask_feature_missing_no_ask": 0,
        "feature_raw_empty_book_feature_missing_no_ask": 0,
    }

    with maker() as session:
        stmt = select(RawOrderbookSnapshot).order_by(RawOrderbookSnapshot.id.desc())
        if limit is not None:
            stmt = stmt.limit(int(limit))
        rows = list(session.scalars(stmt).all())

    snap_by_id: dict[int, RawOrderbookSnapshot] = {int(r.id): r for r in rows}

    for snap in rows:
        counts["snapshots_seen"] += 1
        raw = snap.raw_json
        if not isinstance(raw, dict):
            counts["snapshots_missing_raw_json"] += 1
            continue

        counts["snapshots_with_raw_json"] += 1
        for k in raw.keys():
            top_key_counts[f"top:{k}"] += 1

        inner = _orderbook_inner(raw)
        if inner is None:
            counts["snapshots_unrecognized_shape"] += 1
            if len(shape_samples) < max_shape_samples:
                shape_samples.append(
                    {
                        "snapshot_id": snap.id,
                        "market_ticker": snap.market_ticker,
                        "top_keys": list(_fingerprint_keys(raw)),
                        "note": "no orderbook_fp and no yes_dollars/no_dollars at top level",
                    }
                )
            continue

        for k in inner.keys():
            nested_key_counts[f"nested:{k}"] += 1

        yes_levels, no_levels = _level_lists(inner)
        if yes_levels:
            counts["snapshots_with_yes_book"] += 1
        if no_levels:
            counts["snapshots_with_no_book"] += 1
        ny = _nonempty_level_rows(yes_levels)
        nn = _nonempty_level_rows(no_levels)
        if ny > 0:
            counts["snapshots_with_nonempty_yes_book"] += 1
        if nn > 0:
            counts["snapshots_with_nonempty_no_book"] += 1

        if ny == 0 and nn == 0:
            counts["snapshots_empty_both_sides"] += 1

        ex: dict[str, Any]
        try:
            ex = derive_executable_prices_from_orderbook(raw)
        except Exception as exc:
            counts["snapshots_unrecognized_shape"] += 1
            if len(shape_samples) < max_shape_samples:
                shape_samples.append(
                    {
                        "snapshot_id": snap.id,
                        "market_ticker": snap.market_ticker,
                        "top_keys": list(_fingerprint_keys(raw)),
                        "nested_keys": list(_fingerprint_keys(inner)),
                        "parse_error": f"{type(exc).__name__}",
                    }
                )
            continue

        byb = ex.get("best_yes_bid_cents")
        bnb = ex.get("best_no_bid_cents")
        no_ask = ex.get("best_no_ask_cents")
        yes_ask = ex.get("best_yes_ask_cents")

        if byb is not None:
            counts["rows_best_yes_bid_present"] += 1
        if no_ask is not None:
            counts["rows_derived_no_ask_present"] += 1
        if bnb is not None:
            counts["rows_best_no_bid_present"] += 1
        if yes_ask is not None:
            counts["rows_derived_yes_ask_present"] += 1

        if byb is not None or bnb is not None:
            counts["snapshots_with_any_bid"] += 1
        if no_ask is not None:
            counts["snapshots_with_executable_no_ask"] += 1
        if yes_ask is not None:
            counts["snapshots_with_executable_yes_ask"] += 1

    # Feature-row join diagnostic (same snapshot batch)
    if snap_by_id and join_feature_row_limit > 0:
        ids = list(snap_by_id.keys())[: int(join_feature_row_limit)]
        feats: list[ResearchFeatureRow] = []
        if ids:
            with maker() as session:
                stmt = select(ResearchFeatureRow).where(ResearchFeatureRow.snapshot_id.in_(ids))
                if feature_version:
                    stmt = stmt.where(ResearchFeatureRow.feature_version == str(feature_version).strip())
                if split_version:
                    stmt = stmt.where(ResearchFeatureRow.split_version == str(split_version).strip())
                feats = list(session.scalars(stmt).all())

        for fr in feats:
            sid = int(fr.snapshot_id)
            ob_row = snap_by_id.get(sid)
            if ob_row is None:
                continue
            counts["feature_join_snapshots"] += 1
            raw = ob_row.raw_json
            if not isinstance(raw, dict):
                continue
            try:
                ex = derive_executable_prices_from_orderbook(raw)
            except Exception:
                continue
            raw_no_ask = ex.get("best_no_ask_cents")
            inner = _orderbook_inner(raw)
            yes_levels: list[Any] = []
            no_levels: list[Any] = []
            if inner is not None:
                yes_levels, no_levels = _level_lists(inner)
            empty_book = _nonempty_level_rows(yes_levels) == 0 and _nonempty_level_rows(no_levels) == 0

            if raw_no_ask is not None and fr.no_ask_cents is None:
                counts["feature_raw_executable_no_ask_feature_missing_no_ask"] += 1
            if raw_no_ask is None and fr.no_ask_cents is None and empty_book:
                counts["feature_raw_empty_book_feature_missing_no_ask"] += 1

    out: dict[str, Any] = {
        "success": True,
        "audit_version": "v0.12_orderbook_price_extraction",
        "counts": counts,
        "top_level_key_histogram": dict(top_key_counts.most_common(30)),
        "nested_orderbook_key_histogram": dict(nested_key_counts.most_common(30)),
        "shape_samples": shape_samples,
    }
    return out


__all__ = ["audit_orderbook_price_extraction", "orderbook_json_coverage_flags"]
