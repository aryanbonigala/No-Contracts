"""Tests for research.reporting (v0.10)."""

from __future__ import annotations

import pytest

from kalshi_no_carry.research.reporting import (
    MINIMUM_SCORABLE_ROWS_FOR_MODELING,
    build_research_audit_report,
    compute_research_readiness,
    format_ratio,
)


def _audit_base(**kwargs: object) -> dict:
    d = {
        "raw_markets_count": 10,
        "raw_orderbook_snapshots_count": 10,
        "event_clusters_count": 2,
        "strategy_splits_count": 2,
        "market_labels_count": 10,
        "research_feature_rows_count": 200,
        "scorable_feature_rows": 150,
        "feature_rows_with_label": 160,
        "feature_rows_without_label": 40,
        "resolved_yes_count": 50,
        "resolved_no_count": 50,
        "void_count": 0,
        "unknown_label_count": 100,
        "feature_rows_by_split": {"train": 120, "validation": 80},
    }
    d.update(kwargs)
    return d


def _summary(
    *,
    audit: dict | None,
    include_test: bool = False,
    backtest: dict | None = None,
    warnings: list | None = None,
) -> dict:
    return {
        "pipeline_version": "v0.10_research_report",
        "split_version": "sv",
        "feature_version": "fv",
        "label_version": "lv",
        "backtest_version": "bv",
        "include_test": include_test,
        "success": True,
        "failed_stage": None,
        "stages": {
            "audit": {"enabled": True, "success": True, "skipped": False},
        },
        "warnings": warnings or [],
        "audit_summary": audit,
        "backtest_summary": backtest,
        "high_level_counts": {},
        "next_recommended_action": "Continue offline research.",
    }


def test_build_research_audit_report_title_and_versions() -> None:
    md = build_research_audit_report(_summary(audit=_audit_base()))
    assert "# Kalshi NO Carry Research Audit Report" in md
    assert "v0.10_research_report" in md
    assert "**split_version:**" in md


def test_report_says_test_excluded_by_default() -> None:
    md = build_research_audit_report(_summary(audit=_audit_base(), include_test=False))
    assert "include_test" in md.lower()
    assert "false" in md.lower()


def test_report_shows_test_included_warning() -> None:
    md = build_research_audit_report(
        _summary(
            audit=_audit_base(),
            include_test=True,
            warnings=["TEST_SPLIT_INCLUDED: sealed test rows are included"],
        )
    )
    assert "TEST_SPLIT_INCLUDED" in md


def test_report_read_only_no_orders() -> None:
    md = build_research_audit_report(_summary(audit=_audit_base()))
    assert "read-only" in md.lower()
    assert "place orders" in md.lower()


def test_report_no_edge_claim_without_backtest() -> None:
    md = build_research_audit_report(_summary(audit=_audit_base(), backtest=None))
    assert "not run" in md.lower()
    assert "edge" in md.lower()


def test_compute_not_ready_no_data() -> None:
    r = compute_research_readiness(_summary(audit=_audit_base(raw_markets_count=0)))
    assert r["readiness_level"] == "not_ready_no_data"


def test_compute_not_ready_missing_orderbooks() -> None:
    r = compute_research_readiness(_summary(audit=_audit_base(raw_orderbook_snapshots_count=0)))
    assert r["readiness_level"] == "not_ready_missing_orderbooks"


def test_compute_not_ready_missing_splits() -> None:
    r = compute_research_readiness(_summary(audit=_audit_base(strategy_splits_count=0)))
    assert r["readiness_level"] == "not_ready_missing_splits"


def test_compute_not_ready_missing_labels() -> None:
    r = compute_research_readiness(_summary(audit=_audit_base(market_labels_count=0)))
    assert r["readiness_level"] == "not_ready_missing_labels"


def test_compute_not_ready_missing_features() -> None:
    r = compute_research_readiness(
        _summary(audit=_audit_base(research_feature_rows_count=0, scorable_feature_rows=0))
    )
    assert r["readiness_level"] == "not_ready_missing_features"


def test_compute_not_ready_low_scorable_zero() -> None:
    r = compute_research_readiness(
        _summary(audit=_audit_base(research_feature_rows_count=50, scorable_feature_rows=0))
    )
    assert r["readiness_level"] == "not_ready_low_scorable_coverage"


def test_compute_not_ready_low_scorable_below_floor() -> None:
    scorable = MINIMUM_SCORABLE_ROWS_FOR_MODELING - 1
    r = compute_research_readiness(
        _summary(
            audit=_audit_base(
                research_feature_rows_count=200,
                scorable_feature_rows=scorable,
                feature_rows_with_label=200,
            )
        )
    )
    assert r["readiness_level"] == "not_ready_low_scorable_coverage"


def test_compute_low_label_coverage_ratio() -> None:
    r = compute_research_readiness(
        _summary(
            audit=_audit_base(
                research_feature_rows_count=200,
                scorable_feature_rows=150,
                feature_rows_with_label=30,
            )
        )
    )
    assert r["readiness_level"] == "not_ready_low_scorable_coverage"


def test_compute_ready_for_more_data_when_val_empty() -> None:
    r = compute_research_readiness(
        _summary(audit=_audit_base(feature_rows_by_split={"train": 200, "validation": 0}))
    )
    assert r["readiness_level"] == "ready_for_more_data"


def test_compute_ready_for_v1_when_sufficient() -> None:
    r = compute_research_readiness(_summary(audit=_audit_base()))
    assert r["readiness_level"] == "ready_for_v1_probability_baseline"
    assert not r["blocking_issues"]


def test_compute_incomplete_when_audit_skipped() -> None:
    s = _summary(audit=None)
    s["stages"] = {"audit": {"enabled": False, "skipped": True, "success": True}}
    r = compute_research_readiness(s)
    assert r["readiness_level"] == "readiness_verdict_incomplete"


def test_recommended_next_step_never_live_trading() -> None:
    samples = [
        _summary(audit=None),
        _summary(audit=_audit_base()),
        _summary(audit=_audit_base(raw_markets_count=0)),
        {"audit_summary": None, "label_version": "x", "stages": {"audit": {"enabled": False, "skipped": True}}},
    ]
    for s in samples:
        step = compute_research_readiness(s).get("recommended_next_step", "").lower()
        assert "live trading" not in step


def test_format_ratio_handles_zero_denom() -> None:
    assert format_ratio(1, 0) == "—"


def test_backtest_unscored_message() -> None:
    bt = {
        "summary": {"candidates_selected": 5, "scored_trades": 0, "unscored_trades": 5},
        "candidates_selected": 5,
        "scored_trades": 0,
        "net_pnl_cents": None,
    }
    md = build_research_audit_report(_summary(audit=_audit_base(), backtest=bt))
    assert "could not score" in md.lower()
