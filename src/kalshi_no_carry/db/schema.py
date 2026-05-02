"""SQLAlchemy 2.0 ORM models — Postgres in production, SQLite in tests."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

_JSON = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class ApiFetchLog(Base):
    __tablename__ = "api_fetch_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fetched_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    params_json: Mapped[dict | list | None] = mapped_column(_JSON, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)


class RawEvent(Base):
    __tablename__ = "raw_events"

    event_ticker: Mapped[str] = mapped_column(String(256), primary_key=True)
    series_ticker: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    raw_json: Mapped[dict] = mapped_column(_JSON, nullable=False)
    first_seen_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class RawMarket(Base):
    __tablename__ = "raw_markets"

    market_ticker: Mapped[str] = mapped_column(String(512), primary_key=True)
    event_ticker: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    series_ticker: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    open_time: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    close_time: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    expiration_time: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    settlement_time: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    result: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    yes_bid_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yes_ask_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    no_bid_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    no_ask_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_json: Mapped[dict] = mapped_column(_JSON, nullable=False)
    first_seen_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class RawOrderbookSnapshot(Base):
    __tablename__ = "raw_orderbook_snapshots"
    __table_args__ = (Index("ix_raw_orderbook_market_fetched", "market_ticker", "fetched_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_ticker: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    fetched_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    best_yes_bid_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_yes_bid_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_no_bid_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_no_bid_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_yes_ask_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_yes_ask_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_no_ask_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_no_ask_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_json: Mapped[dict] = mapped_column(_JSON, nullable=False)


class EventCluster(Base):
    __tablename__ = "event_clusters"

    cluster_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    cluster_key: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    event_ticker: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    series_ticker: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    representative_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    close_time: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    raw_json: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class StrategySplit(Base):
    """
    One train/validation/test assignment per (cluster_id, split_version).

    Multiple ``split_version`` labels can coexist for the same cluster; versioning
    is part of the primary key, not a decorative column.
    """

    __tablename__ = "strategy_splits"

    cluster_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("event_clusters.cluster_id", ondelete="CASCADE"), primary_key=True
    )
    split_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    split_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    assigned_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
