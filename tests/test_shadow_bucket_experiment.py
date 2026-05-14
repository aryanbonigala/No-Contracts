"""Fill simulation, bucket matching, fee and break-even helpers."""

from __future__ import annotations

import pytest

from kalshi_no_carry.research.shadow_bucket_config import validate_bucket_windows
from kalshi_no_carry.research.shadow_bucket_experiment import (
    EMPTY_BOOK,
    FULL_FILL,
    INSUFFICIENT_DEPTH,
    PARTIAL_FILL,
    bucket_for_fill,
    buckets_for_fill,
    compute_fee_adjusted_break_even_win_rate,
    estimate_kalshi_taker_fee_cents,
    extract_orderbook_levels,
    simulate_buy_no_fill_from_yes_bids,
)


def test_extract_nested_orderbook_dict_levels() -> None:
    yes, no = extract_orderbook_levels({"orderbook": {"yes": [[15, 40], [14, 100]], "no": [[84, 50]]}})
    assert yes == [(15, 40), (14, 100)]
    assert no == [(84, 50)]


def test_extract_dict_level_shapes() -> None:
    payload = {
        "yes": [{"price": 15, "size": 40}],
        "no": [{"price_cents": 84, "quantity": 50}],
    }
    yes, no = extract_orderbook_levels(payload)
    assert yes == [(15, 40)]
    assert no == [(84, 50)]


def test_extract_string_numeric_levels() -> None:
    yes, no = extract_orderbook_levels({"yes": [["15", "40"]], "no": []})
    assert yes == [(15, 40)]
    assert no == []


def test_extract_ignores_bad_levels() -> None:
    yes, no = extract_orderbook_levels({"yes": [[150, 10], [50, 0], "oops"], "no": None})
    assert yes == []


def test_simulate_one_level_full_fill() -> None:
    sim = simulate_buy_no_fill_from_yes_bids([(15, 100)], 40)
    assert sim.fill_quality == FULL_FILL
    assert sim.contracts_filled == 40
    assert sim.avg_no_fill_cents == 85.0
    assert sim.worst_no_fill_cents == 85
    assert sim.gross_cost_cents == 40 * 85


def test_simulate_multi_level_average_and_worst() -> None:
    sim = simulate_buy_no_fill_from_yes_bids([(15, 40), (14, 100)], 100)
    assert sim.fill_quality == FULL_FILL
    assert sim.avg_no_fill_cents == pytest.approx(85.6)
    assert sim.worst_no_fill_cents == 86


def test_simulate_insufficient_depth_no_partial() -> None:
    sim = simulate_buy_no_fill_from_yes_bids([(15, 10)], 50)
    assert sim.fill_quality == INSUFFICIENT_DEPTH
    assert sim.contracts_filled == 10


def test_simulate_partial_allowed() -> None:
    sim = simulate_buy_no_fill_from_yes_bids([(15, 10)], 50, allow_partial_fills=True)
    assert sim.fill_quality == PARTIAL_FILL


def test_simulate_empty_book() -> None:
    sim = simulate_buy_no_fill_from_yes_bids([], 10)
    assert sim.fill_quality == EMPTY_BOOK


def test_simulate_sorted_descending_even_if_unsorted_input() -> None:
    sim = simulate_buy_no_fill_from_yes_bids([(10, 50), (20, 50)], 50)
    assert sim.avg_no_fill_cents == 80.0


def test_simulate_invalid_contracts_raises() -> None:
    with pytest.raises(ValueError):
        simulate_buy_no_fill_from_yes_bids([(15, 10)], 0)


def test_visible_fillable_contracts() -> None:
    sim = simulate_buy_no_fill_from_yes_bids([(15, 10)], 100)
    assert sim.visible_fillable_contracts == 10


def test_bucket_match_exact_and_tolerance() -> None:
    assert bucket_for_fill(85.0, (60, 85, 95), 1) == 85
    assert bucket_for_fill(84.0, (85,), 1) == 85
    assert bucket_for_fill(83.4, (85,), 1) is None


def test_buckets_for_fill_empty_when_no_avg() -> None:
    assert buckets_for_fill(None, (85,), 1) == ()


def test_overlap_windows_invalid() -> None:
    with pytest.raises(ValueError):
        validate_bucket_windows((60, 61), tolerance_cents=2)


def test_fee_nonnegative_and_scales() -> None:
    f50 = estimate_kalshi_taker_fee_cents(100, 50)
    f95 = estimate_kalshi_taker_fee_cents(100, 95)
    assert f50 >= 0
    assert f95 >= 0
    assert f50 > f95


def test_fee_invalid_raises() -> None:
    with pytest.raises(ValueError):
        estimate_kalshi_taker_fee_cents(0, 50)
    with pytest.raises(ValueError):
        estimate_kalshi_taker_fee_cents(10, 100)


def test_break_even_invalid_raises() -> None:
    with pytest.raises(ValueError):
        compute_fee_adjusted_break_even_win_rate(100, 10, 0)


def test_break_even_at_85_above_point_85() -> None:
    gross = 85 * 10
    fee = estimate_kalshi_taker_fee_cents(10, 85)
    be = compute_fee_adjusted_break_even_win_rate(gross, fee, 10 * 100)
    assert be > 0.85
