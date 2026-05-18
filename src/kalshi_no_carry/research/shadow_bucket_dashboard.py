"""Static dashboard builder for shadow bucket scans (HTML + JSON + CSV)."""

from __future__ import annotations

import csv
import html
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_no_carry.db.repositories import latest_successful_shadow_scan_run_id, list_shadow_execution_probes_for_scan
from kalshi_no_carry.db.schema import EventCluster, RawMarket, ShadowBucketEntry, ShadowBucketExecutionProbe


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def max_drawdown_cents(series: list[int]) -> int:
    peak = 0
    cur = 0
    dd = 0
    for x in series:
        cur += x
        peak = max(peak, cur)
        dd = max(dd, peak - cur)
    return int(dd)


def longest_losing_streak_pnls(series: list[int]) -> int:
    best = 0
    run = 0
    for x in series:
        if x < 0:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def _cluster_map(session: Session) -> dict[str, str]:
    rows = session.execute(select(EventCluster.event_ticker, EventCluster.cluster_id)).all()
    out: dict[str, str] = {}
    for et, cid in rows:
        if et and cid:
            ek = str(et).strip()
            if ek and (ek not in out or cid < out[ek]):
                out[ek] = cid
    return out


def _markets_map(session: Session, tickers: Iterable[str]) -> dict[str, RawMarket]:
    tset = tuple(sorted({str(x).strip() for x in tickers if str(x).strip()}))
    if not tset:
        return {}
    rows = session.scalars(select(RawMarket).where(RawMarket.market_ticker.in_(tset))).all()
    return {r.market_ticker: r for r in rows}


def _load_entries(
    session: Session,
    *,
    shadow_version: str,
    experiment_name: str | None,
) -> list[ShadowBucketEntry]:
    stmt = select(ShadowBucketEntry).where(ShadowBucketEntry.shadow_version == shadow_version.strip())
    if experiment_name:
        stmt = stmt.where(ShadowBucketEntry.experiment_name == experiment_name.strip())
    return list(session.scalars(stmt.order_by(ShadowBucketEntry.id.asc())).all())


