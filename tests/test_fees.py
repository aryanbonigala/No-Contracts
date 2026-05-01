"""Tests for fee estimation helpers."""

from __future__ import annotations

import pytest

from kalshi_no_carry.utils.fees import estimate_taker_fee_cents


def test_fee_symmetric_midpoint() -> None:
    # p=0.5, 10 contracts, rate 0.07 => 0.07 * 10 * 0.25 = 0.175 USD => 18 cents (ceil)
    assert estimate_taker_fee_cents(price_cents=50, contracts=10) == 18


def test_fee_zero_contracts() -> None:
    assert estimate_taker_fee_cents(price_cents=50, contracts=0) == 0


def test_fee_extremes_are_small() -> None:
    assert estimate_taker_fee_cents(price_cents=1, contracts=100, fee_rate=0.07) >= 0
    assert estimate_taker_fee_cents(price_cents=99, contracts=100, fee_rate=0.07) >= 0


def test_fee_invalid_contracts() -> None:
    with pytest.raises(ValueError):
        estimate_taker_fee_cents(price_cents=50, contracts=-1)


def test_fee_invalid_price() -> None:
    with pytest.raises(ValueError):
        estimate_taker_fee_cents(price_cents=101, contracts=1)


def test_side_parameter_accepted() -> None:
    assert estimate_taker_fee_cents(price_cents=40, contracts=3, side="yes") == estimate_taker_fee_cents(
        price_cents=40, contracts=3, side="no"
    )
