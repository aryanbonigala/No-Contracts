"""Frozen Pydantic configuration for the NO bucket shadow experiment (v0.17a)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_SHADOW_VERSION = "v0.17a_no_bucket_shadow_experiment"
DEFAULT_EXPERIMENT_NAME = "no_bucket_shadow_experiment_v0"


def validate_bucket_windows(bucket_prices_cents: Sequence[int], tolerance_cents: int) -> None:
    """Raise ``ValueError`` if buckets are invalid or tolerance bands overlap."""
    if tolerance_cents < 0:
        raise ValueError("tolerance_cents must be non-negative")
    buckets = list(bucket_prices_cents)
    if not buckets:
        raise ValueError("bucket_prices_cents must be non-empty")
    if sorted(buckets) != buckets:
        raise ValueError("bucket_prices_cents must be sorted ascending")
    if len(set(buckets)) != len(buckets):
        raise ValueError("bucket_prices_cents must be unique")
    for b in buckets:
        if not isinstance(b, int) or not (1 <= b <= 99):
            raise ValueError(f"each bucket price must be an integer from 1 to 99, got {b!r}")
    for i, b in enumerate(buckets):
        lo_i, hi_i = b - tolerance_cents, b + tolerance_cents
        for j, c in enumerate(buckets):
            if j <= i:
                continue
            lo_j, hi_j = c - tolerance_cents, c + tolerance_cents
            if hi_i >= lo_j and hi_j >= lo_i:
                raise ValueError(
                    f"tolerance windows overlap for buckets {b}¢ and {c}¢ "
                    f"(tolerance={tolerance_cents})"
                )


class BucketShadowConfig(BaseModel):
    """Parameters for read-only shadow scans (paper portfolios only)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    shadow_version: str = Field(default=DEFAULT_SHADOW_VERSION, min_length=1)
    experiment_name: str = Field(default=DEFAULT_EXPERIMENT_NAME, min_length=1)
    bucket_prices_cents: tuple[int, ...] = (60, 70, 80, 85, 90, 95)
    entry_tolerance_cents: int = Field(default=1, ge=0, le=10)
    paper_bankroll_cents: int = Field(default=1_000_000, gt=0)
    stake_cents_per_trade: int = Field(default=10_000, gt=0)
    allow_partial_fills: bool = False
    one_entry_per_market_per_bucket: bool = True
    max_markets_per_scan: int | None = None
    max_entries_per_scan: int | None = None
    min_seconds_to_close: int | None = None
    max_seconds_to_close: int | None = None
    raw_debug_max_chars: int = Field(default=2_000, ge=0, le=10_000)
    dry_run: bool = False

    @field_validator("bucket_prices_cents", mode="before")
    @classmethod
    def _normalize_buckets(cls, v: Any) -> tuple[int, ...]:
        if v is None:
            return (60, 70, 80, 85, 90, 95)
        if isinstance(v, str):
            parts = tuple(int(p.strip()) for p in v.split(",") if p.strip())
            return parts
        if isinstance(v, (list, tuple)):
            return tuple(int(x) for x in v)
        raise TypeError("bucket_prices_cents must be tuple, list, or comma-separated str")

    @model_validator(mode="after")
    def _bucket_windows_ok(self) -> BucketShadowConfig:
        validate_bucket_windows(self.bucket_prices_cents, self.entry_tolerance_cents)
        return self

    @model_validator(mode="after")
    def _stake_vs_bankroll(self) -> BucketShadowConfig:
        if int(self.stake_cents_per_trade) > int(self.paper_bankroll_cents):
            raise ValueError("stake_cents_per_trade must be <= paper_bankroll_cents")
        return self

    @model_validator(mode="after")
    def _optional_positive_limits(self) -> BucketShadowConfig:
        if self.max_markets_per_scan is not None and self.max_markets_per_scan <= 0:
            raise ValueError("max_markets_per_scan must be positive when set")
        if self.max_entries_per_scan is not None and self.max_entries_per_scan <= 0:
            raise ValueError("max_entries_per_scan must be positive when set")
        mi, ma = self.min_seconds_to_close, self.max_seconds_to_close
        if mi is not None and ma is not None and mi > ma:
            raise ValueError("min_seconds_to_close must be <= max_seconds_to_close when both set")
        return self

    @property
    def bucket_names(self) -> tuple[str, ...]:
        return tuple(f"NO_{p}" for p in self.bucket_prices_cents)

    @property
    def bucket_windows(self) -> dict[int, tuple[int, int]]:
        t = self.entry_tolerance_cents
        return {b: (b - t, b + t) for b in self.bucket_prices_cents}