def _summarize_buckets_for_dashboard(
    entries: Sequence[ShadowBucketEntry],
    probes: Sequence[ShadowBucketExecutionProbe] | None,
    *,
    market_scan_count: int,
    include_unsettled: bool,
    min_settled_warning: int,
    buckets: tuple[int, ...],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_bucket: dict[int, list[ShadowBucketEntry]] = defaultdict(list)
    for e in entries:
        by_bucket[int(e.bucket_price_cents)].append(e)

    probe_by_b: dict[int, list[ShadowBucketExecutionProbe]] = defaultdict(list)
    if probes:
        for p in probes:
            probe_by_b[int(p.bucket_price_cents)].append(p)

    rows: list[dict[str, Any]] = []
    for b in buckets:
        br = by_bucket.get(b, [])
        scored = [x for x in br if x.scored]
        unsettled = [x for x in br if not x.scored]
        wins = [x for x in scored if int(x.net_pnl_cents or 0) > 0]
        losses = [x for x in scored if int(x.net_pnl_cents or 0) < 0]
        prs = probe_by_b.get(b, [])

        total_notional = sum(int(x.gross_cost_cents or 0) + int(x.fee_cents or 0) for x in br)
        gross_pnl = sum(int(x.gross_pnl_cents or 0) for x in scored)
        fees = sum(int(x.fee_cents or 0) for x in scored)
        net_pnl = sum(int(x.net_pnl_cents or 0) for x in scored)
        max_payout = sum(int(x.contracts_filled or 0) * 100 for x in scored)
        sum_cost_fee = sum(int(x.gross_cost_cents or 0) + int(x.fee_cents or 0) for x in scored)
        win_rate = (len(wins) / len(scored)) if scored else None
        be_wr = (sum_cost_fee / max_payout) if scored and max_payout > 0 else None

        pnls_ordered = sorted(scored, key=lambda x: (x.observed_at, x.id))
        pnl_series = [int(x.net_pnl_cents or 0) for x in pnls_ordered]
        roi = (net_pnl / total_notional) if total_notional else None

        entry_prices = [float(x.simulated_avg_no_fill_cents or 0) for x in br]
        avg_entry = statistics.mean(entry_prices) if entry_prices else None
        median_entry = float(statistics.median(entry_prices)) if entry_prices else None
        avg_filled_sz = statistics.mean([int(x.contracts_filled or 0) for x in br]) if br else None

        avg_win = statistics.mean([int(x.net_pnl_cents or 0) for x in wins]) if wins else None
        avg_loss = statistics.mean([int(x.net_pnl_cents or 0) for x in losses]) if losses else None

        gross_edge_positive = gross_pnl > 0
        fee_drag_pct = (
            float(sum(int(x.fee_drag_cents or 0) for x in scored)) / float(gross_pnl)
            if gross_edge_positive and gross_pnl != 0
            else None
        )

        fill_status_counts: dict[str, int] = defaultdict(int)
        for p in prs:
            fill_status_counts[str(p.fill_quality)] += 1

        scanned_denom = len({p.market_ticker for p in prs}) if prs else market_scan_count
        eligible_approx = scanned_denom
        full_ct = int(fill_status_counts.get("FULL_FILL", 0))
        partial_ct = int(fill_status_counts.get("PARTIAL_FILL", 0))

        warns: list[str] = []
        if len(scored) < min_settled_warning:
            warns.append(f"settled_sample_below_{min_settled_warning}")
        row_rec = {
            "bucket_price_cents": b,
            "markets_scanned": scanned_denom,
            "eligible_markets_observed_approx": eligible_approx,
            "fillable_markets_by_probe_full_or_partial_approx": full_ct + partial_ct,
            "full_fills_probes": full_ct,
            "partial_fills_probes": partial_ct,
            "insufficient_depth_probes": fill_status_counts.get("INSUFFICIENT_DEPTH", 0),
            "empty_book_probes": fill_status_counts.get("EMPTY_BOOK", 0),
            "api_error_probes": fill_status_counts.get("API_ERROR", 0),
            "invalid_book_probes": fill_status_counts.get("INVALID_BOOK", 0),
            "skipped_probes": fill_status_counts.get("SKIPPED", 0),
            "virtual_entries": len(br),
            "settled_entries": len(scored),
            "unsettled_entries": len(unsettled),
            "avg_entry_price_cents": avg_entry,
            "median_entry_price_cents": median_entry,
            "avg_filled_contracts": avg_filled_sz,
            "total_notional_cents_at_risk": total_notional,
            "total_fees_cents_on_settled": fees,
            "gross_pnl_cents_on_settled": gross_pnl,
            "net_pnl_cents_on_settled": net_pnl,
            "roi_on_notional_approx": roi,
            "win_rate_net": win_rate,
            "break_even_win_rate_after_fees": be_wr,
            "average_win_net_cents": avg_win,
            "average_loss_net_cents": avg_loss,
            "max_drawdown_net_cents_stream": max_drawdown_cents(pnl_series) if scored else 0,
            "longest_losing_streak_net": longest_losing_streak_pnls(pnl_series),
            "fee_drag_as_pct_of_positive_gross_pnl_stream": fee_drag_pct,
            "sample_warnings": warns,
            "experiment_disclaimer_correlated_buckets": True,
        }
        rows.append(row_rec)

    return rows, {"bucket_rows": rows}


def _execution_quality_rows(probes: Sequence[ShadowBucketExecutionProbe] | None, buckets: tuple[int, ...]) -> list[dict[str, Any]]:
    if not probes:
        return [
            {"bucket_price_cents": b, "full_fill_rate": None, "note": "no_probe_rows_latest_scan"}
            for b in buckets
        ]
    by_bucket: dict[int, list[ShadowBucketExecutionProbe]] = defaultdict(list)
    for p in probes:
        by_bucket[int(p.bucket_price_cents)].append(p)
    rows: list[dict[str, Any]] = []
    for b in buckets:
        prs = by_bucket.get(b, [])
        total = len(prs)
        if total == 0:
            rows.append({"bucket_price_cents": b, "note": "no_probes"})
            continue

        def rate(q: str) -> float | None:
            c = sum(1 for x in prs if x.fill_quality == q)
            return c / total

        reqs = sum(int(x.contracts_requested or 0) for x in prs)
        fills = sum(int(x.contracts_filled or 0) for x in prs)
        slips = [
            float(x.slippage_cents or 0.0)
            for x in prs
            if x.slippage_cents is not None and int(x.contracts_filled or 0) > 0
        ]
        med_depth_list = sorted(
            [
                float(x.eligible_depth_contracts or 0)
                for x in prs
                if x.eligible_depth_contracts is not None and int(x.contracts_requested or 0) > 0
            ]
        )
        median_depth = statistics.median(med_depth_list) if med_depth_list else None
        avg_slip = statistics.mean(slips) if slips else None
        avg_req = reqs / total
        avg_filled_contracts_probe = fills / total
        fill_ratio = (fills / reqs) if reqs else None

        rows.append(
            {
                "bucket_price_cents": b,
                "full_fill_rate": rate("FULL_FILL"),
                "partial_fill_rate": rate("PARTIAL_FILL"),
                "insufficient_depth_rate": rate("INSUFFICIENT_DEPTH"),
                "empty_book_rate": rate("EMPTY_BOOK"),
                "api_failure_rate": rate("API_ERROR"),
                "invalid_book_rate": rate("INVALID_BOOK"),
                "skipped_rate": rate("SKIPPED"),
                "avg_slippage_from_target_cents": avg_slip,
                "median_depth_available_contracts": median_depth,
                "avg_requested_size": avg_req,
                "avg_filled_size": avg_filled_contracts_probe,
                "fill_ratio_filled_over_requested_global": fill_ratio,
            }
        )
    return rows


def build_shadow_bucket_dashboard(
    session: Session,
    *,
    shadow_version: str,
    experiment_name: str | None,
    buckets: Sequence[int],
    output_dir: Path,
    scan_run_id: str | None = None,
    include_unsettled: bool = True,
    min_settled_sample_warning: int = 30,
    overwrite: bool = False,
    market_observation_denominator_override: int | None = None,
) -> dict[str, Any]:
    """Write ``index.html``, ``dashboard_summary.json``, and CSVs under ``output_dir``."""
    b_sorted = tuple(sorted(int(x) for x in buckets))
    out = Path(output_dir)
    if out.exists():
        if not overwrite:
            raise FileExistsError(f"dashboard output exists: {out} (pass overwrite=True to replace)")
        for child in list(out.iterdir()):
            if child.is_file():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                raise NotADirectoryError(f"nested directory not emptied: {child}")
    else:
        out.mkdir(parents=True, exist_ok=True)

    entries_full = _load_entries(session, shadow_version=shadow_version, experiment_name=experiment_name)
    entries_scope = entries_full if include_unsettled else [x for x in entries_full if x.scored]
    probe_run = scan_run_id or latest_successful_shadow_scan_run_id(
        session, shadow_version.strip(), experiment_name=experiment_name
    )
    probes_list: list[ShadowBucketExecutionProbe] | None = None
    if probe_run:
        probes_list = list_shadow_execution_probes_for_scan(session, probe_run)

    obs_denom = int(market_observation_denominator_override or len({e.market_ticker for e in entries_full}))

    bucket_rows, _ = _summarize_buckets_for_dashboard(
        entries_scope,
        probes_list,
        market_scan_count=obs_denom,
        include_unsettled=include_unsettled,
        min_settled_warning=min_settled_sample_warning,
        buckets=b_sorted,
    )

    tickers = [e.market_ticker for e in entries_scope]
    cmap = _cluster_map(session)
    mmap = _markets_map(session, tickers)

    drill_rows: list[dict[str, Any]] = []
    for e in sorted(entries_scope, key=lambda x: (x.market_ticker, x.bucket_price_cents, x.id)):
        rm = mmap.get(e.market_ticker)
        cat = getattr(rm, "category", None) if rm is not None else None
        et = e.event_ticker or getattr(rm, "event_ticker", None)
        cluster_id = cmap.get(str(et or ""), "")
        gp = int(e.gross_pnl_cents) if e.scored and e.gross_pnl_cents is not None else None
        npn = int(e.net_pnl_cents) if e.scored and e.net_pnl_cents is not None else None
        drill_rows.append(
            {
                "ticker": e.market_ticker,
                "event_ticker": et,
                "cluster_id": cluster_id,
                "category": cat or "",
                "title": getattr(rm, "title", None) if rm else None,
                "close_time": e.close_time,
                "bucket": e.bucket_price_cents,
                "entry_observed_at": e.observed_at,
                "target_price_cents": e.target_price_cents,
                "weighted_avg_no_fill_cents": e.simulated_avg_no_fill_cents,
                "contracts_requested": e.contracts_requested,
                "contracts_filled": e.contracts_filled,
                "fill_status": e.fill_quality,
                "fee_estimate_cents": e.fee_cents,
                "settlement_status": "SETTLED" if e.scored else "NOT_SETTLED_OR_UNSCORED",
                "realized_gross_pnl_cents": gp,
                "realized_net_pnl_cents": npn,
                "failure_skip_reason_probe_only": "",
            }
        )

    cat_agg: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "category": "",
            "markets_seen": set(),
            "entries": 0,
            "settled": 0,
            "unsettled": 0,
            "wins": 0,
            "gross": 0,
            "fees": 0,
            "net": 0,
            "depth_accum": [],
            "fee_drag_accum": [],
        }
    )

    probe_for_market_latest: dict[tuple[str, int], ShadowBucketExecutionProbe] = {}
    if probes_list:
        for p in probes_list:
            probe_for_market_latest[(str(p.market_ticker), int(p.bucket_price_cents))] = p

    for e in entries_scope:
        rm = mmap.get(e.market_ticker)
        ck = rm.category if rm and rm.category else "unknown"
        ca = cat_agg[ck]
        ca["category"] = ck
        ca["markets_seen"].add(e.market_ticker)
        ca["entries"] += 1
        if e.scored:
            ca["settled"] += 1
            npn = int(e.net_pnl_cents or 0)
            if npn > 0:
                ca["wins"] += 1
            ca["gross"] += int(e.gross_pnl_cents or 0)
            ca["fees"] += int(e.fee_cents or 0)
            ca["net"] += npn
            fd = int(e.fee_drag_cents or 0)
            ge = int(e.gross_pnl_cents or 0)
            if ge > 0:
                ca["fee_drag_accum"].append(fd / max(ge, 1))
        else:
            ca["unsettled"] += 1
        pr = probe_for_market_latest.get((e.market_ticker, int(e.bucket_price_cents)))
        if pr and pr.eligible_depth_contracts is not None:
            ca["depth_accum"].append(float(pr.eligible_depth_contracts))

    category_metrics: list[dict[str, Any]] = []
    for ck, bag in sorted(cat_agg.items(), key=lambda x: abs(x[1]["net"]), reverse=True):
        settled = bag["settled"]
        entries_n = bag["entries"]
        probed = settled / entries_n if entries_n else None
        wins = bag["wins"]
        cat_metrics_row = {
            "category": ck,
            "markets_scanned_approx": len(bag["markets_seen"]),
            "entries": entries_n,
            "settled_entries": settled,
            "unsettled_entries": bag["unsettled"],
            "fillability_indicator_settled_frac": probed,
            "win_rate_net_on_settled": (wins / settled) if settled else None,
            "gross_pnl_settled": bag["gross"],
            "fees_settled": bag["fees"],
            "net_pnl_settled": bag["net"],
            "avg_depth_available_estimate": statistics.mean(bag["depth_accum"]) if bag["depth_accum"] else None,
            "avg_fee_drag_ratio_on_positive_gross": statistics.mean(bag["fee_drag_accum"])
            if bag["fee_drag_accum"]
            else None,
        }
        category_metrics.append(cat_metrics_row)

    cluster_buckets: defaultdict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "cluster_id": "",
            "event_tickers": set(),
            "markets": set(),
            "bucket_entries": 0,
            "total_exposure_cost_cents": 0,
            "settled": 0,
            "net_settled": 0,
            "pnl_series": [],
        }
    )
    net_total = sum(int(e.net_pnl_cents or 0) for e in entries_scope if e.scored)
    loss_total = sum(int(e.net_pnl_cents or 0) for e in entries_scope if e.scored and int(e.net_pnl_cents or 0) < 0)

    for e in entries_scope:
        rm = mmap.get(e.market_ticker)
        et = e.event_ticker or (rm.event_ticker if rm else None) or ""
        cid = cmap.get(str(et).strip(), "orphan_cluster")
        cb = cluster_buckets[cid]
        cb["cluster_id"] = cid
        if et:
            cb["event_tickers"].add(str(et))
        cb["markets"].add(e.market_ticker)
        cb["bucket_entries"] += 1
        cb["total_exposure_cost_cents"] += int(e.gross_cost_cents or 0) + int(e.fee_cents or 0)
        if e.scored:
            cb["settled"] += 1
            pn = int(e.net_pnl_cents or 0)
            cb["net_settled"] += pn
            cb["pnl_series"].append(pn)

    cluster_rows: list[dict[str, Any]] = []
    ranked_abs = sorted(
        ((cid, bag["net_settled"]) for cid, bag in cluster_buckets.items()),
        key=lambda x: abs(x[1]),
        reverse=True,
    )
    for cid, bag in cluster_buckets.items():
        worst_loss = min(bag["pnl_series"]) if bag["pnl_series"] else 0
        share_pnl_total = bag["net_settled"] / net_total if net_total else None
        share_losses_total = bag["net_settled"] / loss_total if loss_total else None
        concentration_note = ""
        if abs(net_total) > 0 and abs(bag["net_settled"]) / abs(net_total) > 0.25:
            concentration_note = "high_cluster_share_abs_net_vs_total_abs"
        cluster_rows.append(
            {
                "cluster_id": cid,
                "event_tickers": ";".join(sorted(bag["event_tickers"]))[:4096],
                "number_of_markets": len(bag["markets"]),
                "number_of_virtual_bucket_entries": bag["bucket_entries"],
                "total_exposure_estimate_cents": bag["total_exposure_cost_cents"],
                "settled_entries_in_cluster": bag["settled"],
                "net_pnl_on_settled_cents": bag["net_settled"],
                "worst_single_entry_loss_in_cluster_cents_approx": worst_loss,
                "cluster_net_as_fraction_of_total_portfolio_net_abs": abs(bag["net_settled"]) / abs(net_total or 1),
                "cluster_net_as_fraction_of_total_loss_mag": (
                    bag["net_settled"] / loss_total if loss_total != 0 else None
                ),
                "percent_portfolio_share_signed": share_pnl_total,
                "concentration_warning": concentration_note or "",
                "pct_total_loss_share_signed_approx": share_losses_total,
            }
        )

    cluster_rows_sorted = sorted(cluster_rows, key=lambda x: abs(x["net_pnl_on_settled_cents"]), reverse=True)

    def cum_abs_top(k: int) -> float | None:
        mag_total = sum(abs(v) for _, v in ranked_abs)
        if mag_total <= 0:
            return None
        s = sum(abs(v) for _, v in ranked_abs[:k])
        return s / mag_total

    top5_share_abs = cum_abs_top(5)
    top10_share_abs = cum_abs_top(10)

    exec_quality = _execution_quality_rows(probes_list, b_sorted)

    summary_payload: dict[str, Any] = {
        "dashboard_version_meta": {
            "project_version_marker": "KalshiNoCarry_v0.18_AllMarketBucketDashboard_DuckDNSDeploy",
            "shadow_version": shadow_version.strip(),
            "experiment_name": experiment_name,
            "scan_run_used_for_execution_probes": probe_run,
        },
        "generated_at": _utc_now_iso(),
        "interpretation_notice": (
            "These are hypothetical virtual experimental NO entries inferred from reciprocal YES bids "
            "using visible depth only. Entries on multiple buckets for the same market are correlated "
            "(shared event risk). Separate gross PnL (pre-fees) vs net after local fee approximation. "
            "Shadow fills resemble live liquidity but omit queue ordering, latency, and post-trade book drift."
        ),
        "total_virtual_entries_loaded": len(entries_full),
        "cluster_concentration": {
            "top_5_abs_net_clusters_share_approx": top5_share_abs,
            "top_10_abs_net_clusters_share_approx": top10_share_abs,
        },
        "bucket_comparison": bucket_rows,
        "execution_quality_preview": exec_quality,
    }

    (out / "dashboard_summary.json").write_text(json.dumps(summary_payload, indent=2, default=str), encoding="utf-8")

    def csv_write(filename: str, fieldnames: list[str], vals: Iterable[dict[str, Any]]) -> None:
        path = out / filename
        rows_materialized = list(vals)
        with path.open("w", newline="", encoding="utf-8") as fp:
            w = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for row in rows_materialized:
                w.writerow({k: row.get(k, "") for k in fieldnames})

    bucket_fields = sorted({k for r in bucket_rows for k in r.keys()}) if bucket_rows else []
    csv_write("bucket_metrics.csv", bucket_fields, bucket_rows)

    drill_fields = sorted({k for r in drill_rows for k in r.keys()}) if drill_rows else []
    csv_write("market_drilldown.csv", drill_fields, drill_rows)

    cat_fields = sorted({k for r in category_metrics for k in r.keys()}) if category_metrics else []
    csv_write("category_metrics.csv", cat_fields, category_metrics)

    cl_fields = sorted({k for r in cluster_rows_sorted for k in r.keys()}) if cluster_rows_sorted else []
    csv_write("cluster_risk.csv", cl_fields, cluster_rows_sorted)

    ex_fields = sorted({k for r in exec_quality for k in r.keys()}) if exec_quality else []
    csv_write("execution_quality.csv", ex_fields, exec_quality)

    html = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8"/><title>Shadow bucket dashboard</title>',
        "<style>",
        "body{font-family:system-ui,Segoe UI,sans-serif;margin:24px;line-height:1.45;color:#111;}",
        "h1{font-size:1.25rem;margin-top:0;} h2{font-size:1.05rem;margin-top:1.5rem;} table{border-collapse:collapse;margin:10px 0;width:100%;}",
        "th,td{border:1px solid #ccc;padding:6px;text-align:right;font-size:0.82rem;} th{background:#f3f5f9;text-align:center;}",
        ".note{font-size:0.82rem;color:#444;}",
        "</style>",
        "</head><body>",
        "<h1>Shadow NO bucket dashboard (research / paper fills only)</h1>",
        '<p class="note">Correlation warning: buckets on one market/event are not independent. '
        "Gross vs net PnL are shown separately—fees can erase nominal edge. Shadow fills omit queue/latency effects.</p>",
        "<h2>Bucket comparison</h2>",
        _html_table(bucket_rows),
        "<h2>Execution quality</h2>",
        _html_table(exec_quality),
        "<h2>Category metrics</h2>",
        _html_table(category_metrics),
        "<h2>Cluster risk</h2>",
        _html_table(cluster_rows_sorted[:200]),
        "<h2>Market drilldown (first 250)</h2>",
        _html_table(drill_rows[:250]),
        "<p class=\"note\">Full drilldown CSV is market_drilldown.csv in this folder.</p>",
        "</body></html>",
    ]
    (out / "index.html").write_text("\n".join(html), encoding="utf-8")

    return summary_payload


def _html_table(rows: Sequence[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="note">empty</p>'
    keys = list(sorted(rows[0].keys()))
    th = "".join(f"<th>{html.escape(str(k))}</th>" for k in keys)
    tb: list[str] = []
    for r in rows:
        cells: list[str] = []
        for k in keys:
            v = r.get(k)
            cells.append(html.escape("" if v is None else str(v)))
        tb.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(tb)}</tbody></table>"

