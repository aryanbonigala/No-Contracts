"""Idempotent persistence helpers for collectors (no HTTP)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from sqlalchemy import Select, case, delete, func, select
from sqlalchemy.orm import Session

from kalshi_no_carry.db.schema import (
    ApiFetchLog,
    BacktestRun,
    BacktestTrade,
    EventCluster,
    RawEvent,
    RawMarket,
    RawOrderbookSnapshot,
    ResearchFeatureRow,
    ResearchMarketLabel,
    StrategySplit,
)
from kalshi_no_carry.kalshi_client import derive_executable_prices_from_orderbook
from kalshi_no_carry.research.feature_dataset import JoinedFeatureSource


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


def list_raw_events_for_clustering(session: Session) -> list[dict[str, Any]]:
    """Return raw event rows as plain dicts for deterministic clustering (read-only)."""
    rows = session.scalars(select(RawEvent).order_by(RawEvent.event_ticker)).all()
    return [
        {
            "event_ticker": r.event_ticker,
            "ticker": r.event_ticker,
            "series_ticker": r.series_ticker,
            "title": r.title,
            "category": r.category,
            "close_time": None,
            "expiration_time": None,
            "settlement_time": None,
            "raw_json": r.raw_json,
            "fetched_at": r.fetched_at,
        }
        for r in rows
    ]


def list_raw_markets_for_clustering(session: Session) -> list[dict[str, Any]]:
    """Return raw market rows as plain dicts for deterministic clustering (read-only)."""
    rows = session.scalars(select(RawMarket).order_by(RawMarket.market_ticker)).all()
    return [
        {
            "market_ticker": r.market_ticker,
            "ticker": r.market_ticker,
            "event_ticker": r.event_ticker,
            "series_ticker": r.series_ticker,
            "title": r.title,
            "subtitle": r.subtitle,
            "category": r.category,
            "close_time": r.close_time,
            "expiration_time": r.expiration_time,
            "settlement_time": r.settlement_time,
            "raw_json": r.raw_json,
            "fetched_at": r.fetched_at,
        }
        for r in rows
    ]


def list_event_clusters(session: Session) -> list[EventCluster]:
    """
    List ``event_clusters`` rows sorted for chronological splits:

    ``(close_time ascending, NULLs last), cluster_id``.
    """
    from datetime import datetime, timezone

    rows = session.scalars(select(EventCluster)).all()
    far_future = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    def _key_sort(ec: EventCluster) -> tuple[object, str]:
        ct = ec.close_time
        if ct is None:
            return (far_future, ec.cluster_id)
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        return (ct, ec.cluster_id)

    return sorted(rows, key=_key_sort)


def list_orderbook_snapshots_for_feature_building(
    session: Session,
    *,
    split_version: str,
    include_splits: Sequence[str] = ("train", "validation"),
    include_test: bool = False,
    market_tickers: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[JoinedFeatureSource]:
    """
    Join orderbook snapshots to markets, clusters, and split rows for feature building.

    **Join rule:** ``raw_markets.event_ticker == event_clusters.event_ticker`` (inner).
    Markets with NULL ``event_ticker`` are omitted. For orphan/fallback clusters with
    no matching ``event_ticker``, use cluster rebuild tooling; this query does not
    reconstruct ``cluster_key`` fallbacks.

    Ordering: ``split_name`` (train, validation, test), ``cluster_id``, ``market_ticker``,
    ``fetched_at``, ``snapshot_id``.
    """
    sv = (split_version or "").strip()
    if not sv:
        raise ValueError("split_version is required")

    allowed: set[str] = set()
    for s in include_splits:
        t = str(s).strip()
        if t:
            allowed.add(t)
    if not include_test:
        allowed.discard("test")
    for name in allowed:
        if name not in ("train", "validation", "test"):
            raise ValueError(f"invalid split name: {name!r}")
    if not allowed:
        return []

    split_order = case(
        (StrategySplit.split_name == "train", 1),
        (StrategySplit.split_name == "validation", 2),
        (StrategySplit.split_name == "test", 3),
        else_=9,
    )
    stmt = (
        select(RawOrderbookSnapshot, RawMarket, EventCluster, StrategySplit, RawEvent.title)
        .join(RawMarket, RawOrderbookSnapshot.market_ticker == RawMarket.market_ticker)
        .join(EventCluster, EventCluster.event_ticker == RawMarket.event_ticker)
        .join(
            StrategySplit,
            (StrategySplit.cluster_id == EventCluster.cluster_id)
            & (StrategySplit.split_version == sv),
        )
        .outerjoin(RawEvent, RawEvent.event_ticker == RawMarket.event_ticker)
        .where(StrategySplit.split_name.in_(tuple(sorted(allowed))))
        .order_by(
            split_order,
            EventCluster.cluster_id,
            RawOrderbookSnapshot.market_ticker,
            RawOrderbookSnapshot.fetched_at,
            RawOrderbookSnapshot.id,
        )
    )
    if market_tickers:
        mt = [str(m).strip() for m in market_tickers if m and str(m).strip()]
        if mt:
            stmt = stmt.where(RawOrderbookSnapshot.market_ticker.in_(mt))
    if limit is not None:
        stmt = stmt.limit(int(limit))

    out: list[JoinedFeatureSource] = []
    for row in session.execute(stmt).all():
        ob, rm, ec, sp, ev_title = row[0], row[1], row[2], row[3], row[4]
        out.append(
            JoinedFeatureSource(
                snapshot=ob,
                market=rm,
                cluster=ec,
                split=sp,
                event_title=ev_title,
            )
        )
    return out


def upsert_research_feature_row(session: Session, row: ResearchFeatureRow) -> ResearchFeatureRow:
    return session.merge(row)


def bulk_upsert_research_feature_rows(session: Session, rows: Sequence[ResearchFeatureRow]) -> int:
    n = 0
    for r in rows:
        session.merge(r)
        n += 1
    return n


def delete_research_feature_rows_for_version(
    session: Session, *, split_version: str, feature_version: str
) -> int:
    res = session.execute(
        delete(ResearchFeatureRow).where(
            ResearchFeatureRow.split_version == split_version.strip(),
            ResearchFeatureRow.feature_version == feature_version.strip(),
        )
    )
    return int(res.rowcount or 0)


def count_research_feature_rows(
    session: Session,
    *,
    split_version: str | None = None,
    feature_version: str | None = None,
) -> int:
    stmt = select(func.count()).select_from(ResearchFeatureRow)
    if split_version is not None:
        stmt = stmt.where(ResearchFeatureRow.split_version == split_version.strip())
    if feature_version is not None:
        stmt = stmt.where(ResearchFeatureRow.feature_version == feature_version.strip())
    return int(session.scalar(stmt) or 0)


def research_feature_row_as_dict(row: ResearchFeatureRow) -> dict[str, Any]:
    """ORM row → plain dict (all columns) for deterministic backtests / export."""
    return {c.key: getattr(row, c.key) for c in ResearchFeatureRow.__table__.columns}


def list_raw_markets_for_labeling(
    session: Session,
    *,
    market_tickers: Sequence[str] | None = None,
    statuses: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[RawMarket]:
    """Deterministic read of ``raw_markets`` for outcome labeling."""
    stmt = select(RawMarket).order_by(RawMarket.market_ticker)
    if market_tickers:
        mt = [str(m).strip() for m in market_tickers if m and str(m).strip()]
        if mt:
            stmt = stmt.where(RawMarket.market_ticker.in_(mt))
    if statuses:
        st = [str(s).strip() for s in statuses if s and str(s).strip()]
        if st:
            stmt = stmt.where(RawMarket.status.in_(st))
    if limit is not None:
        stmt = stmt.limit(int(limit))
    return list(session.scalars(stmt).all())


def upsert_market_outcome_label(session: Session, row: ResearchMarketLabel) -> ResearchMarketLabel:
    return session.merge(row)


def bulk_upsert_market_outcome_labels(session: Session, rows: Sequence[ResearchMarketLabel]) -> int:
    n = 0
    for r in rows:
        session.merge(r)
        n += 1
    return n


def delete_market_outcome_labels_for_version(session: Session, *, label_version: str) -> int:
    res = session.execute(
        delete(ResearchMarketLabel).where(ResearchMarketLabel.label_version == (label_version or "").strip())
    )
    return int(res.rowcount or 0)


def count_market_outcome_labels(session: Session, *, label_version: str | None = None) -> int:
    stmt = select(func.count()).select_from(ResearchMarketLabel)
    if label_version is not None:
        stmt = stmt.where(ResearchMarketLabel.label_version == label_version.strip())
    return int(session.scalar(stmt) or 0)


def list_market_outcome_labels(
    session: Session,
    *,
    label_version: str | None = None,
    limit: int | None = None,
) -> list[ResearchMarketLabel]:
    stmt = select(ResearchMarketLabel).order_by(ResearchMarketLabel.market_ticker)
    if label_version is not None:
        stmt = stmt.where(ResearchMarketLabel.label_version == label_version.strip())
    if limit is not None:
        stmt = stmt.limit(int(limit))
    return list(session.scalars(stmt).all())


def load_market_outcome_labels_by_ticker(
    session: Session,
    *,
    label_version: str,
    market_tickers: Sequence[str] | None = None,
) -> dict[str, ResearchMarketLabel]:
    lv = (label_version or "").strip()
    if not lv:
        return {}
    stmt = select(ResearchMarketLabel).where(ResearchMarketLabel.label_version == lv)
    if market_tickers is not None:
        mt = sorted({str(m).strip() for m in market_tickers if m and str(m).strip()})
        if mt:
            stmt = stmt.where(ResearchMarketLabel.market_ticker.in_(mt))
    return {r.market_ticker: r for r in session.scalars(stmt).all()}


def list_feature_rows_for_backtest(
    session: Session,
    *,
    split_version: str,
    feature_version: str,
    include_splits: Sequence[str] = ("train", "validation"),
    include_test: bool = False,
    limit: int | None = None,
    market_tickers: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Load ``research_feature_rows`` for read-only backtesting.

    Ordering: ``split_name`` (train, validation, test), ``cluster_id``, ``market_ticker``,
    ``fetched_at``, ``snapshot_id``. Test split is omitted from the SQL filter unless
    ``include_test=True`` (even if the caller lists ``test`` in ``include_splits``).
    """
    sv = (split_version or "").strip()
    fv = (feature_version or "").strip()
    if not sv or not fv:
        raise ValueError("split_version and feature_version are required")

    allowed: set[str] = set()
    for s in include_splits:
        t = str(s).strip()
        if t:
            allowed.add(t)
    if not include_test:
        allowed.discard("test")
    for name in allowed:
        if name not in ("train", "validation", "test"):
            raise ValueError(f"invalid split name: {name!r}")
    if not allowed:
        return []

    split_order = case(
        (ResearchFeatureRow.split_name == "train", 1),
        (ResearchFeatureRow.split_name == "validation", 2),
        (ResearchFeatureRow.split_name == "test", 3),
        else_=9,
    )
    stmt = (
        select(ResearchFeatureRow)
        .where(
            ResearchFeatureRow.split_version == sv,
            ResearchFeatureRow.feature_version == fv,
            ResearchFeatureRow.split_name.in_(tuple(sorted(allowed))),
        )
        .order_by(
            split_order,
            ResearchFeatureRow.cluster_id,
            ResearchFeatureRow.market_ticker,
            ResearchFeatureRow.fetched_at,
            ResearchFeatureRow.snapshot_id,
        )
    )
    if market_tickers:
        mt = [str(m).strip() for m in market_tickers if m and str(m).strip()]
        if mt:
            stmt = stmt.where(ResearchFeatureRow.market_ticker.in_(mt))
    if limit is not None:
        stmt = stmt.limit(int(limit))

    rows = list(session.scalars(stmt).all())
    return [research_feature_row_as_dict(r) for r in rows]


