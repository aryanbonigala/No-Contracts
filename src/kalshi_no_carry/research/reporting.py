"""Human-readable Markdown and readiness verdicts from pipeline summaries (v0.10; read-only).

Thresholds (conservative, not tuned on outcomes):
``MINIMUM_SCORABLE_ROWS_FOR_MODELING`` (100), ``MINIMUM_LABEL_COVERAGE_RATIO`` (0.5).
"""

from __future__ import annotations

from typing import Any

# Frozen conservative thresholds — not tuned from empirical results.
MINIMUM_SCORABLE_ROWS_FOR_MODELING = 100
MINIMUM_LABEL_COVERAGE_RATIO = 0.5

_READINESS_V1 = "ready_for_v1_probability_baseline"
_READINESS_MORE_DATA = "ready_for_more_data"
_READINESS_NO_DATA = "not_ready_no_data"
_READINESS_NO_OB = "not_ready_missing_orderbooks"
_READINESS_NO_SPLITS = "not_ready_missing_splits"
_READINESS_NO_LABELS = "not_ready_missing_labels"
_READINESS_NO_FEATURES = "not_ready_missing_features"
_READINESS_LOW_SCORABLE = "not_ready_low_scorable_coverage"
_READINESS_INCOMPLETE = "readiness_verdict_incomplete"


def safe_get_nested(obj: Any, path: tuple[str, ...], default: Any = None) -> Any:
    """Walk dict keys; return ``default`` on missing or non-dict."""
    cur: Any = obj
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def format_count(value: Any) -> str:
    try:
        if value is None:
            return "—"
        return str(int(value))
    except (TypeError, ValueError):
        return "—"


def format_ratio(numerator: Any, denominator: Any) -> str:
    """Return ``num/den`` as string or ``—`` if undefined."""
    try:
        n = int(numerator)
        d = int(denominator)
        if d <= 0:
            return "—"
        return f"{n / d:.1%}"
    except (TypeError, ValueError):
        return "—"


def extract_high_level_counts(summary: dict[str, Any]) -> dict[str, Any]:
    h = dict(summary.get("high_level_counts") or {})
    aud = summary.get("audit_summary") or {}
    keys = (
        "raw_markets_count",
        "raw_orderbook_snapshots_count",
        "event_clusters_count",
        "strategy_splits_count",
        "market_labels_count",
        "research_feature_rows_count",
        "scorable_feature_rows",
        "unscorable_feature_rows",
    )
    out: dict[str, Any] = {}
    for k in keys:
        if k in h:
            out[k] = h[k]
        elif k in aud:
            out[k] = aud[k]
    return out


def extract_label_coverage(summary: dict[str, Any]) -> dict[str, Any]:
    aud = summary.get("audit_summary") or {}
    return {
        "resolved_yes_count": aud.get("resolved_yes_count"),
        "resolved_no_count": aud.get("resolved_no_count"),
        "void_count": aud.get("void_count"),
        "unknown_label_count": aud.get("unknown_label_count"),
        "feature_rows_with_label": aud.get("feature_rows_with_label"),
        "feature_rows_without_label": aud.get("feature_rows_without_label"),
        "research_feature_rows_count": aud.get("research_feature_rows_count"),
    }


def extract_feature_coverage(summary: dict[str, Any]) -> dict[str, Any]:
    aud = summary.get("audit_summary") or {}
    return {
        "feature_rows_with_complete_prices": aud.get("feature_rows_with_complete_prices"),
        "feature_rows_missing_prices": aud.get("feature_rows_missing_prices"),
        "feature_rows_missing_no_ask": aud.get("feature_rows_missing_no_ask"),
        "feature_rows_missing_close_time_reference": aud.get("feature_rows_missing_close_time_reference"),
        "feature_rows_by_split": aud.get("feature_rows_by_split") or {},
        "feature_rows_by_category": aud.get("feature_rows_by_category") or {},
    }


def render_markdown_table(rows: list[list[str]], headers: list[str]) -> str:
    if not headers:
        return ""
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        padded = list(row) + [""] * (len(headers) - len(row))
        lines.append("| " + " | ".join(padded[: len(headers)]) + " |")
    return "\n".join(lines) + "\n"


