"""Unit tests for deterministic feature primitives."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kalshi_no_carry.research.features import (
    compute_mid_cents,
    compute_no_carry_fields,
    compute_spread_cents,
    compute_time_to_close_seconds,
    missing_price_reason_code,
    near_close_flags,
    summarize_orderbook_depth,
)


def test_compute_mid_cents() -> None:
    assert compute_mid_cents(40, 60) == 50
    assert compute_mid_cents(None, 60) is None


def test_compute_spread_cents() -> None:
    assert compute_spread_cents(40, 46) == 6
    assert compute_spread_cents(50, 48) == -2


def test_compute_time_to_close_positive_and_negative() -> None:
    snap = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    close = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)
    sec = compute_time_to_close_seconds(snap, close)
    assert sec == 7200.0
    sec2 = compute_time_to_close_seconds(close, snap)
    assert sec2 == -7200.0


def test_near_close_flags() -> None:
    assert near_close_flags(1800.0) == (True, True, True)
    assert near_close_flags(3 * 3600.0) == (False, True, True)
    assert near_close_flags(12 * 3600.0) == (False, False, True)
    assert near_close_flags(-100.0) == (False, False, False)


def test_no_carry_required_probability_before_fees() -> None:
    nc = compute_no_carry_fields(no_ask_cents=45, no_bid_cents=44)
    assert nc.required_no_probability_before_fees == pytest.approx(0.45)


def test_no_carry_required_probability_after_fees() -> None:
    nc = compute_no_carry_fields(no_ask_cents=50, no_bid_cents=49, contracts=1)
    assert nc.estimated_taker_fee_cents is not None
    assert nc.no_cost_cents == 50 + nc.estimated_taker_fee_cents
    assert nc.required_no_probability_after_fees == pytest.approx(nc.no_cost_cents / 100.0)


def test_no_carry_missing_no_ask() -> None:
    nc = compute_no_carry_fields(no_ask_cents=None, no_bid_cents=30)
    assert nc.required_no_probability_before_fees is None
    assert nc.estimated_taker_fee_cents is None


def test_missing_price_reason() -> None:
    assert (
        missing_price_reason_code(
            best_yes_bid_cents=1,
            best_yes_ask_cents=2,
            best_no_bid_cents=3,
            best_no_ask_cents=None,
        )
        == "missing_no_ask"
    )


def test_summarize_orderbook_depth() -> None:
    d = summarize_orderbook_depth({"yes": [{"price": 50}], "no": []})
    assert d == {"yes_level_count": 1, "no_level_count": 0}
