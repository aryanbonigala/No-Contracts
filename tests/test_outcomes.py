"""Outcome label extraction and persistence (v0.8)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.database import create_all_tables, drop_all_tables
from kalshi_no_carry.db.schema import ResearchMarketLabel
from kalshi_no_carry.db.repositories import (
    bulk_upsert_market_outcome_labels,
    delete_market_outcome_labels_for_version,
    list_raw_markets_for_labeling,
    upsert_market_outcome_label,
    insert_orderbook_snapshot,
    list_orderbook_snapshots_for_feature_building,
    upsert_event,
    upsert_event_cluster,
    upsert_market,
    upsert_strategy_split,
)
from kalshi_no_carry.research.backtest_config import BacktestConfig, STRATEGY_NO_CARRY_PRICE_THRESHOLD_V0
from kalshi_no_carry.research.backtest_no_carry import select_no_carry_candidates
from kalshi_no_carry.research.feature_dataset import build_feature_row_from_joined_record, validate_feature_row
from kalshi_no_carry.research.outcomes import (
    LABEL_NO,
    LABEL_UNKNOWN,
    LABEL_VOID,
    LABEL_YES,
    build_market_outcome_labels_from_raw_markets,
    extract_market_outcome_label,
)


@pytest.fixture
def memory_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_all_tables(engine)
    yield engine
    drop_all_tables(engine)
    engine.dispose()


@pytest.fixture
def session_factory(memory_engine):
    return sessionmaker(memory_engine, expire_on_commit=False, future=True)


def test_extract_yes_from_result() -> None:
    r = extract_market_outcome_label({"ticker": "M1", "result": "yes"}, label_version="v0.8_market_outcome_labels")
    assert r["label_market_result"] == LABEL_YES
    assert r["label_yes_won"] is True
    assert r["label_no_won"] is False
    assert r["label_is_resolved"] is True
    assert r["label_confidence"] == "high"
    assert r["label_source_field"] == "result"


def test_extract_no_from_result() -> None:
    r = extract_market_outcome_label({"ticker": "M1", "result": "NO"}, label_version="v0.8_market_outcome_labels")
    assert r["label_market_result"] == LABEL_NO
    assert r["label_no_won"] is True


def test_extract_void_from_status() -> None:
    r = extract_market_outcome_label(
        {"ticker": "M1", "status": "canceled", "result": "yes"},
        label_version="v0.8_market_outcome_labels",
    )
    assert r["label_market_result"] == LABEL_VOID
    assert r["label_is_void"] is True
    assert r["label_no_won"] is None


def test_extract_unknown_open() -> None:
    r = extract_market_outcome_label(
        {"ticker": "M1", "status": "open"},
        label_version="v0.8_market_outcome_labels",
    )
    assert r["label_market_result"] == LABEL_UNKNOWN


def test_extract_missing_fields_safe() -> None:
    r = extract_market_outcome_label({}, label_version="v0.8_market_outcome_labels")
    assert r["label_market_result"] == LABEL_UNKNOWN


def test_title_not_used_for_outcome() -> None:
    r = extract_market_outcome_label(
        {"ticker": "M1", "title": "YES TEAM WINS", "status": "finalized"},
        label_version="v0.8_market_outcome_labels",
    )
    assert r["label_market_result"] == LABEL_UNKNOWN


def test_label_persist_composite_key(session_factory) -> None:
    day = datetime.now(timezone.utc)
    with session_factory() as s:
        upsert_market(s, {"ticker": "MT", "event_ticker": "E"}, fetched_at=day)
        s.commit()
    lv = "v0.8_market_outcome_labels"
    now = datetime.now(timezone.utc)
    row = ResearchMarketLabel(
        market_ticker="MT",
        label_version=lv,
        label_market_result=LABEL_YES,
        label_yes_won=True,
        label_no_won=False,
        label_is_resolved=True,
        label_is_void=False,
        label_confidence="high",
        label_source_field="result",
        label_source_value="yes",
        label_reason="test",
        extracted_at=now,
        raw_json=None,
        created_at=now,
    )
    with session_factory() as s:
        with s.begin():
            upsert_market_outcome_label(s, row)
    with session_factory() as s:
        n = s.scalar(select(func.count()).select_from(ResearchMarketLabel))
        assert int(n or 0) == 1


def test_multiple_label_versions_coexist(session_factory) -> None:
    day = datetime.now(timezone.utc)
    with session_factory() as s:
        upsert_market(s, {"ticker": "MT", "event_ticker": "E"}, fetched_at=day)
        s.commit()
    now = datetime.now(timezone.utc)
    r1 = ResearchMarketLabel(
        market_ticker="MT",
        label_version="a",
        label_market_result=LABEL_YES,
        label_yes_won=True,
        label_no_won=False,
        label_is_resolved=True,
        label_is_void=False,
        label_confidence="high",
        label_source_field="result",
        label_source_value="yes",
        label_reason="t",
        extracted_at=now,
        raw_json=None,
        created_at=now,
    )
    r2 = ResearchMarketLabel(
        market_ticker="MT",
        label_version="b",
        label_market_result=LABEL_NO,
        label_yes_won=False,
        label_no_won=True,
        label_is_resolved=True,
        label_is_void=False,
        label_confidence="high",
        label_source_field="result",
        label_source_value="no",
        label_reason="t",
        extracted_at=now,
        raw_json=None,
        created_at=now,
    )
    with session_factory() as s:
        with s.begin():
            bulk_upsert_market_outcome_labels(s, [r1, r2])
    with session_factory() as s:
        n = s.scalar(select(func.count()).select_from(ResearchMarketLabel))
        assert int(n or 0) == 2


def test_delete_one_label_version(session_factory) -> None:
    day = datetime.now(timezone.utc)
    with session_factory() as s:
        upsert_market(s, {"ticker": "MT", "event_ticker": "E"}, fetched_at=day)
        s.commit()
    now = datetime.now(timezone.utc)
    rows = [
        ResearchMarketLabel(
            market_ticker="MT",
            label_version="keep",
            label_market_result=LABEL_UNKNOWN,
            label_is_resolved=False,
            label_is_void=False,
            label_confidence="low",
            extracted_at=now,
            created_at=now,
        ),
        ResearchMarketLabel(
            market_ticker="MT",
            label_version="drop",
            label_market_result=LABEL_UNKNOWN,
            label_is_resolved=False,
            label_is_void=False,
            label_confidence="low",
            extracted_at=now,
            created_at=now,
        ),
    ]
    with session_factory() as s:
        with s.begin():
            bulk_upsert_market_outcome_labels(s, rows)
        with s.begin():
            delete_market_outcome_labels_for_version(s, label_version="drop")
        n = s.scalar(select(func.count()).select_from(ResearchMarketLabel))
        assert int(n or 0) == 1


def test_build_labels_from_raw_markets_writes(session_factory, memory_engine) -> None:
    day = datetime(2024, 6, 15, 15, 0, 0, tzinfo=timezone.utc)
    with session_factory() as s:
        upsert_market(
            s,
            {"ticker": "LAB", "event_ticker": "E", "result": "no", "close_time": day.isoformat(), "status": "finalized"},
            fetched_at=day,
        )
        s.commit()
    summ = build_market_outcome_labels_from_raw_markets(memory_engine, label_version="v0.8_market_outcome_labels")
    assert summ["labels_written"] == 1
    assert summ["resolved_no"] == 1
    with session_factory() as s:
        lst = list_raw_markets_for_labeling(s, limit=10)
        assert len(lst) == 1


def test_feature_build_with_outcome_label(session_factory) -> None:
    day = datetime(2024, 6, 15, 15, 0, 0, tzinfo=timezone.utc)
    close = datetime(2024, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    ol = ResearchMarketLabel(
        market_ticker="MKT-L",
        label_version="lv1",
        label_market_result=LABEL_YES,
        label_yes_won=True,
        label_no_won=False,
        label_is_resolved=True,
        label_is_void=False,
        label_confidence="high",
        label_source_field="result",
        label_source_value="yes",
        label_reason="t",
        extracted_at=now,
        raw_json={},
        created_at=now,
    )
    with session_factory() as s:
        upsert_event(s, {"event_ticker": "EVT-L", "title": "E"}, fetched_at=day)
        upsert_market(s, {"ticker": "MKT-L", "event_ticker": "EVT-L", "close_time": close.isoformat()}, fetched_at=day)
        upsert_event_cluster(s, cluster_id="cl-l", cluster_key="event_ticker:EVT-L", event_ticker="EVT-L", close_time=close)
        upsert_strategy_split(s, cluster_id="cl-l", split_name="train", split_version="sv1")
        insert_orderbook_snapshot(
            s,
            "MKT-L",
            {"yes": [], "no": []},
            executable_prices={
                "best_yes_bid_cents": 40,
                "best_yes_ask_cents": 60,
                "best_no_bid_cents": 40,
                "best_no_ask_cents": 60,
                "best_yes_bid_size": 1,
                "best_yes_ask_size": 1,
                "best_no_bid_size": 1,
                "best_no_ask_size": 1,
            },
        )
        upsert_market_outcome_label(s, ol)
        s.commit()
    with session_factory() as s:
        src = list_orderbook_snapshots_for_feature_building(s, split_version="sv1")[0]
        row = build_feature_row_from_joined_record(src, feature_version="fv1", outcome_label=ol)
        assert validate_feature_row(row) == []
        assert row.label_market_result == "yes"
        assert row.outcome_label_version == "lv1"
        assert row.label_no_won is False


def test_candidate_selection_ignores_labels() -> None:
    cfg = BacktestConfig(
        backtest_version="v",
        strategy_name=STRATEGY_NO_CARRY_PRICE_THRESHOLD_V0,
        split_version="sv",
        feature_version="fv",
    )
    base = dict(
        split_name="train",
        has_complete_executable_prices=True,
        no_ask_cents=50,
        seconds_to_close=100.0,
        market_ticker="m1",
        cluster_id="c1",
    )
    r1 = {**base, "label_no_won": True, "label_market_result": "yes"}
    r2 = {**base, "market_ticker": "m2", "cluster_id": "c2", "label_no_won": None, "label_market_result": None}
    sel = select_no_carry_candidates([r1, r2], cfg)
    assert len(sel.selected) == 2