def _trade_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def insert_backtest_run(session: Session, run: BacktestRun) -> BacktestRun:
    session.add(run)
    session.flush()
    return run


def insert_backtest_trades(session: Session, run_id: str, trades: Sequence[Mapping[str, Any]]) -> int:
    rid = run_id.strip()
    n = 0
    for i, t in enumerate(trades):
        d = dict(t)
        session.add(
            BacktestTrade(
                run_id=rid,
                trade_index=int(i),
                snapshot_id=_trade_optional_int(d.get("snapshot_id")),
                market_ticker=_maybe_str(d.get("market_ticker")),
                cluster_id=_maybe_str(d.get("cluster_id")),
                split_name=_maybe_str(d.get("split_name")),
                no_ask_cents=_trade_optional_int(d.get("no_ask_cents")),
                fee_cents=_trade_optional_int(d.get("fee_cents")),
                gross_pnl_cents=_trade_optional_int(d.get("gross_pnl_cents")),
                net_pnl_cents=_trade_optional_int(d.get("net_pnl_cents")),
                scored=bool(d.get("scored")),
                unscored_reason=_maybe_str(d.get("unscored_reason")),
                raw_json=d,
            )
        )
        n += 1
    return n


def get_backtest_run(session: Session, run_id: str) -> BacktestRun | None:
    return session.get(BacktestRun, (run_id or "").strip())


