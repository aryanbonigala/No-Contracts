"""Pure, deterministic feature primitives (orderbook snapshot — research v0.6)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from kalshi_no_carry.utils.fees import estimate_taker_fee_cents


def compute_mid_cents(bid: int | None, ask: int | None) -> int | None:
    """Midpoint of bid/ask in cents; ``None`` if either side missing."""
    if bid is None or ask is None:
        return None
    return (int(bid) + int(ask)) // 2


def compute_spread_cents(bid: int | None, ask: int | None) -> int | None:
    """Signed spread ``ask - bid`` in cents; ``None`` if either side missing."""
    if bid is None or ask is None:
        return None
    return int(ask) - int(bid)


def market_side_crossed_or_locked(bid: int | None, ask: int | None) -> bool | None:
    """``True`` if bid >= ask (crossed or locked); ``None`` if either quote missing."""
    if bid is None or ask is None:
        return None
    return int(bid) >= int(ask)


def compute_time_to_close_seconds(
    snapshot_time: datetime,
    close_time: datetime | None,
) -> float | None:
    """
    Seconds until ``close_time`` from ``snapshot_time`` (UTC-normalized).

    **Negative** values mean the nominal close is already in the past; callers may
    treat this as a data-quality signal. ``None`` if ``close_time`` is unknown.
    """
    if close_time is None:
        return None
    st = snapshot_time if snapshot_time.tzinfo else snapshot_time.replace(tzinfo=timezone.utc)
    ct = close_time if close_time.tzinfo else close_time.replace(tzinfo=timezone.utc)
    return (ct - st).total_seconds()


def seconds_to_time_bucket_features(seconds: float | None) -> tuple[float | None, float | None, float | None]:
    """Return ``(minutes, hours, days)`` from seconds, or three ``None`` if *seconds* is ``None``."""
    if seconds is None:
        return None, None, None
    m = seconds / 60.0
    h = seconds / 3600.0
    d = seconds / 86400.0
    return m, h, d


def near_close_flags(seconds_to_close: float | None) -> tuple[bool, bool, bool]:
    """
    ``(1h, 6h, 24h)`` windows: ``True`` only when ``0 < seconds_to_close <= window``.

    Past-close (negative) or unknown yields ``False`` for all flags.
    """
    if seconds_to_close is None or seconds_to_close <= 0:
        return False, False, False
    return (
        seconds_to_close <= 3600.0,
        seconds_to_close <= 6 * 3600.0,
        seconds_to_close <= 24 * 3600.0,
    )


@dataclass(frozen=True)
class NoCarryDerived:
    no_ask_cents: int | None
    no_bid_cents: int | None
    no_payout_cents: int
    gross_no_profit_if_correct_cents: int | None
    gross_no_loss_if_wrong_cents: int | None
    required_no_probability_before_fees: float | None
    estimated_taker_fee_cents: int | None
    no_cost_cents: int | None
    required_no_probability_after_fees: float | None


def compute_no_carry_fields(
    *,
    no_ask_cents: int | None,
    no_bid_cents: int | None,
    contracts: int = 1,
    fee_rate: float = 0.07,
    no_payout_cents: int = 100,
) -> NoCarryDerived:
    """
    NO-leg scaffolding (no true edge / model).

    Breakeven probability **after** fees uses ``(no_ask + fee) / payout`` on a per-contract
    cent basis when both ask and fee are known; ``None`` otherwise.
    """
    payout = int(no_payout_cents)
    gross_profit = (payout - int(no_ask_cents)) if no_ask_cents is not None else None
    gross_loss = int(no_ask_cents) if no_ask_cents is not None else None
    p_before = (float(no_ask_cents) / float(payout)) if no_ask_cents is not None else None

    fee: int | None = None
    if no_ask_cents is not None:
        try:
            fee = estimate_taker_fee_cents(
                price_cents=int(no_ask_cents),
                contracts=int(contracts),
                fee_rate=fee_rate,
                side="no",
            )
        except ValueError:
            fee = None

    no_cost = (int(no_ask_cents) + int(fee)) if no_ask_cents is not None and fee is not None else None
    p_after: float | None = None
    if no_cost is not None and payout > 0:
        p_after = float(no_cost) / float(payout)

    return NoCarryDerived(
        no_ask_cents=no_ask_cents,
        no_bid_cents=no_bid_cents,
        no_payout_cents=payout,
        gross_no_profit_if_correct_cents=gross_profit,
        gross_no_loss_if_wrong_cents=gross_loss,
        required_no_probability_before_fees=p_before,
        estimated_taker_fee_cents=fee,
        no_cost_cents=no_cost,
        required_no_probability_after_fees=p_after,
    )


def utc_hour_and_weekday(fetched_at: datetime) -> tuple[int, int]:
    """``(hour_utc, weekday_utc)`` with ``weekday`` = ``datetime.weekday()`` (Mon=0)."""
    dt = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.hour, dt.weekday()


def summarize_orderbook_depth(raw_json: dict[str, Any] | None) -> dict[str, Any] | None:
    """Small JSON-safe summary for auditing (not a full book duplicate)."""
    if not raw_json or not isinstance(raw_json, dict):
        return None
    ob = raw_json.get("orderbook_fp", raw_json)
    if not isinstance(ob, dict):
        return None
    yes = ob.get("yes_dollars")
    if yes is None:
        yes = ob.get("yes")
    no = ob.get("no_dollars")
    if no is None:
        no = ob.get("no")
    yc = len(yes) if isinstance(yes, list) else None
    nc = len(no) if isinstance(no, list) else None
    return {"yes_level_count": yc, "no_level_count": nc}


def has_complete_executable_quotes(
    *,
    best_yes_bid_cents: int | None,
    best_yes_ask_cents: int | None,
    best_no_bid_cents: int | None,
    best_no_ask_cents: int | None,
) -> bool:
    return (
        best_yes_bid_cents is not None
        and best_yes_ask_cents is not None
        and best_no_bid_cents is not None
        and best_no_ask_cents is not None
    )


def missing_price_reason_code(
    *,
    best_yes_bid_cents: int | None,
    best_yes_ask_cents: int | None,
    best_no_bid_cents: int | None,
    best_no_ask_cents: int | None,
) -> str | None:
    if has_complete_executable_quotes(
        best_yes_bid_cents=best_yes_bid_cents,
        best_yes_ask_cents=best_yes_ask_cents,
        best_no_bid_cents=best_no_bid_cents,
        best_no_ask_cents=best_no_ask_cents,
    ):
        return None
    missing: list[str] = []
    if best_yes_bid_cents is None:
        missing.append("yes_bid")
    if best_yes_ask_cents is None:
        missing.append("yes_ask")
    if best_no_bid_cents is None:
        missing.append("no_bid")
    if best_no_ask_cents is None:
        missing.append("no_ask")
    return "missing_" + "_".join(sorted(missing))