def summarize_stage_table(summary: dict[str, Any]) -> list[list[str]]:
    stages = summary.get("stages") or {}
    rows: list[list[str]] = []
    for name in (
        "migrate",
        "create_tables",
        "collect_markets",
        "collect_orderbooks",
        "build_splits",
        "build_labels",
        "build_features",
        "audit",
        "backtest",
    ):
        st = stages.get(name) or {}
        enabled = "yes" if st.get("enabled") else "no"
        if st.get("skipped"):
            ok = "skipped"
        else:
            ok = "yes" if st.get("success") else "no"
        notes_parts: list[str] = []
        for key in ("rows_seen", "rows_written", "labels_written", "markets_seen", "run_id"):
            if key in st and st[key] is not None:
                notes_parts.append(f"{key}={st[key]}")
        w = st.get("warnings") or []
        if w:
            notes_parts.append(f"warnings={len(w)}")
        rows.append([name, enabled, ok, "; ".join(notes_parts) if notes_parts else "—"])
    return rows


def _recommended_safe(text: str) -> str:
    t = (text or "").lower()
    if "live" in t and "trad" in t:
        return "Continue read-only data collection or offline analysis; do not deploy capital based on this report."
    return text


def compute_research_readiness(summary: dict[str, Any]) -> dict[str, Any]:
    """
    Conservative readiness classification from a ``run_research_pipeline`` summary.

    Never recommends live trading. If audit was skipped, returns ``readiness_verdict_incomplete``.
    """
    reasons: list[str] = []
    blocking: list[str] = []

    stages = summary.get("stages") or {}
    aud_st = stages.get("audit") or {}
    audit_summary = summary.get("audit_summary")
    hlc = extract_high_level_counts(summary)

    if audit_summary is None:
        if not aud_st.get("enabled") or aud_st.get("skipped"):
            blocking.append("Audit was skipped; dataset counts and readiness verdict are incomplete.")
            reasons.append("Enable the audit stage for a full readiness assessment.")
        elif not aud_st.get("success"):
            blocking.append("Audit stage failed before producing a summary.")
            reasons.append("Fix pipeline errors and re-run with audit enabled.")
        else:
            blocking.append("Audit stage reported success but no audit_summary was attached.")
            reasons.append("Re-run the pipeline or inspect pipeline_runner output.")
        return {
            "readiness_level": _READINESS_INCOMPLETE,
            "reasons": reasons,
            "blocking_issues": blocking,
            "recommended_next_step": _recommended_safe(
                "Run the research report without --skip-audit after a successful pipeline run."
            ),
        }

    def _ic(key: str) -> int:
        v = hlc.get(key)
        if v is None and isinstance(audit_summary, dict):
            v = audit_summary.get(key)
        try:
            return int(v) if v is not None else 0
        except (TypeError, ValueError):
            return 0

    rm = _ic("raw_markets_count")
    ro = _ic("raw_orderbook_snapshots_count")
    ec = _ic("event_clusters_count")
    ss = _ic("strategy_splits_count")
    ml = _ic("market_labels_count")
    fr = _ic("research_feature_rows_count")
    scorable = _ic("scorable_feature_rows")

    label_version = (summary.get("label_version") or "").strip()

    if rm <= 0:
        blocking.append("No rows in raw_markets (or count unavailable).")
        return {
            "readiness_level": _READINESS_NO_DATA,
            "reasons": reasons + ["raw_markets_count is zero."],
            "blocking_issues": blocking,
            "recommended_next_step": _recommended_safe(
                safe_get_nested(summary, ("next_recommended_action",), "Ingest events/markets offline before modeling.")
            ),
        }

    if ro <= 0:
        blocking.append("No orderbook snapshots present.")
        return {
            "readiness_level": _READINESS_NO_OB,
            "reasons": reasons + ["raw_orderbook_snapshots_count is zero."],
            "blocking_issues": blocking,
            "recommended_next_step": _recommended_safe(
                safe_get_nested(summary, ("next_recommended_action",), "Collect or import orderbook snapshots.")
            ),
        }

    if ec <= 0 or ss <= 0:
        blocking.append("Event clusters or strategy_splits missing for this split_version.")
        return {
            "readiness_level": _READINESS_NO_SPLITS,
            "reasons": reasons + ["event_clusters_count or strategy_splits_count is zero."],
            "blocking_issues": blocking,
            "recommended_next_step": _recommended_safe("Build event clusters and chronological splits."),
        }

    if label_version and ml <= 0 and isinstance(audit_summary, dict):
        blocking.append(f"Expected labels for label_version={label_version!r} but market_labels_count is zero.")
        return {
            "readiness_level": _READINESS_NO_LABELS,
            "reasons": reasons + ["Research market labels are missing or unaudited."],
            "blocking_issues": blocking,
            "recommended_next_step": _recommended_safe("Run build_labels (or fix raw market outcome fields)."),
        }

    if fr <= 0:
        blocking.append("No research_feature_rows for this split_version and feature_version.")
        return {
            "readiness_level": _READINESS_NO_FEATURES,
            "reasons": reasons + ["research_feature_rows_count is zero."],
            "blocking_issues": blocking,
            "recommended_next_step": _recommended_safe("Build feature rows after splits, labels, and snapshots exist."),
        }

    if scorable <= 0:
        blocking.append("No scorable feature rows (labels ambiguous/void/missing or prices incomplete).")
        return {
            "readiness_level": _READINESS_LOW_SCORABLE,
            "reasons": reasons + ["scorable_feature_rows is zero."],
            "blocking_issues": blocking,
            "recommended_next_step": _recommended_safe(
                "Improve label coverage and executable quotes on feature rows; collect more resolved markets."
            ),
        }

    if scorable < MINIMUM_SCORABLE_ROWS_FOR_MODELING:
        blocking.append(
            f"Scorable rows ({scorable}) are below the conservative floor ({MINIMUM_SCORABLE_ROWS_FOR_MODELING})."
        )
        return {
            "readiness_level": _READINESS_LOW_SCORABLE,
            "reasons": reasons,
            "blocking_issues": blocking,
            "recommended_next_step": _recommended_safe(
                "Add more data (resolved markets + orderbooks) before a v1.0 probability baseline."
            ),
        }

    with_label = 0
    if isinstance(audit_summary, dict):
        with_label = int(audit_summary.get("feature_rows_with_label") or 0)
    ratio = (with_label / fr) if fr > 0 else 0.0
    if ratio < MINIMUM_LABEL_COVERAGE_RATIO:
        blocking.append(
            f"Label coverage on feature rows ({ratio:.1%}) is below {MINIMUM_LABEL_COVERAGE_RATIO:.0%}."
        )
        return {
            "readiness_level": _READINESS_LOW_SCORABLE,
            "reasons": reasons + ["Labels on feature rows are too sparse for confident supervised work."],
            "blocking_issues": blocking,
            "recommended_next_step": _recommended_safe("Merge labels into feature rows and resolve unknown outcomes."),
        }

    by_split: dict[str, Any] = {}
    if isinstance(audit_summary, dict):
        by_split = dict(audit_summary.get("feature_rows_by_split") or {})
    n_train = int(by_split.get("train") or 0)
    n_val = int(by_split.get("validation") or 0)
    if n_train <= 0 or n_val <= 0:
        blocking.append("Train or validation split has zero feature rows in this audit scope.")
        return {
            "readiness_level": _READINESS_MORE_DATA,
            "reasons": reasons
            + [
                "Both train and validation need non-empty feature-row presence before a modeling baseline.",
            ],
            "blocking_issues": blocking,
            "recommended_next_step": _recommended_safe(
                "Broaden data so chronological splits populate train and validation feature rows."
            ),
        }

    reasons.append(
        f"Scorable rows {scorable} ≥ {MINIMUM_SCORABLE_ROWS_FOR_MODELING}; label row coverage {ratio:.1%}."
    )
    reasons.append("Train and validation splits both have feature rows in the audited scope.")
    return {
        "readiness_level": _READINESS_V1,
        "reasons": reasons,
        "blocking_issues": blocking,
        "recommended_next_step": _recommended_safe(
            "Proceed to a v1.0 read-only probability baseline on train/validation only; keep test sealed."
        ),
    }


