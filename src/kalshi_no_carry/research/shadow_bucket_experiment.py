"""NO bucket shadow scan: simulate fills from live orderbooks, persist compact rows (v0.17a).

Read-only: uses ``GET /markets`` and ``GET /markets/{ticker}/orderbook`` only — never orders or portfolio.
"""

from __future__ import annotations

import json
import math
import uuid
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from kalshi_no_carry.collectors.common import safe_error_message
from kalshi_no_carry.db.schema import ShadowBucketMarketObservation
from kalshi_no_carry.db.repositories import (
    create_shadow_bucket_scan_run,
    finish_shadow_bucket_scan_run,
    get_or_create_shadow_bucket_market_observation,
    has_shadow_bucket_entry,
    insert_shadow_bucket_entry,
    update_shadow_bucket_market_observation,
)
from kalshi_no_carry.kalshi_client import dollars_str_to_cents
from kalshi_no_carry.research.shadow_bucket_config import BucketShadowConfig, validate_bucket_windows
from kalshi_no_carry.utils.fees import estimate_taker_fee_cents

# --- Fill quality ---
FULL_FILL = "FULL_FILL"
PARTIAL_FILL = "PARTIAL_FILL"
INSUFFICIENT_DEPTH = "INSUFFICIENT_DEPTH"
EMPTY_BOOK = "EMPTY_BOOK"
MALFORMED_BOOK = "MALFORMED_BOOK"

# --- Rejections (scanner / observation) ---
MARKET_MALFORMED = "MARKET_MALFORMED"
SECONDS_TO_CLOSE_TOO_LOW = "SECONDS_TO_CLOSE_TOO_LOW"
SECONDS_TO_CLOSE_TOO_HIGH = "SECONDS_TO_CLOSE_TOO_HIGH"
ORDERBOOK_FETCH_FAILED = "ORDERBOOK_FETCH_FAILED"
ORDERBOOK_EMPTY = "ORDERBOOK_EMPTY"
INSUFFICIENT_DEPTH_REJ = "INSUFFICIENT_DEPTH"
AVG_FILL_OUTSIDE_BUCKET = "AVG_FILL_OUTSIDE_BUCKET"
DUPLICATE_BUCKET_ENTRY = "DUPLICATE_BUCKET_ENTRY"
MAX_ENTRIES_REACHED = "MAX_ENTRIES_REACHED"
INVALID_STAKE_OR_BUCKET = "INVALID_STAKE_OR_BUCKET"

ACTIVE_MARKET_STATUSES: tuple[str, ...] = ("open", "active")


@dataclass(frozen=True)
class FillSimulation:
    contracts_requested: int
    contracts_filled: int
    avg_no_fill_cents: float | None
    worst_no_fill_cents: int | None
    gross_cost_cents: int
    visible_fillable_contracts: int
    fill_quality: str
    levels_used: tuple[dict[str, int], ...]


