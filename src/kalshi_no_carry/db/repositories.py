"""Idempotent persistence helpers for collectors (no HTTP)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from kalshi_no_carry.db.schema import (
    ApiFetchLog,
    EventCluster,
    RawEvent,
    RawMarket,
    RawOrderbookSnapshot,
    StrategySplit,
)
from kalshi_no_carry.kalshi_client import derive_executable_prices_from_orderbook


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


def _dollars_to_cents(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        quanta = (Decimal(str(value)) * Decimal(100)).quantize(Decimal("1"))
        return int(quanta)
    except Exception:
        return None


def _fp_count_to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(Decimal(str(value)).quantize(Decimal("1")))
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return None


def record_api_fetch(
    session: Session,
    *,
    endpoint: str,
    fetched_at: datetime | None = None,
    params_json: dict | list | None = None,
    status_code: int | None = None,
    success: bool,
    error_message: str | None = None,
    row_count: int | None = None,
    source: str | None = None,
) -> ApiFetchLog:
    row = ApiFetchLog(
        fetched_at=fetched_at or _utcnow(),
        endpoint=endpoint,
        params_json=params_json,
        status_code=status_code,
        success=success,
        error_message=error_message,
        row_count=row_count,
        source=source,
    )
    session.add(row)
    return row


def upsert_event(
    session: Session,
    event_json: Mapping[str, Any],
    *,
    fetched_at: datetime | None = None,
) -> RawEvent:
    event_ticker = str(event_json.get("event_ticker") or event_json.get("ticker") or "").strip()
    if not event_ticker:
        raise ValueError("event_json must include event_ticker (or ticker for events)")
    now = fetched_at or _utcnow()
    stmt: Select[tuple[RawEvent]] = select(RawEvent).where(RawEvent.event_ticker == event_ticker)
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is None:
        row = RawEvent(
            event_ticker=event_ticker,
            series_ticker=_maybe_str(event_json.get("series_ticker")),
            title=_maybe_str(event_json.get("title")),
            category=_maybe_str(event_json.get("category")),
            status=_maybe_str(event_json.get("status")),
            raw_json=dict(event_json),
            first_seen_at=now,
            last_seen_at=now,
            fetched_at=now,
        )
        session.add(row)
        return row
    existing.series_ticker = _maybe_str(event_json.get("series_ticker")) or existing.series_ticker
    existing.title = _maybe_str(event_json.get("title")) or existing.title
    existing.category = _maybe_str(event_json.get("category")) or existing.category
    existing.status = _maybe_str(event_json.get("status")) or existing.status
    existing.raw_json = dict(event_json)
    existing.last_seen_at = now
    existing.fetched_at = now
    session.add(existing)
    return existing


def upsert_market(
    session: Session,
    market_json: Mapping[str, Any],
    *,
    fetched_at: datetime | None = None,
) -> RawMarket:
    ticker = str(market_json.get("ticker") or "").strip()
    if not ticker:
        raise ValueError("market_json must include ticker")
    now = fetched_at or _utcnow()
    stmt = select(RawMarket).where(RawMarket.market_ticker == ticker)
    existing = session.execute(stmt).scalar_one_or_none()

    title = _maybe_str(market_json.get("title") or market_json.get("yes_sub_title"))
    subtitle = _maybe_str(market_json.get("subtitle") or market_json.get("no_sub_title"))

    row_values = dict(
        event_ticker=_maybe_str(market_json.get("event_ticker")),
        series_ticker=_maybe_str(market_json.get("series_ticker")),
        title=title,
        subtitle=subtitle,
        category=_maybe_str(market_json.get("category")),
        status=_maybe_str(market_json.get("status")),
        open_time=_parse_iso_dt(market_json.get("open_time")),
        close_time=_parse_iso_dt(market_json.get("close_time")),
        expiration_time=_parse_iso_dt(
            market_json.get("latest_expiration_time") or market_json.get("expiration_time")
        ),
        settlement_time=_parse_iso_dt(market_json.get("settlement_ts")),
        result=_maybe_str(market_json.get("result")),
        yes_bid_cents=_dollars_to_cents(market_json.get("yes_bid_dollars")),
        yes_ask_cents=_dollars_to_cents(market_json.get("yes_ask_dollars")),
        no_bid_cents=_dollars_to_cents(market_json.get("no_bid_dollars")),
        no_ask_cents=_dollars_to_cents(market_json.get("no_ask_dollars")),
        last_price_cents=_dollars_to_cents(market_json.get("last_price_dollars")),
        volume=_fp_count_to_int(market_json.get("volume_fp") or market_json.get("volume")),
        open_interest=_fp_count_to_int(
            market_json.get("open_interest_fp") or market_json.get("open_interest")
        ),
    )

    if existing is None:
        row = RawMarket(
            market_ticker=ticker,
            raw_json=dict(market_json),
            first_seen_at=now,
            last_seen_at=now,
            fetched_at=now,
            **row_values,
        )
        session.add(row)
        return row
    for k, v in row_values.items():
        setattr(existing, k, v)
    existing.raw_json = dict(market_json)
    existing.last_seen_at = now
    existing.fetched_at = now
    session.add(existing)
    return existing


def insert_orderbook_snapshot(
    session: Session,
    market_ticker: str,
    orderbook_json: Mapping[str, Any],
    *,
    fetched_at: datetime | None = None,
    executable_prices: Mapping[str, Any] | None = None,
) -> RawOrderbookSnapshot:
    mt = market_ticker.strip()
    if not mt:
        raise ValueError("market_ticker must be non-empty")
    ex = executable_prices or derive_executable_prices_from_orderbook(dict(orderbook_json))
    now = fetched_at or _utcnow()

    def _sz(key: str) -> int | None:
        v = ex.get(key)
        if v is None:
            return None
        if isinstance(v, int):
            return v
        return _fp_count_to_int(v)

    snap = RawOrderbookSnapshot(
        market_ticker=mt,
        fetched_at=now,
        best_yes_bid_cents=ex.get("best_yes_bid_cents"),
        best_yes_bid_size=_sz("yes_bid_size"),
        best_no_bid_cents=ex.get("best_no_bid_cents"),
        best_no_bid_size=_sz("no_bid_size"),
        best_yes_ask_cents=ex.get("best_yes_ask_cents"),
        best_yes_ask_size=_sz("yes_ask_size"),
        best_no_ask_cents=ex.get("best_no_ask_cents"),
        best_no_ask_size=_sz("no_ask_size"),
        raw_json=dict(orderbook_json),
    )
    session.add(snap)
    return snap


def upsert_event_cluster(
    session: Session,
    *,
    cluster_id: str,
    cluster_key: str | None = None,
    event_ticker: str | None = None,
    series_ticker: str | None = None,
    category: str | None = None,
    representative_title: str | None = None,
    close_time: datetime | None = None,
    raw_json: dict | None = None,
) -> EventCluster:
    cid = cluster_id.strip()
    if not cid:
        raise ValueError("cluster_id must be non-empty")
    now = _utcnow()
    stmt = select(EventCluster).where(EventCluster.cluster_id == cid)
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is None:
        row = EventCluster(
            cluster_id=cid,
            cluster_key=cluster_key,
            event_ticker=event_ticker,
            series_ticker=series_ticker,
            category=category,
            representative_title=representative_title,
            close_time=close_time,
            raw_json=raw_json,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        return row
    existing.cluster_key = cluster_key if cluster_key is not None else existing.cluster_key
    existing.event_ticker = event_ticker if event_ticker is not None else existing.event_ticker
    existing.series_ticker = series_ticker if series_ticker is not None else existing.series_ticker
    existing.category = category if category is not None else existing.category
    existing.representative_title = (
        representative_title
        if representative_title is not None
        else existing.representative_title
    )
    existing.close_time = close_time if close_time is not None else existing.close_time
    existing.raw_json = raw_json if raw_json is not None else existing.raw_json
    existing.updated_at = now
    session.add(existing)
    return existing


def upsert_strategy_split(
    session: Session,
    *,
    cluster_id: str,
    split_name: str,
    split_version: str,
    assigned_at: datetime | None = None,
    notes: str | None = None,
) -> StrategySplit:
    if split_name not in ("train", "validation", "test"):
        raise ValueError("split_name must be one of: train, validation, test")
    cid = cluster_id.strip()
    if not cid:
        raise ValueError("cluster_id must be non-empty")
    now = assigned_at or _utcnow()
    stmt = select(StrategySplit).where(StrategySplit.cluster_id == cid)
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is None:
        row = StrategySplit(
            cluster_id=cid,
            split_name=split_name,
            split_version=split_version,
            assigned_at=now,
            notes=notes,
        )
        session.add(row)
        return row
    existing.split_name = split_name
    existing.split_version = split_version
    existing.assigned_at = now
    existing.notes = notes
    session.add(existing)
    return existing


def _maybe_str(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)
