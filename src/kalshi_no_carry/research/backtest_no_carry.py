"""Read-only NO-carry baseline backtest: selection, scoring, summaries (v0.7)."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import median
from typing import Any

from kalshi_no_carry.research.backtest_config import (
    STRATEGY_NO_CARRY_REQUIRED_PROB_PLACEHOLDER_V0,
    BacktestConfig,
)


@dataclass(frozen=True)
class CandidateSelection:
    selected: tuple[dict[str, Any], ...]
    rejection_counts: dict[str, int]


def compute_backtest_run_id(config: BacktestConfig) -> str:
    """Deterministic run id: UUIDv5 over a canonical JSON payload of the config."""
    payload = json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"kalshi-no-carry|backtest|{payload}"))


def resolve_label_no_won_for_scoring(row: Mapping[str, Any]) -> bool | None:
    """
    Interpret whether NO won for PnL scoring, using explicit label columns when present.

    Never inspects market title text.
    """
    if row.get("label_is_void") is True:
        return None
    lr = row.get("label_market_result")
    if lr is not None and str(lr).strip().lower() == "void":
        return None
    ln = row.get("label_no_won")
    if ln is True:
        return True
    if ln is False:
        return False
    return parse_label_no_won(str(lr).strip() if lr is not None else None)


def parse_label_no_won(label_market_result: str | None) -> bool | None:
    """
    Interpret stored ``label_market_result`` (Kalshi market ``result``) for a **NO** position.

    Returns ``True`` if NO won, ``False`` if YES won, ``None`` if unknown/void/unset.
    """
    if label_market_result is None:
        return None
    s = str(label_market_result).strip().lower()
    if not s:
        return None
    if s in ("no", "n"):
        return True
    if s in ("yes", "y"):
        return False
    if s in ("void", "scnd", "canceled", "cancelled", "null", "none", "unknown"):
        return None
    return None


def _fee_cents_for_row(row: Mapping[str, Any], config: BacktestConfig) -> int:
    if config.fee_model == "stored_estimated_taker_fee_cents":
        v = row.get("estimated_taker_fee_cents")
        if v is None:
            return 0
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 0
    return 0


def _scale_pnl_cents(per_contract_cents: int, stake_cents: int) -> int:
    """Scale per-contract PnL: ``(per_contract * stake_cents) // 100`` (deterministic)."""
    return int(per_contract_cents) * int(stake_cents) // 100


def score_no_trade(candidate_row: Mapping[str, Any], config: BacktestConfig) -> dict[str, Any]:
    """
    Score hypothetical buy-NO-at-ask using **labels only** (no inference from titles).

    Per-contract economics at one contract (100¢ payoff): NO wins → ``100 - no_ask``;
    NO loses → ``-no_ask``. Fees subtract from gross using ``fee_model``.
    """
    snapshot_id = candidate_row.get("snapshot_id")
    market_ticker = candidate_row.get("market_ticker")
    cluster_id = candidate_row.get("cluster_id")
    split_name = candidate_row.get("split_name")
    no_ask = candidate_row.get("no_ask_cents")
    label_raw = candidate_row.get("label_market_result")

    base: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "market_ticker": market_ticker,
        "cluster_id": cluster_id,
        "split_name": split_name,
        "no_ask_cents": no_ask,
        "fee_cents": None,
        "label_market_result": label_raw,
        "label_no_won": None,
        "gross_pnl_cents": None,
        "net_pnl_cents": None,
        "scored": False,
        "unscored_reason": None,
    }

    if no_ask is None:
        base["unscored_reason"] = "missing_no_ask"
        return base

    try:
        ask_i = int(no_ask)
    except (TypeError, ValueError):
        base["unscored_reason"] = "missing_no_ask"
        return base

    won = resolve_label_no_won_for_scoring(candidate_row)
    if won is None:
        base["unscored_reason"] = "missing_or_ambiguous_label"
        return base

    fee_per = _fee_cents_for_row(candidate_row, config)
    base["label_no_won"] = won

    if won:
        gross = 100 - ask_i
    else:
        gross = -ask_i

    gross_s = _scale_pnl_cents(gross, config.stake_cents)
    fee_s = _scale_pnl_cents(fee_per, config.stake_cents)
    net_s = gross_s - fee_s

    base["fee_cents"] = fee_s
    base["gross_pnl_cents"] = gross_s
    base["net_pnl_cents"] = net_s
    base["scored"] = True
    base["unscored_reason"] = None
    return base


