"""Versioned backtest configuration (read-only harness, v0.7)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

STRATEGY_NO_CARRY_PRICE_THRESHOLD_V0 = "no_carry_price_threshold_v0"
STRATEGY_NO_CARRY_REQUIRED_PROB_PLACEHOLDER_V0 = "no_carry_required_prob_placeholder_v0"

SUPPORTED_STRATEGIES = frozenset(
    {
        STRATEGY_NO_CARRY_PRICE_THRESHOLD_V0,
        STRATEGY_NO_CARRY_REQUIRED_PROB_PLACEHOLDER_V0,
    }
)

_DEFAULT_BACKTEST_VERSION = "v0.7_no_carry_baseline"


class BacktestConfig(BaseModel):
    """
    Frozen parameters for a deterministic read-only backtest over ``research_feature_rows``.

    ``include_test`` defaults to **False**; evaluation on the sealed test split requires an
    explicit opt-in at the CLI layer as well as ``include_test=True`` here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    backtest_version: str = Field(default=_DEFAULT_BACKTEST_VERSION, min_length=1)
    strategy_name: str = Field(min_length=1)
    split_version: str = Field(min_length=1)
    feature_version: str = Field(min_length=1)
    include_splits: tuple[str, ...] = ("train", "validation")
    include_test: bool = False
    max_no_ask_cents: int = 95
    min_no_ask_cents: int = 1
    min_seconds_to_close: float | None = None
    max_seconds_to_close: float | None = None
    max_rows: int | None = None
    one_trade_per_market: bool = True
    one_trade_per_cluster: bool = False
    stake_cents: int = Field(default=100, ge=1)
    fee_model: str = "stored_estimated_taker_fee_cents"
    require_complete_prices: bool = True

    @model_validator(mode="after")
    def _ask_range(self) -> BacktestConfig:
        if int(self.min_no_ask_cents) > int(self.max_no_ask_cents):
            raise ValueError("min_no_ask_cents must be <= max_no_ask_cents")
        return self

    @field_validator("strategy_name")
    @classmethod
    def _strategy_ok(cls, v: str) -> str:
        s = (v or "").strip()
        if s not in SUPPORTED_STRATEGIES:
            raise ValueError(f"strategy_name must be one of {sorted(SUPPORTED_STRATEGIES)}")
        return s

    @field_validator("include_splits", mode="before")
    @classmethod
    def _normalize_splits(cls, v: object) -> tuple[str, ...]:
        if v is None:
            return ("train", "validation")
        if isinstance(v, str):
            parts = tuple(p.strip() for p in v.split(",") if p.strip())
            return parts if parts else ("train", "validation")
        if isinstance(v, (list, tuple)):
            parts = tuple(str(p).strip() for p in v if str(p).strip())
            return parts if parts else ("train", "validation")
        raise TypeError("include_splits must be str, list, or tuple")

    @field_validator("fee_model")
    @classmethod
    def _fee_ok(cls, v: str) -> str:
        allowed = {"stored_estimated_taker_fee_cents"}
        if (v or "").strip() not in allowed:
            raise ValueError(f"fee_model must be one of {sorted(allowed)}")
        return v.strip()

    @field_validator("max_no_ask_cents")
    @classmethod
    def _ask_bounds_max(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("max_no_ask_cents must be between 0 and 100")
        return v

    @field_validator("min_no_ask_cents")
    @classmethod
    def _ask_bounds_min(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("min_no_ask_cents must be between 0 and 100")
        return v
