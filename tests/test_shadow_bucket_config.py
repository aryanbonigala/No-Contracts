"""Tests for BucketShadowConfig validation."""

from __future__ import annotations

import pytest

from kalshi_no_carry.research.shadow_bucket_config import (
    DEFAULT_EXPERIMENT_NAME,
    DEFAULT_SHADOW_VERSION,
    BucketShadowConfig,
)


def test_default_config_valid() -> None:
    c = BucketShadowConfig()
    assert c.shadow_version == DEFAULT_SHADOW_VERSION
    assert c.experiment_name == DEFAULT_EXPERIMENT_NAME
    assert c.bucket_windows[85] == (84, 86)


def test_custom_bucket_list_valid() -> None:
    c = BucketShadowConfig(bucket_prices_cents=(50, 85, 95), entry_tolerance_cents=4)
    assert c.bucket_names == ("NO_50", "NO_85", "NO_95")


def test_duplicate_bucket_invalid() -> None:
    with pytest.raises(ValueError):
        BucketShadowConfig(bucket_prices_cents=(80, 80))


def test_unsorted_bucket_list_invalid() -> None:
    with pytest.raises(ValueError):
        BucketShadowConfig(bucket_prices_cents=(90, 60))


def test_bucket_outside_range_invalid() -> None:
    with pytest.raises(ValueError):
        BucketShadowConfig(bucket_prices_cents=(0, 60))


def test_tolerance_outside_range_invalid() -> None:
    with pytest.raises(ValueError):
        BucketShadowConfig(entry_tolerance_cents=11)


def test_overlapping_tolerance_invalid() -> None:
    with pytest.raises(ValueError):
        BucketShadowConfig(bucket_prices_cents=(60, 61), entry_tolerance_cents=2)


def test_stake_gt_bankroll_invalid() -> None:
    with pytest.raises(ValueError):
        BucketShadowConfig(paper_bankroll_cents=1000, stake_cents_per_trade=2000)


def test_min_seconds_gt_max_invalid() -> None:
    with pytest.raises(ValueError):
        BucketShadowConfig(min_seconds_to_close=100, max_seconds_to_close=50)


def test_raw_debug_max_chars_too_large_invalid() -> None:
    with pytest.raises(ValueError):
        BucketShadowConfig(raw_debug_max_chars=10_001)


def test_fee_series_multiplier_effective_multiplier() -> None:
    cfg = BucketShadowConfig(
        fee_taker_multiplier=2.0,
        fee_series_multiplier_by_series_ticker=(("KXBTC", 1.5),),
    )
    assert cfg.effective_fee_multiplier_for_series(None) == 2.0
    assert pytest.approx(cfg.effective_fee_multiplier_for_series("KXBTC")) == 3.0
    assert cfg.effective_fee_multiplier_for_series("OTHER") == 2.0
