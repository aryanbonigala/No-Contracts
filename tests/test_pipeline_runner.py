"""Tests for research.pipeline_runner (v0.9; SQLite / mocks only)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from kalshi_no_carry.database import create_all_tables, drop_all_tables
from kalshi_no_carry.research.pipeline_runner import (
    ResearchPipelineConfig,
    recommend_next_action,
    run_research_pipeline,
)


@pytest.fixture
def memory_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_all_tables(engine)
    yield engine
    drop_all_tables(engine)
    engine.dispose()


def test_config_defaults_exclude_test_and_collectors() -> None:
    c = ResearchPipelineConfig()
    assert c.include_test is False
    assert c.collect_markets is False
    assert c.collect_orderbooks is False
    assert c.run_backtest is False


def test_pipeline_does_not_call_collectors_when_disabled(memory_engine) -> None:
    cfg = ResearchPipelineConfig(
        build_splits=False,
        build_labels=False,
        build_features=False,
        run_audit=False,
    )
    with patch("kalshi_no_carry.collectors.events.collect_events") as ce:
        with patch("kalshi_no_carry.collectors.markets.collect_markets_multi_status") as cm:
            with patch("kalshi_no_carry.collectors.orderbooks.collect_orderbooks_for_active_markets") as co:
                run_research_pipeline(memory_engine, cfg, kalshi_client=None)
    ce.assert_not_called()
    cm.assert_not_called()
    co.assert_not_called()


def test_include_test_adds_warning(memory_engine) -> None:
    cfg = ResearchPipelineConfig(
        include_test=True,
        build_splits=False,
        build_labels=False,
        build_features=False,
        run_audit=False,
    )
    out = run_research_pipeline(memory_engine, cfg)
    assert any("TEST_SPLIT_INCLUDED" in w for w in out["warnings"])


def test_stage_failure_sets_failed_stage(memory_engine) -> None:
    cfg = ResearchPipelineConfig(
        build_splits=False,
        build_labels=True,
        build_features=False,
        run_audit=False,
    )
    with patch(
        "kalshi_no_carry.research.pipeline_runner.build_market_outcome_labels_from_raw_markets",
        side_effect=RuntimeError("label boom"),
    ):
        out = run_research_pipeline(memory_engine, cfg)
    assert out["success"] is False
    assert out["failed_stage"] == "build_labels"
    assert out["stages"]["build_labels"]["success"] is False


def test_recommend_collect_markets_when_empty() -> None:
    s = {
        "high_level_counts": {"raw_markets_count": 0},
        "audit_summary": {},
        "stages": {},
    }
    assert "collect_markets" in recommend_next_action(s).lower()


def test_recommend_collect_orderbooks() -> None:
    s = {
        "high_level_counts": {"raw_markets_count": 5, "raw_orderbook_snapshots_count": 0},
        "audit_summary": {},
        "stages": {},
    }
    assert "orderbook" in recommend_next_action(s).lower()


def test_recommend_build_labels_when_missing() -> None:
    s = {
        "high_level_counts": {
            "raw_markets_count": 3,
            "raw_orderbook_snapshots_count": 3,
            "event_clusters_count": 1,
            "strategy_splits_count": 1,
            "market_labels_count": 0,
            "research_feature_rows_count": 0,
        },
        "audit_summary": {},
        "stages": {},
    }
    msg = recommend_next_action(s)
    assert "label" in msg.lower()


def test_recommend_build_features_when_no_rows() -> None:
    s = {
        "high_level_counts": {
            "raw_markets_count": 3,
            "raw_orderbook_snapshots_count": 3,
            "event_clusters_count": 1,
            "strategy_splits_count": 1,
            "market_labels_count": 5,
            "research_feature_rows_count": 0,
        },
        "audit_summary": {},
        "stages": {},
    }
    assert "feature" in recommend_next_action(s).lower()


def test_recommend_next_action_never_live_trading() -> None:
    samples = [
        None,
        {},
        {"high_level_counts": {}, "audit_summary": {}, "stages": {}},
        {
            "high_level_counts": {"scorable_feature_rows": 500},
            "audit_summary": {"research_feature_rows_count": 500},
            "stages": {"build_labels": {"enabled": True}},
        },
    ]
    for s in samples:
        text = recommend_next_action(s).lower()
        assert "live trading" not in text


def test_run_backtest_stage_wired(memory_engine) -> None:
    cfg = ResearchPipelineConfig(
        build_splits=False,
        build_labels=False,
        build_features=False,
        run_audit=False,
        run_backtest=True,
    )
    with patch(
        "kalshi_no_carry.research.pipeline_runner.run_no_carry_backtest_persisted",
        return_value={"success": True, "warnings": [], "rows_seen": 0, "run_id": "x"},
    ) as m:
        out = run_research_pipeline(memory_engine, cfg, kalshi_client=None)
    m.assert_called_once()
    assert out["stages"]["backtest"]["enabled"] is True
    assert out["backtest_summary"] is not None


def test_pipeline_stage_keys_order(memory_engine) -> None:
    cfg = ResearchPipelineConfig(
        run_migrations=False,
        create_tables=False,
        build_splits=True,
        build_labels=True,
        build_features=True,
        run_audit=True,
        run_backtest=False,
    )
    out = run_research_pipeline(memory_engine, cfg)
    names = list(out["stages"].keys())
    assert names.index("build_splits") < names.index("build_labels")
    assert names.index("build_labels") < names.index("build_features")
    assert names.index("build_features") < names.index("audit")


def test_pipeline_collect_orderbooks_with_legacy_summary_no_success_attr(memory_engine) -> None:
    """Regression: ActiveMarketsOrderbookSummary once lacked .success and crashed the pipeline."""
    cfg = ResearchPipelineConfig(
        collect_orderbooks=True,
        build_splits=False,
        build_labels=False,
        build_features=False,
        run_audit=False,
    )

    class _StubClient:
        pass

    with patch(
        "kalshi_no_carry.collectors.orderbooks.collect_orderbooks_for_active_markets",
        return_value=LegacyNoRootSuccess(),
    ) as co:
        out = run_research_pipeline(memory_engine, cfg, kalshi_client=_StubClient())
    co.assert_called_once()
    st = out["stages"]["collect_orderbooks"]
    assert st["enabled"] is True
    assert st["success"] is True
    assert st.get("records_seen") == 12
    assert st.get("records_written") == 4
    assert out["failed_stage"] is None


def test_pipeline_collect_orderbooks_dict_summary(memory_engine) -> None:
    cfg = ResearchPipelineConfig(
        collect_orderbooks=True,
        build_splits=False,
        build_labels=False,
        build_features=False,
        run_audit=False,
    )

    class _StubClient:
        pass

    fake = {
        "success": True,
        "errors": [],
        "tickers_attempted": 4,
        "snapshots_inserted": 4,
    }
    with patch(
        "kalshi_no_carry.collectors.orderbooks.collect_orderbooks_for_active_markets",
        return_value=fake,
    ):
        out = run_research_pipeline(memory_engine, cfg, kalshi_client=_StubClient())
    st = out["stages"]["collect_orderbooks"]
    assert st["success"] is True
    assert st["records_seen"] == 4
    assert st["records_written"] == 4


def test_pipeline_collect_orderbooks_dataclass_with_errors(memory_engine) -> None:
    from kalshi_no_carry.collectors.common import OrderbookCollectionSummary, utc_now

    cfg = ResearchPipelineConfig(
        collect_orderbooks=True,
        build_splits=False,
        build_labels=False,
        build_features=False,
        run_audit=False,
    )

    class _StubClient:
        pass

    bad = OrderbookCollectionSummary(
        name="t",
        started_at=utc_now(),
        finished_at=utc_now(),
        tickers_attempted=1,
        snapshots_inserted=0,
        errors=["ticker: fail"],
        success=False,
    )
    with patch(
        "kalshi_no_carry.collectors.orderbooks.collect_orderbooks_for_active_markets",
        return_value=bad,
    ):
        out = run_research_pipeline(memory_engine, cfg, kalshi_client=_StubClient())
    assert out["success"] is False
    assert out["failed_stage"] == "collect_orderbooks"
    assert out["stages"]["collect_orderbooks"]["success"] is False


class LegacyNoRootSuccess:
    """Same shape as tests in test_collector_summary_normalize (no root success)."""

    def to_public_dict(self):
        return {
            "markets": {
                "success": True,
                "errors": [],
                "records_seen": 10,
                "records_written": 2,
            },
            "orderbooks": {
                "success": True,
                "errors": [],
                "tickers_attempted": 2,
                "snapshots_inserted": 2,
            },
        }