def _parse_price_to_cents(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if 1 <= value <= 99 else None
        if isinstance(value, float):
            if 0 < value < 1:
                c = int(round(value * 100))
                return c if 1 <= c <= 99 else None
            if value == int(value):
                iv = int(value)
                return iv if 1 <= iv <= 99 else None
            return None
        s = str(value).strip()
        if not s:
            return None
        if "." in s:
            quanta = (Decimal(s) * Decimal(100)).quantize(Decimal("1"))
            c = int(quanta)
            return c if 1 <= c <= 99 else None
        c = int(s)
        return c if 1 <= c <= 99 else None
    except (TypeError, ValueError, ArithmeticError):
        return None


def _parse_size(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, float):
            i = int(value)
            return i if i > 0 else None
        i = int(Decimal(str(value).strip()).quantize(Decimal("1")))
        return i if i > 0 else None
    except (TypeError, ValueError, ArithmeticError):
        try:
            i = int(float(value))
            return i if i > 0 else None
        except (TypeError, ValueError):
            return None


def _extract_side_levels(raw_side: Any) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    if raw_side is None:
        return out
    if not isinstance(raw_side, list):
        return out
    for item in raw_side:
        price: int | None
        size: int | None
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            price = _parse_price_to_cents(item[0])
            size = _parse_size(item[1])
        elif isinstance(item, dict):
            if "price_cents" in item or "quantity" in item:
                price = _parse_price_to_cents(item.get("price_cents"))
                size = _parse_size(item.get("quantity"))
            else:
                price = _parse_price_to_cents(item.get("price"))
                size = _parse_size(item.get("size"))
        else:
            continue
        if price is None or size is None:
            continue
        out.append((price, size))
    return out


def extract_orderbook_levels(orderbook_payload: Any) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Return ``(yes_levels, no_levels)`` as (price_cents, size) bids per Kalshi conventions."""
    if orderbook_payload is None:
        return [], []
    payload = orderbook_payload
    if isinstance(payload, dict):
        inner = payload.get("orderbook")
        if isinstance(inner, dict):
            payload = inner
        yes_raw = payload.get("yes") or payload.get("yes_dollars")
        no_raw = payload.get("no") or payload.get("no_dollars")

        def _levels_from_dollars_lists(y_raw: Any, n_raw: Any) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
            yes_levels_l: list[tuple[int, int]] = []
            no_levels_l: list[tuple[int, int]] = []

            def _price_cents(price_raw: Any) -> int | None:
                if isinstance(price_raw, int) and not isinstance(price_raw, bool):
                    return price_raw if 1 <= price_raw <= 99 else None
                if isinstance(price_raw, float) and 0 < price_raw < 1:
                    c = int(round(price_raw * 100))
                    return c if 1 <= c <= 99 else None
                s = str(price_raw).strip()
                if not s:
                    return None
                if "." in s:
                    try:
                        c = dollars_str_to_cents(s)
                        return c if 1 <= c <= 99 else None
                    except Exception:
                        return None
                try:
                    iv = int(s)
                    return iv if 1 <= iv <= 99 else None
                except ValueError:
                    return None

            if isinstance(y_raw, list):
                for lvl in y_raw:
                    if isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
                        cents = _price_cents(lvl[0])
                        sz = _parse_size(lvl[1])
                        if cents is not None and sz is not None:
                            yes_levels_l.append((cents, sz))
            if isinstance(n_raw, list):
                for lvl in n_raw:
                    if isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
                        cents = _price_cents(lvl[0])
                        sz = _parse_size(lvl[1])
                        if cents is not None and sz is not None:
                            no_levels_l.append((cents, sz))
            return yes_levels_l, no_levels_l

        if yes_raw is not None or no_raw is not None:
            if isinstance(yes_raw, list) and yes_raw and isinstance(yes_raw[0], dict):
                return _extract_side_levels(yes_raw), _extract_side_levels(no_raw or [])
            return _levels_from_dollars_lists(yes_raw, no_raw)

        obf = payload.get("orderbook_fp")
        if isinstance(obf, dict):
            yd = obf.get("yes_dollars") or obf.get("yes")
            nd = obf.get("no_dollars") or obf.get("no")
            return _levels_from_dollars_lists(yd, nd)

        return _extract_side_levels(yes_raw or []), _extract_side_levels(no_raw or [])
    return [], []


def simulate_buy_no_fill_from_yes_bids(
    yes_levels: list[tuple[int, int]],
    contracts_requested: int,
    *,
    allow_partial_fills: bool = False,
) -> FillSimulation:
    if contracts_requested <= 0:
        raise ValueError("contracts_requested must be positive")

    visible = 0
    for yc, sz in yes_levels:
        impl = 100 - yc
        if 1 <= impl <= 99:
            visible += sz

    if not yes_levels:
        return FillSimulation(
            contracts_requested=contracts_requested,
            contracts_filled=0,
            avg_no_fill_cents=None,
            worst_no_fill_cents=None,
            gross_cost_cents=0,
            visible_fillable_contracts=visible,
            fill_quality=EMPTY_BOOK,
            levels_used=(),
        )

    sorted_levels = sorted(yes_levels, key=lambda x: x[0], reverse=True)
    remaining = contracts_requested
    gross = 0
    worst_no: int | None = None
    used: list[dict[str, int]] = []

    for yes_cents, avail in sorted_levels:
        if remaining <= 0:
            break
        implied_no = 100 - yes_cents
        if not (1 <= implied_no <= 99):
            continue
        take = min(avail, remaining)
        if take <= 0:
            continue
        gross += take * implied_no
        worst_no = implied_no if worst_no is None else max(worst_no, implied_no)
        used.append(
            {
                "yes_bid_cents": yes_cents,
                "implied_no_ask_cents": implied_no,
                "available_size": avail,
                "filled_size": take,
            }
        )
        remaining -= take

    filled = contracts_requested - remaining
    if filled == contracts_requested:
        qual = FULL_FILL
        avg = gross / filled if filled else None
    elif filled > 0 and not allow_partial_fills:
        qual = INSUFFICIENT_DEPTH
        avg = gross / filled
    elif filled > 0:
        qual = PARTIAL_FILL
        avg = gross / filled
    else:
        qual = INSUFFICIENT_DEPTH
        avg = None

    return FillSimulation(
        contracts_requested=contracts_requested,
        contracts_filled=filled,
        avg_no_fill_cents=float(avg) if avg is not None else None,
        worst_no_fill_cents=worst_no,
        gross_cost_cents=gross,
        visible_fillable_contracts=visible,
        fill_quality=qual,
        levels_used=tuple(used),
    )


def bucket_for_fill(
    avg_fill_cents: float | None,
    bucket_prices_cents: Sequence[int],
    tolerance_cents: int,
) -> int | None:
    got = buckets_for_fill(avg_fill_cents, bucket_prices_cents, tolerance_cents)
    if len(got) > 1:
        raise ValueError("overlapping buckets matched average fill (invalid configuration)")
    return got[0] if got else None


def buckets_for_fill(
    avg_fill_cents: float | None,
    bucket_prices_cents: Sequence[int],
    tolerance_cents: int,
) -> tuple[int, ...]:
    validate_bucket_windows(bucket_prices_cents, tolerance_cents)
    if avg_fill_cents is None:
        return ()
    out: list[int] = []
    for b in bucket_prices_cents:
        lo = b - tolerance_cents
        hi = b + tolerance_cents
        if lo <= avg_fill_cents <= hi:
            out.append(b)
    return tuple(out)


def estimate_kalshi_taker_fee_cents(contract_count: int, price_cents: float | int) -> int:
    if contract_count <= 0:
        raise ValueError("contract_count must be positive")
    pc = float(price_cents)
    if pc <= 0 or pc >= 100:
        raise ValueError("price_cents must be strictly between 0 and 100")
    rounded = int(round(pc))
    rounded = max(1, min(99, rounded))
    return estimate_taker_fee_cents(price_cents=rounded, contracts=contract_count)


def compute_fee_adjusted_break_even_win_rate(
    gross_cost_cents: int,
    fee_cents: int,
    max_payout_cents: int,
) -> float:
    if max_payout_cents <= 0:
        raise ValueError("max_payout_cents must be positive")
    if gross_cost_cents < 0 or fee_cents < 0:
        raise ValueError("costs must be non-negative")
    return (gross_cost_cents + fee_cents) / max_payout_cents


def _parse_iso_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        s = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def normalize_market_for_shadow(market: Any) -> dict[str, Any]:
    malformed = False
    market_ticker = ""
    event_ticker: str | None = None
    series_ticker: str | None = None
    status: str | None = None
    close_time: datetime | None = None

    if hasattr(market, "market_ticker"):
        market_ticker = str(getattr(market, "market_ticker") or "").strip()
        event_ticker = getattr(market, "event_ticker", None)
        if event_ticker is not None:
            event_ticker = str(event_ticker).strip() or None
        series_ticker = getattr(market, "series_ticker", None)
        if series_ticker is not None:
            series_ticker = str(series_ticker).strip() or None
        status = getattr(market, "status", None)
        if status is not None:
            status = str(status).strip() or None
        close_time = getattr(market, "close_time", None)
        if close_time is not None and not isinstance(close_time, datetime):
            close_time = _parse_iso_dt(close_time)
    elif isinstance(market, dict):
        market_ticker = str(market.get("ticker") or market.get("market_ticker") or "").strip()
        et = market.get("event_ticker")
        event_ticker = str(et).strip() if et not in (None, "") else None
        st = market.get("series_ticker")
        series_ticker = str(st).strip() if st not in (None, "") else None
        stat = market.get("status")
        status = str(stat).strip() if stat not in (None, "") else None
        close_time = _parse_iso_dt(market.get("close_time"))
    else:
        malformed = True

    if not market_ticker:
        malformed = True

    return {
        "market_ticker": market_ticker,
        "event_ticker": event_ticker,
        "series_ticker": series_ticker,
        "status": status,
        "close_time": close_time,
        "malformed": malformed,
    }


def compute_seconds_to_close(observed_at: datetime, close_time: datetime | None) -> int | None:
    if close_time is None:
        return None
    obs = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=timezone.utc)
    cl = close_time if close_time.tzinfo else close_time.replace(tzinfo=timezone.utc)
    return int((cl - obs).total_seconds())


def summarize_book_for_no_entry(
    yes_levels: list[tuple[int, int]],
    no_levels: list[tuple[int, int]],
) -> dict[str, Any]:
    yes_best = max((p for p, _ in yes_levels), default=None)
    no_best = max((p for p, _ in no_levels), default=None)
    implied_no_ask = (100 - yes_best) if yes_best is not None else None
    spread: int | None = None
    if implied_no_ask is not None and no_best is not None:
        spread = implied_no_ask - no_best
    return {
        "yes_bid_best_cents": yes_best,
        "no_bid_best_cents": no_best,
        "implied_no_ask_best_cents": implied_no_ask,
        "no_spread_cents": spread,
    }


def _closest_bucket_distance(
    implied_no_ask: float | None,
    bucket_prices_cents: Sequence[int],
) -> tuple[int | None, float | None]:
    if implied_no_ask is None or not bucket_prices_cents:
        return None, None
    best_b: int | None = None
    best_d = float("inf")
    for b in bucket_prices_cents:
        d = abs(float(implied_no_ask) - float(b))
        if d < best_d:
            best_d = d
            best_b = b
    return best_b, float(best_d) if best_b is not None else None


def _bound_debug_payload(payload: Any, max_chars: int) -> dict[str, Any] | None:
    if max_chars <= 0:
        return None
    try:
        s = json.dumps(payload, default=str, separators=(",", ":"))
    except TypeError:
        s = json.dumps({"repr": repr(payload)}, separators=(",", ":"))
    if len(s) <= max_chars:
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            parsed = s
        return {"payload": parsed}
    return {"truncated": True, "prefix": s[:max_chars]}


def _reload_shadow_observation(session: Session, shadow_version: str, experiment_name: str, market_ticker: str) -> ShadowBucketMarketObservation:
    stmt = select(ShadowBucketMarketObservation).where(
        and_(
            ShadowBucketMarketObservation.shadow_version == shadow_version,
            ShadowBucketMarketObservation.experiment_name == experiment_name,
            ShadowBucketMarketObservation.market_ticker == market_ticker,
        )
    )
    row = session.execute(stmt).scalar_one()
    return row


def run_bucket_shadow_scan_persisted(
    session: Session,
    client: Any,
    config: BucketShadowConfig,
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Paginate active markets, simulate bucket fills, persist compact rows."""
    obs_at = observed_at or datetime.now(timezone.utc)
    scan_run_id = str(uuid.uuid4())
    entries_by_bucket: dict[str, int] = {str(b): 0 for b in config.bucket_prices_cents}
    rejection_reasons: Counter[str] = Counter()

    summary_template = {
        "shadow_version": config.shadow_version,
        "experiment_name": config.experiment_name,
        "scan_run_id": scan_run_id,
        "dry_run": config.dry_run,
        "markets_seen": 0,
        "orderbooks_attempted": 0,
        "orderbooks_successful": 0,
        "orderbooks_failed": 0,
        "entries_inserted": 0,
        "entries_by_bucket": dict(entries_by_bucket),
        "fill_failures": 0,
        "top_rejection_reasons": {},
        "started_at": obs_at.isoformat(),
        "finished_at": None,
    }

    create_shadow_bucket_scan_run(session, config, scan_run_id, obs_at)
    session.commit()

    counts = {
        "markets_seen": 0,
        "orderbooks_attempted": 0,
        "orderbooks_successful": 0,
        "orderbooks_failed": 0,
        "entries_inserted": 0,
        "rejections_recorded": 0,
        "fill_failures": 0,
    }

    entries_inserted_total = 0

    def bump_rejection(reason: str) -> None:
        rejection_reasons[reason] += 1
        counts["rejections_recorded"] += 1

    try:

        def market_iter() -> Iterator[dict[str, Any]]:
            seen: set[str] = set()
            for st in ACTIVE_MARKET_STATUSES:
                if not hasattr(client, "iter_markets"):
                    raise AttributeError("client must provide iter_markets(limit=..., status=...)")
                for m in client.iter_markets(limit=200, status=st):
                    if isinstance(m, dict):
                        tid = str(m.get("ticker") or "").strip()
                        if tid and tid not in seen:
                            seen.add(tid)
                            yield m

        for market in market_iter():
            if config.max_markets_per_scan is not None and counts["markets_seen"] >= config.max_markets_per_scan:
                break
            counts["markets_seen"] += 1
            nm = normalize_market_for_shadow(market)
            mt = nm["market_ticker"]

            defaults = {
                "event_ticker": nm["event_ticker"],
                "series_ticker": nm["series_ticker"],
            }
            ob_row = get_or_create_shadow_bucket_market_observation(
                session,
                config.shadow_version,
                config.experiment_name,
                mt,
                defaults,
            )
            now = datetime.now(timezone.utc)
            update_shadow_bucket_market_observation(
                session,
                ob_row,
                {
                    "times_scanned": ob_row.times_scanned + 1,
                    "last_seen_at": obs_at,
                    "first_seen_at": ob_row.first_seen_at or obs_at,
                    "event_ticker": nm["event_ticker"] or ob_row.event_ticker,
                    "series_ticker": nm["series_ticker"] or ob_row.series_ticker,
                    "updated_at": now,
                },
            )

            if nm["malformed"]:
                bump_rejection(MARKET_MALFORMED)
                update_shadow_bucket_market_observation(
                    session,
                    ob_row,
                    {"last_rejection_reason": MARKET_MALFORMED, "updated_at": now},
                )
                session.commit()
                continue

            session.flush()
            ob_row = _reload_shadow_observation(session, config.shadow_version, config.experiment_name, mt)

            sec_close = compute_seconds_to_close(obs_at, nm["close_time"])
            skip_book = False
            if config.min_seconds_to_close is not None:
                if sec_close is None:
                    skip_book = True
                    bump_rejection(SECONDS_TO_CLOSE_TOO_LOW)
                    update_shadow_bucket_market_observation(
                        session,
                        ob_row,
                        {"last_rejection_reason": SECONDS_TO_CLOSE_TOO_LOW, "updated_at": now},
                    )
                elif sec_close < config.min_seconds_to_close:
                    skip_book = True
                    bump_rejection(SECONDS_TO_CLOSE_TOO_LOW)
                    update_shadow_bucket_market_observation(
                        session,
                        ob_row,
                        {"last_rejection_reason": SECONDS_TO_CLOSE_TOO_LOW, "updated_at": now},
                    )
            if (
                not skip_book
                and config.max_seconds_to_close is not None
                and sec_close is not None
                and sec_close > config.max_seconds_to_close
            ):
                skip_book = True
                bump_rejection(SECONDS_TO_CLOSE_TOO_HIGH)
                update_shadow_bucket_market_observation(
                    session,
                    ob_row,
                    {"last_rejection_reason": SECONDS_TO_CLOSE_TOO_HIGH, "updated_at": now},
                )

            book_summary: dict[str, Any] | None = None
            yes_levels: list[tuple[int, int]] = []
            no_levels: list[tuple[int, int]] = []

            if skip_book:
                session.commit()
                continue

            session.flush()
            ob_row = _reload_shadow_observation(session, config.shadow_version, config.experiment_name, mt)

            counts["orderbooks_attempted"] += 1
            update_shadow_bucket_market_observation(
                session,
                ob_row,
                {
                    "orderbooks_attempted": ob_row.orderbooks_attempted + 1,
                    "updated_at": now,
                },
            )

            try:
                raw_book = client.get_orderbook(mt)
            except Exception:
                counts["orderbooks_failed"] += 1
                bump_rejection(ORDERBOOK_FETCH_FAILED)
                update_shadow_bucket_market_observation(
                    session,
                    ob_row,
                    {
                        "orderbooks_failed": ob_row.orderbooks_failed + 1,
                        "last_rejection_reason": ORDERBOOK_FETCH_FAILED,
                        "updated_at": datetime.now(timezone.utc),
                    },
                )
                session.commit()
                continue

            session.flush()
            ob_row = _reload_shadow_observation(session, config.shadow_version, config.experiment_name, mt)

            counts["orderbooks_successful"] += 1
            update_shadow_bucket_market_observation(
                session,
                ob_row,
                {
                    "orderbooks_successful": ob_row.orderbooks_successful + 1,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            session.flush()
            ob_row = _reload_shadow_observation(session, config.shadow_version, config.experiment_name, mt)

            yes_levels, no_levels = extract_orderbook_levels(raw_book)
            book_summary = summarize_book_for_no_entry(yes_levels, no_levels)
            implied = book_summary.get("implied_no_ask_best_cents")
            if implied is None and not yes_levels:
                bump_rejection(ORDERBOOK_EMPTY)

            # Observation rolling book stats
            extra_obs: dict[str, Any] = {
                "updated_at": datetime.now(timezone.utc),
            }
            if implied is not None:
                cur_min = ob_row.min_observed_no_ask_cents
                extra_obs["min_observed_no_ask_cents"] = (
                    float(implied) if cur_min is None else min(float(cur_min), float(implied))
                )
            nb = book_summary.get("no_bid_best_cents")
            if nb is not None:
                cur_mx = ob_row.max_observed_no_bid_cents
                extra_obs["max_observed_no_bid_cents"] = (
                    float(nb) if cur_mx is None else max(float(cur_mx), float(nb))
                )
            sp = book_summary.get("no_spread_cents")
            if sp is not None:
                cur_s = ob_row.min_observed_spread_cents
                extra_obs["min_observed_spread_cents"] = (
                    float(sp) if cur_s is None else min(float(cur_s), float(sp))
                )
            cb, cdist = _closest_bucket_distance(
                float(implied) if implied is not None else None,
                config.bucket_prices_cents,
            )
            if cb is not None:
                extra_obs["closest_bucket_price_cents"] = cb
                extra_obs["closest_bucket_distance_cents"] = cdist
            update_shadow_bucket_market_observation(session, ob_row, extra_obs)
            session.flush()
            ob_row = _reload_shadow_observation(session, config.shadow_version, config.experiment_name, mt)

            entered_buckets: list[int] = list(ob_row.entered_buckets_json or []) if isinstance(ob_row.entered_buckets_json, list) else []

            for bucket_price in config.bucket_prices_cents:
                if (
                    config.max_entries_per_scan is not None
                    and entries_inserted_total >= config.max_entries_per_scan
                ):
                    bump_rejection(MAX_ENTRIES_REACHED)
                    update_shadow_bucket_market_observation(
                        session,
                        ob_row,
                        {
                            "last_rejection_reason": MAX_ENTRIES_REACHED,
                            "updated_at": datetime.now(timezone.utc),
                        },
                    )
                    break

                if config.one_entry_per_market_per_bucket and has_shadow_bucket_entry(
                    session,
                    config.shadow_version,
                    config.experiment_name,
                    mt,
                    bucket_price,
                ):
                    bump_rejection(DUPLICATE_BUCKET_ENTRY)
                    update_shadow_bucket_market_observation(
                        session,
                        ob_row,
                        {
                            "last_rejection_reason": DUPLICATE_BUCKET_ENTRY,
                            "updated_at": datetime.now(timezone.utc),
                        },
                    )
                    continue

                contracts_requested = math.floor(config.stake_cents_per_trade / bucket_price)
                if contracts_requested <= 0:
                    bump_rejection(INVALID_STAKE_OR_BUCKET)
                    counts["fill_failures"] += 1
                    update_shadow_bucket_market_observation(
                        session,
                        ob_row,
                        {
                            "last_rejection_reason": INVALID_STAKE_OR_BUCKET,
                            "updated_at": datetime.now(timezone.utc),
                        },
                    )
                    continue

                sim = simulate_buy_no_fill_from_yes_bids(
                    yes_levels,
                    contracts_requested,
                    allow_partial_fills=config.allow_partial_fills,
                )

                acceptable = sim.fill_quality == FULL_FILL or (
                    config.allow_partial_fills and sim.fill_quality == PARTIAL_FILL
                )
                if not acceptable:
                    counts["fill_failures"] += 1
                    bump_rejection(INSUFFICIENT_DEPTH_REJ)
                    update_shadow_bucket_market_observation(
                        session,
                        ob_row,
                        {
                            "last_rejection_reason": INSUFFICIENT_DEPTH_REJ,
                            "updated_at": datetime.now(timezone.utc),
                        },
                    )
                    continue

                matched = bucket_for_fill(
                    sim.avg_no_fill_cents,
                    config.bucket_prices_cents,
                    config.entry_tolerance_cents,
                )
                if matched != bucket_price:
                    counts["fill_failures"] += 1
                    bump_rejection(AVG_FILL_OUTSIDE_BUCKET)
                    update_shadow_bucket_market_observation(
                        session,
                        ob_row,
                        {
                            "last_rejection_reason": AVG_FILL_OUTSIDE_BUCKET,
                            "updated_at": datetime.now(timezone.utc),
                        },
                    )
                    continue

                avg_fill = float(sim.avg_no_fill_cents or 0.0)
                fee_cents = estimate_kalshi_taker_fee_cents(sim.contracts_filled, avg_fill)
                gross_cost = sim.gross_cost_cents
                net_cost = gross_cost + fee_cents
                slip = avg_fill - float(bucket_price)
                dbg = _bound_debug_payload(
                    {"levels_used": [dict(x) for x in sim.levels_used]},
                    config.raw_debug_max_chars,
                )

                entry_payload = {
                    "shadow_version": config.shadow_version,
                    "experiment_name": config.experiment_name,
                    "scan_run_id": scan_run_id,
                    "bucket_price_cents": bucket_price,
                    "bucket_name": f"NO_{bucket_price}",
                    "market_ticker": mt,
                    "event_ticker": nm["event_ticker"],
                    "series_ticker": nm["series_ticker"],
                    "observed_at": obs_at,
                    "close_time": nm["close_time"],
                    "seconds_to_close": sec_close,
                    "yes_bid_best_cents": book_summary.get("yes_bid_best_cents"),
                    "no_bid_best_cents": book_summary.get("no_bid_best_cents"),
                    "implied_no_ask_best_cents": book_summary.get("implied_no_ask_best_cents"),
                    "no_spread_cents": book_summary.get("no_spread_cents"),
                    "contracts_requested": contracts_requested,
                    "contracts_filled": sim.contracts_filled,
                    "simulated_avg_no_fill_cents": avg_fill,
                    "simulated_worst_no_fill_cents": sim.worst_no_fill_cents,
                    "target_price_cents": bucket_price,
                    "entry_tolerance_cents": config.entry_tolerance_cents,
                    "slippage_cents": slip,
                    "visible_fillable_contracts": sim.visible_fillable_contracts,
                    "fill_quality": sim.fill_quality,
                    "gross_cost_cents": gross_cost,
                    "fee_cents": fee_cents,
                    "net_cost_cents": net_cost,
                    "raw_debug_json": dbg,
                    "scored": False,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }

                if not config.dry_run:
                    ins = insert_shadow_bucket_entry(session, entry_payload)
                    if ins is None:
                        bump_rejection(DUPLICATE_BUCKET_ENTRY)
                        continue
                    counts["entries_inserted"] += 1

                entries_inserted_total += 1
                if not config.dry_run:
                    entries_by_bucket[str(bucket_price)] = entries_by_bucket.get(str(bucket_price), 0) + 1

                if not config.dry_run:
                    if bucket_price not in entered_buckets:
                        entered_buckets.append(bucket_price)
                    update_shadow_bucket_market_observation(
                        session,
                        ob_row,
                        {
                            "ever_entered_any_bucket": True,
                            "entered_buckets_json": entered_buckets,
                            "last_rejection_reason": None,
                            "updated_at": datetime.now(timezone.utc),
                        },
                    )

            session.commit()

        finished = datetime.now(timezone.utc)
        summary_template.update(
            {
                "markets_seen": counts["markets_seen"],
                "orderbooks_attempted": counts["orderbooks_attempted"],
                "orderbooks_successful": counts["orderbooks_successful"],
                "orderbooks_failed": counts["orderbooks_failed"],
                "entries_inserted": counts["entries_inserted"],
                "entries_by_bucket": dict(entries_by_bucket),
                "fill_failures": counts["fill_failures"],
                "top_rejection_reasons": dict(rejection_reasons.most_common(50)),
                "finished_at": finished.isoformat(),
            }
        )
        finish_shadow_bucket_scan_run(
            session,
            scan_run_id,
            "dry_run" if config.dry_run else "success",
            summary_json=dict(summary_template),
            counts=counts,
        )
        session.commit()
        return dict(summary_template)

    except Exception as exc:
        finished = datetime.now(timezone.utc)
        err_payload = {"error_type": type(exc).__name__, "message": safe_error_message(exc)}
        summary_template["finished_at"] = finished.isoformat()
        finish_shadow_bucket_scan_run(
            session,
            scan_run_id,
            "failed",
            summary_json=dict(summary_template),
            error_json=err_payload,
            counts=counts,
        )
        session.commit()
        raise


__all__ = [
    "ACTIVE_MARKET_STATUSES",
    "AVG_FILL_OUTSIDE_BUCKET",
    "DUPLICATE_BUCKET_ENTRY",
    "EMPTY_BOOK",
    "FULL_FILL",
    "INSUFFICIENT_DEPTH",
    "INSUFFICIENT_DEPTH_REJ",
    "INVALID_STAKE_OR_BUCKET",
    "MALFORMED_BOOK",
    "MARKET_MALFORMED",
    "MAX_ENTRIES_REACHED",
    "ORDERBOOK_EMPTY",
    "ORDERBOOK_FETCH_FAILED",
    "PARTIAL_FILL",
    "SECONDS_TO_CLOSE_TOO_HIGH",
    "SECONDS_TO_CLOSE_TOO_LOW",
    "FillSimulation",
    "bucket_for_fill",
    "buckets_for_fill",
    "compute_fee_adjusted_break_even_win_rate",
    "compute_seconds_to_close",
    "estimate_kalshi_taker_fee_cents",
    "extract_orderbook_levels",
    "normalize_market_for_shadow",
    "run_bucket_shadow_scan_persisted",
    "simulate_buy_no_fill_from_yes_bids",
    "summarize_book_for_no_entry",
    "validate_bucket_windows",
]