def select_no_carry_candidates(
    feature_rows: Sequence[Mapping[str, Any]],
    config: BacktestConfig,
) -> CandidateSelection:
    """
    Filter + dedupe feature rows into hypothetical **entries** (read-only).

    Placeholder strategy returns **no** selected trades (summaries use raw rows separately).
    """
    if config.strategy_name == STRATEGY_NO_CARRY_REQUIRED_PROB_PLACEHOLDER_V0:
        return CandidateSelection(selected=(), rejection_counts={})

    allowed = {s.strip() for s in config.include_splits if s and str(s).strip()}
    if not config.include_test:
        allowed.discard("test")

    rejections: Counter[str] = Counter()
    selected: list[dict[str, Any]] = []
    seen_market: set[str] = set()
    seen_cluster: set[str] = set()

    for row in feature_rows:
        r = dict(row)
        sn = str(r.get("split_name") or "")
        if sn not in allowed:
            rejections["split_not_included"] += 1
            continue

        if config.require_complete_prices and not r.get("has_complete_executable_prices"):
            rejections["incomplete_prices"] += 1
            continue

        no_ask = r.get("no_ask_cents")
        if no_ask is None:
            rejections["missing_no_ask"] += 1
            continue
        try:
            ask_i = int(no_ask)
        except (TypeError, ValueError):
            rejections["missing_no_ask"] += 1
            continue

        if ask_i < int(config.min_no_ask_cents):
            rejections["no_ask_too_low"] += 1
            continue
        if ask_i > int(config.max_no_ask_cents):
            rejections["no_ask_too_high"] += 1
            continue

        stc = r.get("seconds_to_close")
        if config.min_seconds_to_close is not None or config.max_seconds_to_close is not None:
            if stc is None:
                rejections["missing_seconds_to_close"] += 1
                continue
            try:
                sec = float(stc)
            except (TypeError, ValueError):
                rejections["missing_seconds_to_close"] += 1
                continue
            if config.min_seconds_to_close is not None and sec < float(config.min_seconds_to_close):
                rejections["too_early"] += 1
                continue
            if config.max_seconds_to_close is not None and sec > float(config.max_seconds_to_close):
                rejections["too_late"] += 1
                continue

        mt = str(r.get("market_ticker") or "")
        cid = str(r.get("cluster_id") or "")

        if config.one_trade_per_market and mt in seen_market:
            rejections["duplicate_market"] += 1
            continue
        if config.one_trade_per_cluster and cid in seen_cluster:
            rejections["duplicate_cluster"] += 1
            continue

        selected.append(r)
        if config.one_trade_per_market and mt:
            seen_market.add(mt)
        if config.one_trade_per_cluster and cid:
            seen_cluster.add(cid)

    return CandidateSelection(selected=tuple(selected), rejection_counts=dict(rejections))


def _no_ask_bucket(no_ask: int | None) -> str:
    if no_ask is None:
        return "unknown"
    if no_ask <= 50:
        return "0-50"
    if no_ask <= 70:
        return "51-70"
    if no_ask <= 85:
        return "71-85"
    if no_ask <= 95:
        return "86-95"
    return "96-100"


def _ttc_bucket(seconds_to_close: Any) -> str:
    if seconds_to_close is None:
        return "unknown"
    try:
        s = float(seconds_to_close)
    except (TypeError, ValueError):
        return "unknown"
    if s < 0:
        return "past_close"
    if s < 3600:
        return "<1h"
    if s < 86400:
        return "1h-24h"
    if s < 7 * 86400:
        return "1d-7d"
    return ">7d"


