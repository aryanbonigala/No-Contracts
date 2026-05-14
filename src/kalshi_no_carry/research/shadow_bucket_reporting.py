"""Reporting for NO bucket shadow experiment (read-only aggregates over stored rows)."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_no_carry.db.schema import ShadowBucketEntry, ShadowBucketMarketObservation
from kalshi_no_carry.research.score_shadow_buckets import (
    DATA_ERROR,
    LOST_RESOLVED_YES,
    SPECIAL_OR_AMBIGUOUS_RESOLUTION,
    UNRESOLVED,
    WIN_AFTER_FEES,
    WON_BUT_BAD_FILL_ERASED_PROFIT,
    WON_BUT_FEES_ERASED_PROFIT,
)

DEFAULT_BUCKET_KEYS = ("60", "70", "80", "85", "90", "95")

INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
TOO_MANY_UNRESOLVED = "TOO_MANY_UNRESOLVED"
PROMISING_AFTER_FEES = "PROMISING_AFTER_FEES"
PROFITABLE_BEFORE_FEES_ONLY = "PROFITABLE_BEFORE_FEES_ONLY"
NEGATIVE_AFTER_FEES = "NEGATIVE_AFTER_FEES"
MIXED_OR_FLAT = "MIXED_OR_FLAT"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _max_drawdown_cents(series: list[int]) -> int:
    peak = 0
    cur = 0
    max_dd = 0
    for x in series:
        cur += x
        peak = max(peak, cur)
        max_dd = max(max_dd, peak - cur)
    return int(max_dd)


def _longest_loss_streak(series: list[int]) -> int:
    best = 0
    run = 0
    for x in series:
        if x < 0:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def _bucket_seconds_label(sec: float | None) -> str:
    if sec is None:
        return "unknown"
    if sec < 300:
        return "<5m"
    if sec < 900:
        return "5m-15m"
    if sec < 3600:
        return "15m-1h"
    if sec < 6 * 3600:
        return "1h-6h"
    if sec < 24 * 3600:
        return "6h-24h"
    if sec < 7 * 24 * 3600:
        return "1d+"
    return "1d+"


def _spread_bucket(spread: float | None) -> str:
    if spread is None:
        return "unknown"
    if spread <= 1:
        return "0-1¢"
    if spread <= 3:
        return "1-3¢"
    if spread <= 5:
        return "3-5¢"
    if spread <= 10:
        return "5-10¢"
    return "10¢+"


def _slippage_bucket(slip: float | None) -> str:
    if slip is None:
        return "unknown"
    if slip <= 0:
        return "<=0¢"
    if slip <= 0.5:
        return "0-0.5¢"
    if slip <= 1:
        return "0.5-1¢"
    if slip <= 2:
        return "1-2¢"
    return "2¢+"


def _diagnose_bucket(
    *,
    scored_entries: int,
    unscored_entries: int,
    net_pnl_cents: int,
    gross_pnl_cents: int,
    win_rate: float | None,
    edge_over_be: float | None,
    min_scored_sample: int,
) -> str:
    if scored_entries < min_scored_sample:
        return INSUFFICIENT_SAMPLE
    if unscored_entries > scored_entries:
        return TOO_MANY_UNRESOLVED
    if net_pnl_cents > 0 and edge_over_be is not None and edge_over_be > 0:
        return PROMISING_AFTER_FEES
    if gross_pnl_cents > 0 and net_pnl_cents <= 0:
        return PROFITABLE_BEFORE_FEES_ONLY
    if net_pnl_cents < 0:
        return NEGATIVE_AFTER_FEES
    return MIXED_OR_FLAT


def build_shadow_bucket_report(
    session: Session,
    *,
    shadow_version: str,
    experiment_name: str | None = None,
    report_name: str = "shadow_bucket_report",
    output_dir: Path | None = None,
    include_unscored: bool = True,
    min_scored_sample: int = 30,
) -> dict[str, Any]:
    stmt = select(ShadowBucketEntry).where(ShadowBucketEntry.shadow_version == shadow_version)
    if experiment_name:
        stmt = stmt.where(ShadowBucketEntry.experiment_name == experiment_name)
    rows = list(session.scalars(stmt).all())

    obs_stmt = select(ShadowBucketMarketObservation).where(
        ShadowBucketMarketObservation.shadow_version == shadow_version
    )
    if experiment_name:
        obs_stmt = obs_stmt.where(ShadowBucketMarketObservation.experiment_name == experiment_name)
    obs_rows = list(session.scalars(obs_stmt).all())

    base_dir = output_dir or Path("reports") / report_name
    base_dir.mkdir(parents=True, exist_ok=True)
    json_path = base_dir / "shadow_bucket_report.json"
    md_path = base_dir / "shadow_bucket_report.md"

    overall = {
        "total_unique_markets_seen": len(obs_rows),
        "total_entries": len(rows),
        "total_scored_entries": sum(1 for r in rows if r.scored),
        "total_unscored_entries": sum(1 for r in rows if not r.scored),
        "total_wins": sum(1 for r in rows if r.scored and int(r.net_pnl_cents or 0) > 0),
        "total_losses": sum(1 for r in rows if r.scored and int(r.net_pnl_cents or 0) < 0),
        "total_gross_pnl_cents": sum(int(r.gross_pnl_cents or 0) for r in rows if r.scored),
        "total_fees_cents": sum(int(r.fee_cents or 0) for r in rows if r.scored),
        "total_net_pnl_cents": sum(int(r.net_pnl_cents or 0) for r in rows if r.scored),
        "best_bucket_by_net_pnl": None,
        "best_bucket_by_avg_net_per_trade": None,
        "worst_bucket_by_net_pnl": None,
    }

    buckets: dict[str, Any] = {}
    scored_sorted_by_bucket: dict[str, list[ShadowBucketEntry]] = defaultdict(list)
    for r in rows:
        if r.scored:
            scored_sorted_by_bucket[str(r.bucket_price_cents)].append(r)
    for bk in scored_sorted_by_bucket:
        scored_sorted_by_bucket[bk].sort(key=lambda x: (x.observed_at, x.id))

    default_buckets = list(DEFAULT_BUCKET_KEYS)

    for bk in default_buckets:
        br = [x for x in rows if str(x.bucket_price_cents) == bk]
        scored = [x for x in br if x.scored]
        unscored = [x for x in br if not x.scored]
        wins = sum(1 for x in scored if int(x.net_pnl_cents or 0) > 0)
        losses = sum(1 for x in scored if int(x.net_pnl_cents or 0) < 0)
        sum_cost_and_fee = sum(int(x.gross_cost_cents or 0) + int(x.fee_cents or 0) for x in scored)
        max_payout_total = sum(int(x.contracts_filled or 0) * 100 for x in scored)
        gross_pnl = sum(int(x.gross_pnl_cents or 0) for x in scored)
        fees_paid = sum(int(x.fee_cents or 0) for x in scored)
        net_pnl = sum(int(x.net_pnl_cents or 0) for x in scored)
        win_rate = wins / len(scored) if scored else None
        if scored and max_payout_total > 0:
            fee_adjusted_be = sum_cost_and_fee / max_payout_total
        else:
            fee_adjusted_be = None
        edge_over_be = (
            (win_rate - fee_adjusted_be) if win_rate is not None and fee_adjusted_be is not None else None
        )
        n_scored = len(scored)
        avg_net = net_pnl / n_scored if n_scored else None
        pnls = [int(x.net_pnl_cents or 0) for x in scored_sorted_by_bucket.get(bk, [])]
        dd = _max_drawdown_cents(pnls)
        lstreak = _longest_loss_streak(pnls)

        rc_counts: Counter[str] = Counter()
        for x in br:
            if x.result_category:
                rc_counts[str(x.result_category)] += 1

        diag = _diagnose_bucket(
            scored_entries=n_scored,
            unscored_entries=len(unscored),
            net_pnl_cents=net_pnl,
            gross_pnl_cents=gross_pnl,
            win_rate=win_rate,
            edge_over_be=edge_over_be,
            min_scored_sample=min_scored_sample,
        )

        buckets[bk] = {
            "bucket_price_cents": int(bk),
            "entries": len(br),
            "scored_entries": n_scored,
            "unscored_entries": len(unscored),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "fee_adjusted_break_even_win_rate": fee_adjusted_be,
            "edge_over_break_even": edge_over_be,
            "gross_pnl_cents": gross_pnl,
            "fees_cents": fees_paid,
            "net_pnl_cents": net_pnl,
            "avg_gross_pnl_per_trade": gross_pnl / n_scored if n_scored else None,
            "avg_fee_per_trade": fees_paid / n_scored if n_scored else None,
            "avg_net_pnl_per_trade": avg_net,
            "avg_entry_price_cents": (
                sum(float(x.simulated_avg_no_fill_cents or 0) for x in scored) / n_scored if n_scored else None
            ),
            "avg_slippage_cents": (
                sum(float(x.slippage_cents or 0) for x in scored) / n_scored if n_scored else None
            ),
            "avg_seconds_to_close": (
                sum(int(x.seconds_to_close or 0) for x in scored if x.seconds_to_close is not None)
                / max(
                    1,
                    sum(1 for x in scored if x.seconds_to_close is not None),
                )
                if scored
                else None
            ),
            "max_drawdown_cents": dd,
            "largest_win_cents": max((int(x.net_pnl_cents or 0) for x in scored), default=None),
            "largest_loss_cents": min((int(x.net_pnl_cents or 0) for x in scored), default=None),
            "longest_loss_streak": lstreak,
            "result_category_counts": dict(rc_counts),
            "diagnosis": diag,
        }

    ranked = sorted(
        ((bk, buckets[bk]["net_pnl_cents"]) for bk in default_buckets),
        key=lambda x: x[1],
        reverse=True,
    )
    if ranked:
        overall["best_bucket_by_net_pnl"] = ranked[0][0]
        overall["worst_bucket_by_net_pnl"] = ranked[-1][0]
    avg_ranked = sorted(
        (
            (bk, buckets[bk]["avg_net_pnl_per_trade"] or float("-inf"))
            for bk in default_buckets
        ),
        key=lambda x: x[1],
        reverse=True,
    )
    if avg_ranked:
        overall["best_bucket_by_avg_net_per_trade"] = avg_ranked[0][0]

    rc_totals: dict[str, dict[str, Any]] = {}
    for cat in (
        WIN_AFTER_FEES,
        WON_BUT_FEES_ERASED_PROFIT,
        WON_BUT_BAD_FILL_ERASED_PROFIT,
        LOST_RESOLVED_YES,
        UNRESOLVED,
        DATA_ERROR,
        SPECIAL_OR_AMBIGUOUS_RESOLUTION,
    ):
        sub = [x for x in rows if (x.result_category or "") == cat]
        rc_totals[cat] = {
            "count": len(sub),
            "gross_pnl_cents": sum(int(x.gross_pnl_cents or 0) for x in sub if x.scored),
            "fees_cents": sum(int(x.fee_cents or 0) for x in sub if x.scored),
            "net_pnl_cents": sum(int(x.net_pnl_cents or 0) for x in sub if x.scored),
        }

    series_agg: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"entries": 0, "scored": 0, "wins": 0, "net_pnl": 0}
    )
    for r in rows:
        st = r.series_ticker or "unknown"
        series_agg[st]["entries"] += 1
        if r.scored:
            series_agg[st]["scored"] += 1
            if int(r.net_pnl_cents or 0) > 0:
                series_agg[st]["wins"] += 1
            series_agg[st]["net_pnl"] += int(r.net_pnl_cents or 0)

    series_rows = []
    for st, v in sorted(series_agg.items(), key=lambda x: abs(x[1]["net_pnl"]), reverse=True)[:50]:
        scored_n = v["scored"]
        series_rows.append(
            {
                "series_ticker": st,
                "entries": v["entries"],
                "scored": scored_n,
                "win_rate": (v["wins"] / scored_n) if scored_n else None,
                "net_pnl": v["net_pnl"],
                "avg_net_pnl": (v["net_pnl"] / scored_n) if scored_n else None,
            }
        )

    stc: dict[str, dict[str, Any]] = defaultdict(lambda: {"entries": 0, "scored": 0, "wins": 0, "net_pnl": 0})
    for r in rows:
        lab = _bucket_seconds_label(float(r.seconds_to_close) if r.seconds_to_close is not None else None)
        stc[lab]["entries"] += 1
        if r.scored:
            stc[lab]["scored"] += 1
            if int(r.net_pnl_cents or 0) > 0:
                stc[lab]["wins"] += 1
            stc[lab]["net_pnl"] += int(r.net_pnl_cents or 0)

    spread_rows = []
    sbuck: dict[str, dict[str, Any]] = defaultdict(lambda: {"entries": 0, "net_pnl": 0})
    for r in rows:
        lab = _spread_bucket(float(r.no_spread_cents) if r.no_spread_cents is not None else None)
        sbuck[lab]["entries"] += 1
        if r.scored:
            sbuck[lab]["net_pnl"] += int(r.net_pnl_cents or 0)
    for lab, v in sbuck.items():
        spread_rows.append({"spread_bucket": lab, **v})

    slip_rows = []
    lbuck: dict[str, dict[str, Any]] = defaultdict(lambda: {"entries": 0, "net_pnl": 0})
    for r in rows:
        lab = _slippage_bucket(float(r.slippage_cents) if r.slippage_cents is not None else None)
        lbuck[lab]["entries"] += 1
        if r.scored:
            lbuck[lab]["net_pnl"] += int(r.net_pnl_cents or 0)
    for lab, v in lbuck.items():
        slip_rows.append({"slippage_bucket": lab, **v})

    fq_rows = []
    fq: dict[str, dict[str, Any]] = defaultdict(lambda: {"entries": 0, "net_pnl": 0})
    for r in rows:
        fq[r.fill_quality]["entries"] += 1
        if r.scored:
            fq[r.fill_quality]["net_pnl"] += int(r.net_pnl_cents or 0)
    for lab, v in fq.items():
        fq_rows.append({"fill_quality": lab, **v})

    warnings: list[str] = []
    notes: list[str] = []
    if overall["total_entries"] == 0:
        warnings.append("No shadow bucket entries found for this filter.")
    if overall["total_scored_entries"] == 0 and overall["total_entries"]:
        warnings.append("No scored entries yet — run scoring after markets resolve.")
    unr_ratio = (
        overall["total_unscored_entries"] / overall["total_entries"]
        if overall["total_entries"]
        else 0.0
    )
    if unr_ratio > 0.5 and overall["total_entries"]:
        warnings.append("High unresolved rate — interpret bucket rankings cautiously.")
    for bk in default_buckets:
        if buckets[bk]["scored_entries"] > 0 and buckets[bk]["scored_entries"] < min_scored_sample:
            warnings.append(f"Bucket {bk}¢ scored sample below min_scored_sample={min_scored_sample}.")
    if series_rows:
        top_share = abs(series_rows[0]["net_pnl"]) / max(
            1, abs(overall["total_net_pnl_cents"] or 1)
        )
        if top_share > 0.6 and overall["total_entries"] >= 5:
            warnings.append(
                f"Series {series_rows[0]['series_ticker']} dominates net PnL share (~{top_share:.0%})."
            )
    for bk in default_buckets:
        b = buckets[bk]
        if b["scored_entries"] and b["gross_pnl_cents"] > 0 and b["net_pnl_cents"] <= 0:
            warnings.append(f"Bucket {bk}¢ is profitable on gross but not net after fees.")
    for bk in default_buckets:
        b = buckets[bk]
        wr = b["win_rate"]
        if wr is not None and wr > 0.55 and b["net_pnl_cents"] < 0 and b["scored_entries"] >= min_scored_sample:
            warnings.append(
                f"Bucket {bk}¢ shows high win rate ({wr:.1%}) but negative net PnL — tail risk and fees matter."
            )

    report = {
        "shadow_version": shadow_version,
        "experiment_name": experiment_name,
        "generated_at": _utcnow_iso(),
        "report_name": report_name,
        "overall": overall,
        "buckets": buckets,
        "result_categories": rc_totals,
        "breakdowns": {
            "series": series_rows,
            "seconds_to_close": [
                {
                    "bucket": k,
                    **{
                        "entries": v["entries"],
                        "scored": v["scored"],
                        "win_rate": (v["wins"] / v["scored"]) if v["scored"] else None,
                        "net_pnl": v["net_pnl"],
                    },
                }
                for k, v in sorted(stc.items())
            ],
            "spread": spread_rows,
            "slippage": slip_rows,
            "fill_quality": fq_rows,
        },
        "diagnostics": {"notes": notes, "warnings": warnings},
    }

    if not include_unscored:
        report["overall"]["note"] = "include_unscored=false (counts still list unscored for transparency)"

    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    md_lines = [
        "# NO Bucket Shadow Experiment Report",
        "",
        f"- Shadow version: `{shadow_version}`",
        f"- Experiment name: `{experiment_name or '—'}`",
        f"- Generated at: {report['generated_at']}",
        f"- Report name: `{report_name}`",
        "",
        "> **Safety note:** This is a read-only shadow experiment. It does not place orders. "
        "It simulates NO entries from live visible orderbook data and scores them after settlement.",
        "",
        "## Overall summary",
        "",
        json.dumps(overall, indent=2, default=str),
        "",
        "## Bucket comparison",
        "",
        "| Bucket | Entries | Scored | Unscored | Win Rate | Break-even Win Rate | Edge Over BE | Gross PnL | Fees | Net PnL | Avg Net/Trade | Max Drawdown | Diagnosis |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for bk in default_buckets:
        b = buckets[bk]
        md_lines.append(
            "| {bk}¢ | {entries} | {scored} | {unscored} | {wr} | {be} | {edge} | {gp} | {fe} | {np} | {avg} | {dd} | {dg} |".format(
                bk=bk,
                entries=b["entries"],
                scored=b["scored_entries"],
                unscored=b["unscored_entries"],
                wr=f"{b['win_rate']:.1%}" if b["win_rate"] is not None else "N/A",
                be=f"{b['fee_adjusted_break_even_win_rate']:.3f}"
                if b["fee_adjusted_break_even_win_rate"] is not None
                else "N/A",
                edge=f"{b['edge_over_break_even']:.3f}" if b["edge_over_break_even"] is not None else "N/A",
                gp=b["gross_pnl_cents"],
                fe=b["fees_cents"],
                np=b["net_pnl_cents"],
                avg=f"{b['avg_net_pnl_per_trade']:.2f}" if b["avg_net_pnl_per_trade"] is not None else "N/A",
                dd=b["max_drawdown_cents"],
                dg=b["diagnosis"],
            )
        )

    md_lines.extend(
        [
            "",
            "## Result categories",
            "",
            "```json",
            json.dumps(rc_totals, indent=2, default=str),
            "```",
            "",
            "## Warnings",
            "",
            "\n".join(f"- {w}" for w in warnings) or "_None_",
            "",
        ]
    )
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    stdout_summary = {
        "shadow_version": shadow_version,
        "experiment_name": experiment_name,
        "generated_at": report["generated_at"],
        "paths": {"json": str(json_path.resolve()), "markdown": str(md_path.resolve())},
        "overall": overall,
        "warnings_count": len(warnings),
    }
    return stdout_summary