def build_research_audit_report(summary: dict[str, Any]) -> str:
    """Build a GitHub-friendly Markdown report from a pipeline summary dict."""
    readiness = compute_research_readiness(summary)
    hlc = extract_high_level_counts(summary)
    lbl = extract_label_coverage(summary)
    feat = extract_feature_coverage(summary)
    aud = summary.get("audit_summary") or {}
    bt = summary.get("backtest_summary")

    lines: list[str] = []
    lines.append("# Kalshi NO Carry Research Audit Report\n")

    if summary.get("dry_run_preview"):
        lines.append("## Preview mode (`dry_run=true`)\n")
        lines.append(
            "- **No files written** (`summary.json` / `report.md` not saved by `run_research_report.py` in this mode). "
        )
        lines.append(
            "- **No database writes**: migrations, table creation, splits, labels, features, and backtest persistence "
            "were **not** executed; this section reflects **existing** database state via read-only audit only.\n"
        )
        ignored = summary.get("ignored_write_flags") or []
        if ignored:
            lines.append(
                f"- **Suppressed write-oriented CLI requests:** `{', '.join(sorted(set(str(x) for x in ignored)))}`\n"
            )

    lines.append("## Versions\n")
    lines.append(f"- **pipeline_version:** {summary.get('pipeline_version')}")
    lines.append(f"- **split_version:** {summary.get('split_version')}")
    lines.append(f"- **feature_version:** {summary.get('feature_version')}")
    lines.append(f"- **label_version:** {summary.get('label_version')}")
    if summary.get("backtest_version"):
        lines.append(f"- **backtest_version:** {summary.get('backtest_version')}")
    inc = bool(summary.get("include_test"))
    lines.append(f"- **include_test:** `{inc}`")
    lines.append("")

    lines.append("## Safety and scope\n")
    lines.append(
        "- **Read-only research.** This report does **not** place orders, execute trades, or move balances."
    )
    lines.append("- **No model training** is performed here.")
    lines.append(
        "- **No proof of edge.** Past or hypothetical PnL does **not** validate future profitability.\n"
    )
    if inc:
        lines.append(
            "- **TEST_SPLIT_INCLUDED:** Sealed **test** rows are included — treat results as a one-time audit, "
            "not for tuning.\n"
        )
    else:
        lines.append(
            "- **Test split excluded** by default (`include_test=false`); metrics describe train/validation "
            "(and held-out test is not in scope unless explicitly enabled).\n"
        )

    lines.append("## Pipeline result\n")
    lines.append(f"- **success:** `{summary.get('success')}`")
    lines.append(f"- **failed_stage:** {summary.get('failed_stage') or '—'}")
    lines.append("")
    st_rows = summarize_stage_table(summary)
    lines.append(render_markdown_table(st_rows, ["stage", "enabled", "success", "notes"]))

    lines.append("\n## High-level dataset counts\n")
    lines.append(f"- **raw_markets_count:** {format_count(hlc.get('raw_markets_count'))}")
    lines.append(f"- **raw_orderbook_snapshots_count:** {format_count(hlc.get('raw_orderbook_snapshots_count'))}")
    lines.append(f"- **event_clusters_count:** {format_count(hlc.get('event_clusters_count'))}")
    lines.append(f"- **strategy_splits_count:** {format_count(hlc.get('strategy_splits_count'))}")
    lines.append(f"- **market_labels_count:** {format_count(hlc.get('market_labels_count'))}")
    lines.append(f"- **research_feature_rows_count:** {format_count(hlc.get('research_feature_rows_count'))}")
    lines.append(f"- **scorable_feature_rows:** {format_count(hlc.get('scorable_feature_rows'))}")
    lines.append(f"- **unscorable_feature_rows:** {format_count(hlc.get('unscorable_feature_rows'))}")
    lines.append("")

    lines.append("## Split coverage\n")
    by_split = feat.get("feature_rows_by_split") or {}
    if by_split:
        for k in sorted(by_split.keys()):
            lines.append(f"- **{k}:** {format_count(by_split.get(k))}")
    else:
        lines.append("- _No per-split feature counts in audit summary (audit may have been skipped)._")
    n_train = int(by_split.get("train") or 0) if by_split else 0
    n_val = int(by_split.get("validation") or 0) if by_split else 0
    if aud and n_train <= 0:
        lines.append("- **Warning:** no **train** feature rows in audit scope.")
    if aud and n_val <= 0:
        lines.append("- **Warning:** no **validation** feature rows in audit scope.")
    if inc:
        lines.append("- **Warning:** **test** split rows are **included** in this report.")
    lines.append("")

    lines.append("## Label coverage\n")
    lines.append(f"- **resolved_yes:** {format_count(lbl.get('resolved_yes_count'))}")
    lines.append(f"- **resolved_no:** {format_count(lbl.get('resolved_no_count'))}")
    lines.append(f"- **void:** {format_count(lbl.get('void_count'))}")
    lines.append(f"- **unknown:** {format_count(lbl.get('unknown_label_count'))}")
    frn = lbl.get("research_feature_rows_count")
    wl = lbl.get("feature_rows_with_label")
    wol = lbl.get("feature_rows_without_label")
    lines.append(
        f"- **rows_with_label / rows_without_label:** {format_count(wl)} / {format_count(wol)} "
        f"(label coverage ratio: {format_ratio(wl, frn)})"
    )
    unk = lbl.get("unknown_label_count")
    lines.append(f"- **unknown label ratio (of feature rows):** {format_ratio(unk, frn)}")
    lines.append("")

    lines.append("## Feature row coverage\n")
    lines.append(
        f"- **complete_executable_prices:** {format_count(feat.get('feature_rows_with_complete_prices'))}"
    )
    lines.append(f"- **missing_prices:** {format_count(feat.get('feature_rows_missing_prices'))}")
    lines.append(
        f"- **missing_no_ask:** {format_count(feat.get('feature_rows_missing_no_ask'))}"
    )
    lines.append(
        f"- **missing_close_time_reference:** "
        f"{format_count(feat.get('feature_rows_missing_close_time_reference'))}"
    )
    lines.append("")

    lines.append("## Scorable vs unscorable\n")
    lines.append(
        f"- **scorable_feature_rows:** {format_count(hlc.get('scorable_feature_rows'))} — "
        "rows that can be hypothetically scored given labels and executable quotes in audit logic."
    )
    lines.append(
        f"- **unscorable_feature_rows:** {format_count(hlc.get('unscorable_feature_rows'))} — "
        "ambiguous/void/missing labels or incomplete prices."
    )
    if (hlc.get("scorable_feature_rows") in (0, None)) and (hlc.get("research_feature_rows_count") or 0) > 0:
        lines.append(
            "- **Note:** Feature rows exist but **none** are scorable — check labels and price completeness."
        )
    lines.append("")

    lines.append("## Baseline backtest (read-only, hypothetical)\n")
    if bt is None:
        lines.append("Baseline backtest was not run in this report.\n")
    else:
        inner = bt.get("summary") or {}
        cand = bt.get("candidates_selected") or inner.get("candidates_selected")
        scored = bt.get("scored_trades") or inner.get("scored_trades")
        unscored = bt.get("unscored_trades") or inner.get("unscored_trades")
        net = bt.get("net_pnl_cents") if bt.get("net_pnl_cents") is not None else inner.get("net_pnl_cents")
        lines.append(
            "**Disclaimer:** figures below are **hypothetical simulation** from stored feature rows only. "
            "They **do not** prove trading edge and **do not** include live execution costs beyond stored estimates.\n"
        )
        lines.append(f"- **candidates_selected:** {format_count(cand)}")
        lines.append(f"- **scored_trades:** {format_count(scored)}")
        lines.append(f"- **unscored_trades:** {format_count(unscored)}")
        if net is not None:
            lines.append(f"- **net_pnl_cents (hypothetical):** {net}")
        else:
            lines.append("- **net_pnl_cents:** —")
        if (cand or 0) > 0 and (scored in (0, None)):
            lines.append(
                "\nBacktest selected candidates but **could not score PnL** because labels were missing or ambiguous.\n"
            )
        elif scored and int(scored) > 0:
            lines.append(
                "\nHypothetical PnL estimates are **not** validation of real-world performance. "
                "Do **not** treat positive PnL as evidence of exploitable edge without further research.\n"
            )
        lines.append("")

    lines.append("## Warnings and data-quality issues\n")
    warns = list(summary.get("warnings") or [])
    aw = list(aud.get("warnings") or []) if aud else []
    combined = warns + aw
    if not combined:
        lines.append("- _None recorded._\n")
    else:
        for w in combined:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("## Next recommended action (heuristic)\n")
    lines.append(f"{summary.get('next_recommended_action') or '—'}\n")

    lines.append("## Readiness verdict\n")
    lines.append(f"- **readiness_level:** `{readiness.get('readiness_level')}`")
    lines.append("- **blocking_issues:**")
    bi = readiness.get("blocking_issues") or []
    if not bi:
        lines.append("  - _None_")
    else:
        for b in bi:
            lines.append(f"  - {b}")
    lines.append("- **reasons:**")
    for r in readiness.get("reasons") or []:
        lines.append(f"  - {r}")
    lines.append(f"- **recommended_next_step:** {readiness.get('recommended_next_step') or '—'}")
    lines.append(
        "\n---\n\n*This report was generated by `kalshi_no_carry.research.reporting` (read-only; no live trading).*"
    )

    return "\n".join(lines)


__all__ = [
    "MINIMUM_LABEL_COVERAGE_RATIO",
    "MINIMUM_SCORABLE_ROWS_FOR_MODELING",
    "build_research_audit_report",
    "compute_research_readiness",
    "extract_feature_coverage",
    "extract_high_level_counts",
    "extract_label_coverage",
    "format_count",
    "format_ratio",
    "render_markdown_table",
    "safe_get_nested",
    "summarize_stage_table",
]