def list_backtest_runs(session: Session, *, limit: int = 200) -> list[BacktestRun]:
    stmt = select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(int(limit))
    return list(session.scalars(stmt).all())


def delete_backtest_run(session: Session, run_id: str) -> bool:
    rid = (run_id or "").strip()
    row = session.get(BacktestRun, rid)
    if row is None:
        return False
    # Explicit child delete for SQLite sessions without FK CASCADE enforcement.
    session.execute(delete(BacktestTrade).where(BacktestTrade.run_id == rid))
    session.delete(row)
    return True


def list_research_feature_rows(
    session: Session,
    *,
    split_version: str | None = None,
    feature_version: str | None = None,
    limit: int | None = None,
) -> list[ResearchFeatureRow]:
    stmt = select(ResearchFeatureRow).order_by(
        ResearchFeatureRow.split_name,
        ResearchFeatureRow.cluster_id,
        ResearchFeatureRow.market_ticker,
        ResearchFeatureRow.fetched_at,
        ResearchFeatureRow.snapshot_id,
    )
    if split_version is not None:
        stmt = stmt.where(ResearchFeatureRow.split_version == split_version.strip())
    if feature_version is not None:
        stmt = stmt.where(ResearchFeatureRow.feature_version == feature_version.strip())
    if limit is not None:
        stmt = stmt.limit(int(limit))
    return list(session.scalars(stmt).all())


