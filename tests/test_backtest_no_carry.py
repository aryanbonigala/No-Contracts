"""Read-only backtest harness: config, selection, scoring, summaries, persistence (SQLite)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.database import create_all_tables, drop_all_tables
from kalshi_no_carry.db.repositories import (
    delete_backtest_run,
    insert_backtest_run,
    insert_backtest_trades,
    insert_orderbook_snapshot,
    list_feature_rows_for_backtest,
    list_orderbook_snapshots_for_feature_building,
    upsert_event,
    upsert_event_cluster,
    upsert_market,
    upsert_research_feature_row,
    upsert_strategy_split,
)
from kalshi_no_carry.db.schema import BacktestRun, BacktestTrade
from kalshi_no_carry.research.backtest_config import (
    STRATEGY_NO_CARRY_PRICE_THRESHOLD_V0,
    STRATEGY_NO_CARRY_REQUIRED_PROB_PLACEHOLDER_V0,
    BacktestConfig,
)
from kalshi_no_carry.research.backtest_no_carry import (
    CandidateSelection,
    _max_drawdown_cents,
    build_backtest_summary,
    compute_backtest_run_id,
    parse_label_no_won,
    run_no_carry_backtest_core,
    score_no_trade,
    select_no_carry_candidates,
)
from kalshi_no_carry.research.feature_dataset import build_feature_row_from_joined_record, validate_feature_row


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


def _cfg(**kw: object) -> BacktestConfig:
    base = dict(
        backtest_version="v0.7_no_carry_baseline",
        strategy_name=STRATEGY_NO_CARRY_PRICE_THRESHOLD_V0,
        split_version="sv1",
        feature_version="fv1",
        include_splits=("train", "validation"),
        include_test=False,
    )
    base.update(kw)
    return BacktestConfig(**base)  # type: ignore[arg-type]


def test_backtest_config_defaults_exclude_test() -> None:
    c = _cfg()
    assert c.include_test is False


def test_compute_mid_parse_label() -> None:
    assert parse_label_no_won("no") is True
    assert parse_label_no_won("YES") is False
    assert parse_label_no_won(None) is None
    assert parse_label_no_won("void") is None


def test_compute_backtest_run_id_stable() -> None:
    c = _cfg(max_no_ask_cents=90)
    assert compute_backtest_run_id(c) == compute_backtest_run_id(c)
    c2 = _cfg(max_no_ask_cents=91)
    assert compute_backtest_run_id(c) != compute_backtest_run_id(c2)


def test_select_rejects_incomplete_and_thresholds() -> None:
    rows = [
        {
            "split_name": "train",
            "has_complete_executable_prices": False,
            "no_ask_cents": 50,
            "seconds_to_close": 100.0,
            "market_ticker": "a",
            "cluster_id": "c1",
        },
        {
            "split_name": "train",
            "has_complete_executable_prices": True,
            "no_ask_cents": None,
            "seconds_to_close": 100.0,
            "market_ticker": "b",
            "cluster_id": "c2",
        },
        {
            "split_name": "train",
            "has_complete_executable_prices": True,
            "no_ask_cents": 5,
            "seconds_to_close": 100.0,
            "market_ticker": "c",
            "cluster_id": "c3",
        },
        {
            "split_name": "train",
            "has_complete_executable_prices": True,
            "no_ask_cents": 96,
            "seconds_to_close": 100.0,
            "market_ticker": "d",
            "cluster_id": "c4",
        },
    ]
    sel = select_no_carry_candidates(rows, _cfg(min_no_ask_cents=10, max_no_ask_cents=95))
    assert sel.selected == ()
    assert sel.rejection_counts.get("incomplete_prices") == 1
    assert sel.rejection_counts.get("missing_no_ask") == 1
    assert sel.rejection_counts.get("no_ask_too_low") == 1
    assert sel.rejection_counts.get("no_ask_too_high") == 1


def test_time_filters_and_dupes() -> None:
    rows = [
        {
            "split_name": "train",
            "has_complete_executable_prices": True,
            "no_ask_cents": 50,
            "seconds_to_close": 100.0,
            "market_ticker": "m1",
            "cluster_id": "c1",
        },
        {
            "split_name": "train",
            "has_complete_executable_prices": True,
            "no_ask_cents": 40,
            "seconds_to_close": 500.0,
            "market_ticker": "m1",
            "cluster_id": "c1",
        },
        {
            "split_name": "train",
            "has_complete_executable_prices": True,
            "no_ask_cents": 40,
            "seconds_to_close": 500.0,
            "market_ticker": "m2",
            "cluster_id": "c1",
        },
    ]
    sel = select_no_carry_candidates(rows, _cfg(min_seconds_to_close=3600))
    assert sel.rejection_counts.get("too_early") == 3

    sel2 = select_no_carry_candidates(rows, _cfg())
    assert len(sel2.selected) == 2
    assert sel2.rejection_counts.get("duplicate_market") == 1

    sel3 = select_no_carry_candidates(
        rows,
        _cfg(one_trade_per_market=False, one_trade_per_cluster=True),
    )
    assert len(sel3.selected) == 1
    assert sel3.rejection_counts.get("duplicate_cluster") >= 1


def test_split_filter_in_selection() -> None:
    rows = [
        {
            "split_name": "test",
            "has_complete_executable_prices": True,
            "no_ask_cents": 50,
            "seconds_to_close": 100.0,
            "market_ticker": "m",
            "cluster_id": "c",
        },
    ]
    sel = select_no_carry_candidates(rows, _cfg(include_test=False, include_splits=("train", "validation", "test")))
    assert sel.selected == ()
    assert sel.rejection_counts.get("split_not_included") == 1


def test_score_no_win_and_loss_and_fee_and_stake() -> None:
    c = _cfg()
    r_win = score_no_trade(
        {"no_ask_cents": 80, "label_market_result": "no", "estimated_taker_fee_cents": 0},
        c,
    )
    assert r_win["scored"] is True
    assert r_win["gross_pnl_cents"] == 20
    assert r_win["net_pnl_cents"] == 20

    r_loss = score_no_trade(
        {"no_ask_cents": 80, "label_market_result": "yes", "estimated_taker_fee_cents": 0},
        c,
    )
    assert r_loss["scored"] is True
    assert r_loss["gross_pnl_cents"] == -80

    r_fee = score_no_trade(
        {"no_ask_cents": 80, "label_market_result": "no", "estimated_taker_fee_cents": 5},
        c,
    )
    assert r_fee["net_pnl_cents"] == 15

    c2 = _cfg(stake_cents=200)
    r2 = score_no_trade(
        {"no_ask_cents": 80, "label_market_result": "no", "estimated_taker_fee_cents": 5},
        c2,
    )
    assert r2["gross_pnl_cents"] == 40
    assert r2["fee_cents"] == 10
    assert r2["net_pnl_cents"] == 30


def test_score_missing_label_unscored() -> None:
    r = score_no_trade({"no_ask_cents": 50, "label_market_result": None}, _cfg())
    assert r["scored"] is False
    assert r["unscored_reason"] == "missing_or_ambiguous_label"
    assert r["net_pnl_cents"] is None


def test_summary_flags_test_split_included() -> None:
    c = _cfg(include_test=True)
    sel = select_no_carry_candidates([], c)
    summ = build_backtest_summary(config=c, feature_rows=[], selection=sel, trade_results=[])
    assert summ["test_included"] is True
    assert any("TEST_SPLIT_INCLUDED" in w for w in summ["warnings"])


def test_summary_zero_trades() -> None:
    c = _cfg()
    sel = select_no_carry_candidates([], c)
    summ = build_backtest_summary(config=c, feature_rows=[], selection=sel, trade_results=[])
    assert summ["scored_trades"] == 0
    assert summ["candidates_selected"] == 0


def test_summary_unscored_trades_counts() -> None:
    c = _cfg()
    row = {"no_ask_cents": 50, "label_market_result": None, "snapshot_id": 1, "split_name": "train"}
    sel = CandidateSelection(selected=(row,), rejection_counts={})
    tr = [score_no_trade(row, c)]
    summ = build_backtest_summary(config=c, feature_rows=[row], selection=sel, trade_results=tr)
    assert summ["candidates_selected"] == 1
    assert summ["scored_trades"] == 0
    assert summ["unscored_trades"] == 1


def test_max_drawdown_cents_deterministic() -> None:
    assert _max_drawdown_cents([-10, 20, -5]) == 10
    assert _max_drawdown_cents([3, -2, 1]) == 2


def test_placeholder_strategy_no_trades_but_buckets() -> None:
    rows = [
        {
            "split_name": "train",
            "required_no_probability_before_fees": 0.1,
            "has_complete_executable_prices": True,
            "no_ask_cents": 50,
            "seconds_to_close": 100.0,
            "market_ticker": "m",
            "cluster_id": "c",
        },
    ]
    c = _cfg(strategy_name=STRATEGY_NO_CARRY_REQUIRED_PROB_PLACEHOLDER_V0)
    _, trades, summ = run_no_carry_backtest_core(rows, c)
    assert trades == []
    assert summ["candidates_selected"] == 0
    assert "lt_0.25" in summ["placeholder"]["required_no_probability_before_fees_buckets"]


def test_list_feature_rows_excludes_test_by_default(session_factory) -> None:
    day = datetime(2024, 6, 15, 15, 0, 0, tzinfo=timezone.utc)
    close = datetime(2024, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    with session_factory() as s:
        for sn in ("train", "test"):
            upsert_event(s, {"event_ticker": f"EVT-{sn}", "title": sn}, fetched_at=day)
            upsert_market(
                s,
                {
                    "ticker": f"MKT-{sn}",
                    "event_ticker": f"EVT-{sn}",
                    "close_time": close.isoformat(),
                    "status": "open",
                },
                fetched_at=day,
            )
            upsert_event_cluster(
                s,
                cluster_id=f"cl-{sn}",
                cluster_key=f"event_ticker:EVT-{sn}",
                event_ticker=f"EVT-{sn}",
                close_time=close,
            )
            upsert_strategy_split(s, cluster_id=f"cl-{sn}", split_name=sn, split_version="sv1")
            insert_orderbook_snapshot(
                s,
                f"MKT-{sn}",
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
        s.commit()

    with session_factory() as s:
        for sn in ("train", "test"):
            src = list_orderbook_snapshots_for_feature_building(
                s, split_version="sv1", include_splits=(sn,), include_test=(sn == "test")
            )[0]
            row = build_feature_row_from_joined_record(src, feature_version="fv1")
            assert validate_feature_row(row) == []
            upsert_research_feature_row(s, row)
        s.commit()

    with session_factory() as s:
        out = list_feature_rows_for_backtest(
            s,
            split_version="sv1",
            feature_version="fv1",
            include_splits=("train", "validation", "test"),
            include_test=False,
        )
        assert len(out) == 1
        assert out[0]["split_name"] == "train"

        out2 = list_feature_rows_for_backtest(
            s,
            split_version="sv1",
            feature_version="fv1",
            include_splits=("test",),
            include_test=True,
        )
        assert len(out2) == 1
        assert out2[0]["split_name"] == "test"


def test_backtest_run_persistence_and_delete(session_factory) -> None:
    cfg = _cfg()
    run_id = compute_backtest_run_id(cfg)
    summ = {"success": True, "rows_seen": 0}
    with session_factory() as s:
        with s.begin():
            insert_backtest_run(
                s,
                BacktestRun(
                    run_id=run_id,
                    backtest_version=cfg.backtest_version,
                    strategy_name=cfg.strategy_name,
                    split_version=cfg.split_version,
                    feature_version=cfg.feature_version,
                    config_json=cfg.model_dump(mode="json"),
                    summary_json=summ,
                    created_at=datetime.now(timezone.utc),
                    test_included=False,
                ),
            )
            insert_backtest_trades(
                s,
                run_id,
                [
                    {
                        "snapshot_id": 1,
                        "market_ticker": "x",
                        "cluster_id": "c",
                        "split_name": "train",
                        "no_ask_cents": 50,
                        "fee_cents": 0,
                        "gross_pnl_cents": 50,
                        "net_pnl_cents": 50,
                        "scored": True,
                        "unscored_reason": None,
                    }
                ],
            )
    with session_factory() as s:
        ntr = s.scalar(select(func.count()).select_from(BacktestTrade))
        assert int(ntr or 0) == 1
        deleted, n_del_trades = delete_backtest_run(s, run_id)
        assert deleted is True
        assert n_del_trades == 1
        s.commit()
        ntr2 = s.scalar(select(func.count()).select_from(BacktestTrade))
        assert int(ntr2 or 0) == 0


def test_two_distinct_runs_coexist(session_factory) -> None:
    for mx in (88, 89):
        cfg = _cfg(max_no_ask_cents=mx)
        rid = compute_backtest_run_id(cfg)
        with session_factory() as s:
            with s.begin():
                insert_backtest_run(
                    s,
                    BacktestRun(
                        run_id=rid,
                        backtest_version=cfg.backtest_version,
                        strategy_name=cfg.strategy_name,
                        split_version=cfg.split_version,
                        feature_version=cfg.feature_version,
                        config_json=cfg.model_dump(mode="json"),
                        summary_json={"k": mx},
                        created_at=datetime.now(timezone.utc),
                        test_included=False,
                    ),
                )
    with session_factory() as s:
        n = s.scalar(select(func.count()).select_from(BacktestRun))
        assert int(n or 0) == 2


def test_run_no_carry_backtest_persisted_no_session_begin_conflict(session_factory, memory_engine) -> None:
    """Regression: nested session.begin() after reads caused InvalidRequestError."""
    from kalshi_no_carry.research.backtest_no_carry import run_no_carry_backtest_persisted

    cfg = _cfg()
    out = run_no_carry_backtest_persisted(memory_engine, cfg, dry_run=False)
    assert out["success"] is True
    assert out["scored_trades"] == 0
    assert out["run_id"]
    assert out["persisted"] is True
    assert out["overwritten_existing_run"] is False
    assert out["prior_run_deleted"] is False
    assert out["prior_trades_deleted"] == 0

    with session_factory() as s:
        n = s.scalar(select(func.count()).select_from(BacktestRun))
        assert int(n or 0) == 1


def test_run_no_carry_backtest_persisted_twice_overwrites_same_run_id(session_factory, memory_engine) -> None:
    from kalshi_no_carry.research.backtest_no_carry import compute_backtest_run_id, run_no_carry_backtest_persisted

    cfg = _cfg()
    rid = compute_backtest_run_id(cfg)

    out1 = run_no_carry_backtest_persisted(memory_engine, cfg, dry_run=False)
    assert out1["overwritten_existing_run"] is False
    assert out1["prior_trades_deleted"] == 0

    out2 = run_no_carry_backtest_persisted(memory_engine, cfg, dry_run=False)
    assert out2["success"] is True
    assert out2["run_id"] == rid
    assert out2["overwritten_existing_run"] is True
    assert out2["prior_run_deleted"] is True
    assert out2["prior_trades_deleted"] == out1["trades_persisted"]

    with session_factory() as s:
        n_run = s.scalar(select(func.count()).select_from(BacktestRun))
        n_tr = s.scalar(select(func.count()).select_from(BacktestTrade))
        assert int(n_run or 0) == 1
        assert int(n_tr or 0) == int(out2["trades_persisted"])


def test_run_no_carry_backtest_persisted_no_overwrite_raises_on_second_run(memory_engine) -> None:
    from sqlalchemy.exc import IntegrityError

    from kalshi_no_carry.research.backtest_no_carry import run_no_carry_backtest_persisted

    cfg = _cfg()
    run_no_carry_backtest_persisted(memory_engine, cfg, dry_run=False)
    with pytest.raises(IntegrityError):
        run_no_carry_backtest_persisted(memory_engine, cfg, dry_run=False, overwrite_existing_run=False)
