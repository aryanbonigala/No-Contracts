"""Unit tests for deterministic event clustering (pure functions + dict rows)."""

from __future__ import annotations

from datetime import datetime, timezone

from kalshi_no_carry.research.event_clustering import (
    cluster_key_fallback,
    cluster_key_for_event_ticker,
    deterministic_cluster_id_from_key,
    draft_to_upsert_kwargs,
    merge_raw_into_cluster_drafts,
    normalize_title_for_clustering,
    reference_time_from_event_row,
    reference_time_from_market_row,
)


def test_normalize_title_deterministic() -> None:
    assert normalize_title_for_clustering("  Hello   World! ") == "hello world"
    assert normalize_title_for_clustering("A,B") == "a,b"
    assert normalize_title_for_clustering("Test") == "test"


def test_same_event_ticker_same_cluster() -> None:
    ck = cluster_key_for_event_ticker("EVT-A")
    assert deterministic_cluster_id_from_key(ck) == deterministic_cluster_id_from_key(ck)


def test_events_and_markets_merge_on_event_ticker() -> None:
    t = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    ev = {
        "event_ticker": "E1",
        "series_ticker": "S",
        "title": "Longer title here",
        "category": "politics",
        "raw_json": {"title": "Longer title here"},
        "fetched_at": t,
    }
    mk = {
        "market_ticker": "M1",
        "event_ticker": "E1",
        "title": "M",
        "raw_json": {},
        "fetched_at": t,
    }
    drafts = merge_raw_into_cluster_drafts([ev], [mk])
    assert len(drafts) == 1
    d = next(iter(drafts.values()))
    assert d.event_ticker == "E1"
    assert "M1" in d.source_market_tickers
    assert "E1" in d.source_event_tickers


def test_fallback_cluster_key_nonempty_without_event_ticker() -> None:
    mk = {
        "market_ticker": "ORPH",
        "event_ticker": None,
        "series_ticker": "KXHIGHNY",
        "title": "Will it rain?",
        "raw_json": {},
        "fetched_at": datetime(2024, 7, 15, tzinfo=timezone.utc),
    }
    ref = reference_time_from_market_row(mk)
    ck = cluster_key_fallback(mk.get("series_ticker"), mk.get("title"), ref)
    assert ck.startswith("fallback:")
    assert "KXHIGHNY" in ck
    cid = deterministic_cluster_id_from_key(ck)
    assert cid.startswith("cf:")


def test_reference_time_market_column_order() -> None:
    t_close = datetime(2024, 1, 10, tzinfo=timezone.utc)
    t_exp = datetime(2024, 2, 10, tzinfo=timezone.utc)
    row = {"close_time": t_close, "expiration_time": t_exp, "raw_json": {}, "fetched_at": None}
    assert reference_time_from_market_row(row) == t_close


def test_reference_time_market_raw_json_expiration_before_settlement() -> None:
    t_exp = datetime(2024, 3, 1, tzinfo=timezone.utc)
    t_set = datetime(2024, 4, 1, tzinfo=timezone.utc)
    row = {
        "close_time": None,
        "expiration_time": None,
        "settlement_time": None,
        "raw_json": {"expiration_time": t_exp.isoformat(), "settlement_ts": t_set.isoformat()},
        "fetched_at": datetime(2024, 5, 1, tzinfo=timezone.utc),
    }
    assert reference_time_from_market_row(row) == t_exp


def test_reference_time_market_falls_back_to_fetched_at() -> None:
    tf = datetime(2024, 8, 1, tzinfo=timezone.utc)
    row = {"close_time": None, "expiration_time": None, "settlement_time": None, "raw_json": {}, "fetched_at": tf}
    assert reference_time_from_market_row(row) == tf


def test_reference_time_event_raw_json() -> None:
    tc = datetime(2024, 1, 2, tzinfo=timezone.utc)
    row = {
        "event_ticker": "E",
        "raw_json": {"close_time": tc.isoformat()},
        "fetched_at": datetime(2024, 9, 1, tzinfo=timezone.utc),
    }
    assert reference_time_from_event_row(row) == tc


def test_draft_upsert_cluster_id_matches_deterministic_id() -> None:
    mk = {
        "market_ticker": "X",
        "event_ticker": "EVT-XYZ",
        "raw_json": {},
        "fetched_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
    }
    drafts = merge_raw_into_cluster_drafts([], [mk])
    d = next(iter(drafts.values()))
    kwargs = draft_to_upsert_kwargs(d)
    assert kwargs["cluster_id"] == deterministic_cluster_id_from_key(cluster_key_for_event_ticker("EVT-XYZ"))