def get_existing_strategy_splits(
    session: Session, *, split_version: str | None = None
) -> list[StrategySplit]:
    stmt = select(StrategySplit).order_by(StrategySplit.cluster_id, StrategySplit.split_version)
    if split_version is not None:
        stmt = stmt.where(StrategySplit.split_version == split_version)
    return list(session.scalars(stmt).all())


def count_strategy_splits(session: Session, *, split_version: str | None = None) -> int:
    stmt = select(func.count()).select_from(StrategySplit)
    if split_version is not None:
        stmt = stmt.where(StrategySplit.split_version == split_version)
    return int(session.scalar(stmt) or 0)


def delete_strategy_splits_for_version(session: Session, split_version: str) -> int:
    """Delete all ``strategy_splits`` rows for *split_version*; returns deleted row count."""
    res = session.execute(delete(StrategySplit).where(StrategySplit.split_version == split_version))
    return int(res.rowcount or 0)


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
    sv = (split_version or "").strip()
    if not sv:
        raise ValueError("split_version must be non-empty")
    now = assigned_at or _utcnow()
    stmt = select(StrategySplit).where(
        StrategySplit.cluster_id == cid,
        StrategySplit.split_version == sv,
    )
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is None:
        row = StrategySplit(
            cluster_id=cid,
            split_version=sv,
            split_name=split_name,
            assigned_at=now,
            notes=notes,
        )
        session.add(row)
        return row
    existing.split_name = split_name
    existing.assigned_at = now
    existing.notes = notes
    session.add(existing)
    return existing


def _maybe_str(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)