def summarize_required_probability_buckets(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Placeholder strategy: distribution of stored breakeven NO probabilities (no trades)."""
    buckets_before: Counter[str] = Counter()
    for row in rows:
        p = row.get("required_no_probability_before_fees")
        if p is None:
            buckets_before["missing"] += 1
            continue
        try:
            x = float(p)
        except (TypeError, ValueError):
            buckets_before["missing"] += 1
            continue
        if x < 0.25:
            buckets_before["lt_0.25"] += 1
        elif x < 0.5:
            buckets_before["0.25_0.50"] += 1
        elif x < 0.75:
            buckets_before["0.50_0.75"] += 1
        else:
            buckets_before["ge_0.75"] += 1
    return {"required_no_probability_before_fees_buckets": dict(buckets_before)}


def _max_drawdown_cents(net_pnls: Sequence[int]) -> int:
    """Max drawdown (positive number = worst peak-to-trough drop) in deterministic order."""
    peak = 0
    cum = 0
    max_dd = 0
    for p in net_pnls:
        cum += int(p)
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    return int(max_dd)


def build_backtest_summary(
    *,
    config: BacktestConfig,
    feature_rows: Sequence[Mapping[str, Any]],
    selection: CandidateSelection,
    trade_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate metrics; ``test_included`` is flagged loudly when True."""
    warnings: list[str] = list()
    test_included = bool(config.include_test)
    if test_included:
        warnings.append("TEST_SPLIT_INCLUDED: sealed test rows were included in this run.")

    rows_seen = len(feature_rows)
    candidates_selected = len(selection.selected)

    scored_trades = sum(1 for t in trade_results if t.get("scored"))
    unscored_trades = len(trade_results) - scored_trades

    scored_nets = [int(t["net_pnl_cents"]) for t in trade_results if t.get("scored") and t.get("net_pnl_cents") is not None]
    wins = [t for t in trade_results if t.get("scored") and t.get("label_no_won") is True]
    losses = [t for t in trade_results if t.get("scored") and t.get("label_no_won") is False]

    win_rate: float | None = None
    if scored_trades:
        win_rate = float(len(wins)) / float(scored_trades)

    gross_total = sum(int(t["gross_pnl_cents"]) for t in trade_results if t.get("scored") and t.get("gross_pnl_cents") is not None)
    net_total = sum(int(t["net_pnl_cents"]) for t in trade_results if t.get("scored") and t.get("net_pnl_cents") is not None)
    fees_total = sum(int(t["fee_cents"] or 0) for t in trade_results if t.get("scored"))

    avg_net: float | None = None
    med_net: float | None = None
    if scored_trades:
        avg_net = float(net_total) / float(scored_trades)
        med_net = float(median(scored_nets)) if scored_nets else None

    costs = []
    for t in trade_results:
        if not t.get("scored"):
            continue
        ask = t.get("no_ask_cents")
        if ask is None:
            continue
        try:
            c = int(ask) * int(config.stake_cents) // 100
        except (TypeError, ValueError):
            continue
        costs.append(c)
    total_cost = sum(costs)
    roi_on_cost: float | None = None
    if total_cost > 0:
        roi_on_cost = float(net_total) / float(total_cost)

    worst = min(scored_nets) if scored_nets else None
    best = max(scored_nets) if scored_nets else None
    max_dd = _max_drawdown_cents(scored_nets) if scored_nets else 0

    trades_by_split: dict[str, int] = {}
    pnl_by_split: dict[str, int] = {}
    for t in trade_results:
        sn = str(t.get("split_name") or "unknown")
        trades_by_split[sn] = trades_by_split.get(sn, 0) + 1
        if t.get("scored") and t.get("net_pnl_cents") is not None:
            pnl_by_split[sn] = pnl_by_split.get(sn, 0) + int(t["net_pnl_cents"])

    by_ask: dict[str, dict[str, int]] = {}
    by_ttc: dict[str, dict[str, int]] = {}
    by_cat: dict[str, dict[str, int]] = {}
    for t in trade_results:
        row_ask = t.get("no_ask_cents")
        try:
            ai = int(row_ask) if row_ask is not None else None
        except (TypeError, ValueError):
            ai = None
        ak = _no_ask_bucket(ai)
        by_ask.setdefault(ak, {"count": 0, "net_pnl_cents": 0})
        by_ask[ak]["count"] += 1
        if t.get("scored") and t.get("net_pnl_cents") is not None:
            by_ask[ak]["net_pnl_cents"] += int(t["net_pnl_cents"])

    # bucket trades using parallel walk: trade_results may omit category — merge from selection maps
    snap_to_row: dict[Any, dict[str, Any]] = {}
    for row in selection.selected:
        sid = row.get("snapshot_id")
        if sid is not None:
            snap_to_row[sid] = dict(row)

    for t in trade_results:
        sid = t.get("snapshot_id")
        src = snap_to_row.get(sid, {})
        ttc_k = _ttc_bucket(src.get("seconds_to_close"))
        by_ttc.setdefault(ttc_k, {"count": 0, "net_pnl_cents": 0})
        by_ttc[ttc_k]["count"] += 1
        if t.get("scored") and t.get("net_pnl_cents") is not None:
            by_ttc[ttc_k]["net_pnl_cents"] += int(t["net_pnl_cents"])

        cat = src.get("category") or "unknown"
        ck = str(cat)
        by_cat.setdefault(ck, {"count": 0, "net_pnl_cents": 0})
        by_cat[ck]["count"] += 1
        if t.get("scored") and t.get("net_pnl_cents") is not None:
            by_cat[ck]["net_pnl_cents"] += int(t["net_pnl_cents"])

    cluster_losses: list[dict[str, Any]] = []
    if scored_trades:
        by_cl: dict[str, list[int]] = {}
        for t in trade_results:
            if not t.get("scored") or t.get("net_pnl_cents") is None:
                continue
            cid = str(t.get("cluster_id") or "")
            by_cl.setdefault(cid, []).append(int(t["net_pnl_cents"]))
        for cid, vals in by_cl.items():
            s = sum(vals)
            cluster_losses.append({"cluster_id": cid, "net_pnl_cents": s, "trades": len(vals)})
        cluster_losses.sort(key=lambda x: (x["net_pnl_cents"], x["cluster_id"]))

    labels_present = any(r.get("label_market_result") not in (None, "") for r in feature_rows)
    if candidates_selected > 0 and not labels_present:
        warnings.append("No label_market_result on loaded rows: scored_trades will be 0 (PnL not fabricated).")

    if config.strategy_name == STRATEGY_NO_CARRY_REQUIRED_PROB_PLACEHOLDER_V0:
        ph = summarize_required_probability_buckets(feature_rows)
    else:
        ph = {}

    return {
        "backtest_version": config.backtest_version,
        "strategy_name": config.strategy_name,
        "split_version": config.split_version,
        "feature_version": config.feature_version,
        "test_included": test_included,
        "rows_seen": rows_seen,
        "candidates_selected": candidates_selected,
        "scored_trades": scored_trades,
        "unscored_trades": unscored_trades,
        "win_rate": win_rate,
        "gross_pnl_cents": gross_total,
        "net_pnl_cents": net_total,
        "avg_net_pnl_cents": avg_net,
        "median_net_pnl_cents": med_net,
        "total_fees_cents": fees_total,
        "roi_on_cost": roi_on_cost,
        "worst_trade_cents": worst,
        "best_trade_cents": best,
        "max_drawdown_cents": max_dd,
        "trades_by_split": trades_by_split,
        "pnl_by_split": pnl_by_split,
        "rejection_counts": dict(selection.rejection_counts),
        "by_no_ask_bucket": by_ask,
        "by_time_to_close_bucket": by_ttc,
        "by_category": by_cat,
        "cluster_net_pnl_sorted": cluster_losses[:20],
        "placeholder": ph,
        "warnings": warnings,
        "success": True,
    }


def run_no_carry_backtest_core(
    feature_rows: Sequence[Mapping[str, Any]],
    config: BacktestConfig,
) -> tuple[CandidateSelection, list[dict[str, Any]], dict[str, Any]]:
    """
    Load **pre-sorted** feature rows, select candidates, score, build summary (pure + deterministic).
    """
    selection = select_no_carry_candidates(feature_rows, config)
    trade_results: list[dict[str, Any]] = []
    for row in selection.selected:
        trade_results.append(score_no_trade(row, config))
    summary = build_backtest_summary(
        config=config,
        feature_rows=feature_rows,
        selection=selection,
        trade_results=trade_results,
    )
    return selection, trade_results, summary


def run_no_carry_backtest_persisted(
    engine: Any,
    config: BacktestConfig,
    *,
    dry_run: bool = False,
    overwrite_existing_run: bool = True,
    market_tickers: list[str] | None = None,
) -> dict[str, Any]:
    """
    Load feature rows from ``engine``, run ``run_no_carry_backtest_core``, optionally persist
    ``backtest_runs`` / ``backtest_trades`` (shared by ``scripts/run_backtest.py`` and v0.9 pipeline).

    Persisted runs use a **deterministic** ``run_id`` (see ``compute_backtest_run_id``). By default,
    if that row already exists, it is **replaced** in one transaction (prior trades removed first)
    so reruns with the same config do not raise duplicate-key errors.
    """
    from datetime import datetime, timezone

    from sqlalchemy.orm import sessionmaker

    from kalshi_no_carry.db.repositories import (
        delete_backtest_run,
        insert_backtest_run,
        insert_backtest_trades,
        list_feature_rows_for_backtest,
    )
    from kalshi_no_carry.db.schema import BacktestRun

    run_id = compute_backtest_run_id(config)
    maker = sessionmaker(engine, expire_on_commit=False, future=True)
    rows_written = 0
    prior_run_deleted = False
    prior_trades_deleted = 0
    with maker() as session:
        feature_rows = list_feature_rows_for_backtest(
            session,
            split_version=config.split_version,
            feature_version=config.feature_version,
            include_splits=config.include_splits,
            include_test=config.include_test,
            limit=config.max_rows,
            market_tickers=market_tickers,
        )

    selection, trade_results, summary = run_no_carry_backtest_core(feature_rows, config)

    if not dry_run:
        # Separate transactional scope: the read path leaves an implicit transaction open on
        # the Session, and nesting ``session.begin()`` triggers InvalidRequestError on SQLAlchemy 2.
        with maker.begin() as session:
            if overwrite_existing_run:
                prior_run_deleted, prior_trades_deleted = delete_backtest_run(session, run_id)
            cfg_dict = config.model_dump(mode="json")
            run_row = BacktestRun(
                run_id=run_id,
                backtest_version=config.backtest_version,
                strategy_name=config.strategy_name,
                split_version=config.split_version,
                feature_version=config.feature_version,
                config_json=cfg_dict,
                summary_json=summary,
                created_at=datetime.now(timezone.utc),
                test_included=bool(config.include_test),
            )
            insert_backtest_run(session, run_row)
            rows_written = insert_backtest_trades(session, run_id, trade_results)

    overwritten_existing_run = bool(
        (not dry_run)
        and overwrite_existing_run
        and (prior_run_deleted or prior_trades_deleted > 0)
    )
    extra_warnings: list[str] = []
    if overwritten_existing_run:
        extra_warnings.append(
            "BACKTEST_RUN_OVERWRITE: replaced existing persisted rows for deterministic "
            f"run_id={run_id} (prior_run_deleted={prior_run_deleted}, "
            f"prior_trades_deleted={prior_trades_deleted})."
        )

    return {
        "success": True,
        "stage_name": "backtest",
        "run_id": run_id,
        "backtest_version": config.backtest_version,
        "strategy_name": config.strategy_name,
        "split_version": config.split_version,
        "feature_version": config.feature_version,
        "include_test": bool(config.include_test),
        "test_included": bool(summary.get("test_included")),
        "rows_seen": summary.get("rows_seen"),
        "candidates_selected": summary.get("candidates_selected"),
        "scored_trades": summary.get("scored_trades"),
        "unscored_trades": summary.get("unscored_trades"),
        "net_pnl_cents": summary.get("net_pnl_cents"),
        "dry_run": bool(dry_run),
        "persisted": not bool(dry_run),
        "overwritten_existing_run": overwritten_existing_run,
        "prior_run_deleted": bool(prior_run_deleted),
        "prior_trades_deleted": int(prior_trades_deleted),
        "trades_persisted": 0 if dry_run else rows_written,
        "warnings": list(summary.get("warnings", [])) + extra_warnings,
        "summary": summary,
    }
