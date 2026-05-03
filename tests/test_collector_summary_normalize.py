"""Tests for collector summary normalization (pipeline integration)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel, Field

from kalshi_no_carry.collectors.common import (
    CollectorSummary,
    OrderbookCollectionSummary,
    normalize_collector_summary,
    utc_now,
)


@dataclass
class LegacyNoRootSuccess:
    """Mimics a legacy summary object: nested success only, no root ``success``."""

    def to_public_dict(self):
        return {
            "markets": {
                "success": True,
                "errors": [],
                "records_seen": 10,
                "records_written": 2,
                "ids_collected_count": 2,
            },
            "orderbooks": {
                "success": True,
                "errors": [],
                "tickers_attempted": 2,
                "snapshots_inserted": 2,
            },
        }


def test_normalize_orderbook_like_summary_success_when_nested_ok_and_errors_empty() -> None:
    nd = normalize_collector_summary(LegacyNoRootSuccess(), "collect_orderbooks")
    assert nd["success"] is True
    assert nd["errors"] == []


def test_normalize_success_false_when_errors_present() -> None:
    ob = OrderbookCollectionSummary(
        name="t",
        started_at=utc_now(),
        finished_at=utc_now(),
        tickers_attempted=1,
        snapshots_inserted=0,
        tickers_failed=1,
        errors=["M1: boom"],
        success=False,
    )
    nd = normalize_collector_summary(ob, "collect_orderbooks")
    assert nd["success"] is False
    assert "boom" in nd["errors"][0]


def test_normalize_dict_with_explicit_success_prioritized() -> None:
    nd = normalize_collector_summary(
        {"success": True, "errors": [], "tickers_attempted": 0, "snapshots_inserted": 0},
        "collect_orderbooks",
    )
    assert nd["success"] is True
    assert nd["detail"]["success"] is True


def test_normalize_json_serializable() -> None:
    ob = OrderbookCollectionSummary(name="t", started_at=utc_now(), finished_at=utc_now())
    nd = normalize_collector_summary(ob, "collect_orderbooks")
    json.dumps(nd)


def test_normalize_dataclass_records_counts_when_present() -> None:
    ob = OrderbookCollectionSummary(
        name="t",
        started_at=utc_now(),
        finished_at=utc_now(),
        tickers_attempted=7,
        snapshots_inserted=6,
    )
    nd = normalize_collector_summary(ob, "collect_orderbooks")
    assert nd["records_seen"] == 7
    assert nd["records_written"] == 6


def test_normalize_pydantic_model() -> None:
    class PSummary(BaseModel):
        success: bool = True
        errors: list[str] = Field(default_factory=list)
        tickers_attempted: int = 3
        snapshots_inserted: int = 3

    nd = normalize_collector_summary(PSummary(), "collect_orderbooks")
    assert nd["success"] is True
    assert nd["records_seen"] == 3
    json.dumps(nd)


def test_normalize_nested_markets_orderbooks_failed() -> None:
    class BadNested:
        def to_public_dict(self):
            return {
                "markets": {"success": True, "errors": []},
                "orderbooks": {"success": False, "errors": ["x"]},
            }

    nd = normalize_collector_summary(BadNested(), "collect_orderbooks")
    assert nd["success"] is False
    assert "x" in nd["errors"]


def test_active_markets_summary_exposes_success_and_public_dict_aggregate() -> None:
    from kalshi_no_carry.collectors.common import ActiveMarketsOrderbookSummary

    now = utc_now()
    m = CollectorSummary(
        name="m",
        started_at=now,
        finished_at=now,
        fetched_pages=1,
        records_seen=25,
        records_written=25,
        errors=[],
        success=True,
        ids_collected=["a", "b"],
    )
    o = OrderbookCollectionSummary(
        name="o",
        started_at=now,
        finished_at=now,
        tickers_attempted=2,
        snapshots_inserted=2,
        errors=[],
        success=True,
    )
    combo = ActiveMarketsOrderbookSummary(markets=m, orderbooks=o)
    assert combo.success is True
    assert combo.errors == []
    d = combo.to_public_dict()
    assert d["records_seen"] == 27
    assert d["records_written"] == 27
