"""SQLAlchemy 2.0 ORM models — Postgres in production, SQLite in tests."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
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


class ResearchFeatureRow(Base):
    """
    Engineered research row: one orderbook snapshot joined to market, cluster, split.

    Primary key ``(snapshot_id, split_version, feature_version)`` allows multiple
    feature pipelines and split policies to coexist.
    """

    __tablename__ = "research_feature_rows"
    __table_args__ = (Index("ix_research_feature_rows_split_feature", "split_version", "feature_version"),)

    snapshot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("raw_orderbook_snapshots.id", ondelete="CASCADE"),
        primary_key=True,
    )
    split_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    feature_version: Mapped[str] = mapped_column(String(64), primary_key=True)

    market_ticker: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    event_ticker: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    cluster_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    split_name: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    market_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    representative_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    series_ticker: Mapped[str | None] = mapped_column(String(256), nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    market_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    market_close_time: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    market_expiration_time: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    market_settlement_time: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)

    best_yes_bid_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_yes_ask_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_no_bid_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_no_ask_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yes_bid_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yes_ask_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    no_bid_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    no_ask_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    yes_mid_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    no_mid_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yes_spread_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    no_spread_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yes_market_crossed_or_locked: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    no_market_crossed_or_locked: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    seconds_to_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    minutes_to_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    hours_to_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    days_to_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    snapshot_hour_utc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_day_of_week_utc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_near_close_1h: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_near_close_6h: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_near_close_24h: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    no_ask_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    no_bid_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    no_cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    no_payout_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    gross_no_profit_if_correct_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gross_no_loss_if_wrong_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    required_no_probability_before_fees: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_taker_fee_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    required_no_probability_after_fees: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_edge_placeholder: Mapped[float | None] = mapped_column(Float, nullable=True)

    has_complete_executable_prices: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    missing_price_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_orderbook_depth_summary: Mapped[dict | None] = mapped_column(_JSON, nullable=True)

    label_market_result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    label_no_won: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    label_yes_won: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    label_is_resolved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    label_is_void: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    label_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    outcome_label_version: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class ResearchMarketLabel(Base):
    """
    Versioned deterministic outcome label per ``market_ticker`` (from raw market payloads).

    Composite PK ``(market_ticker, label_version)`` allows multiple extraction policies to coexist.
    """

    __tablename__ = "research_market_labels"
    __table_args__ = (Index("ix_research_market_labels_version", "label_version"),)

    market_ticker: Mapped[str] = mapped_column(
        String(512),
        ForeignKey("raw_markets.market_ticker", ondelete="CASCADE"),
        primary_key=True,
    )
    label_version: Mapped[str] = mapped_column(String(64), primary_key=True)

    label_market_result: Mapped[str] = mapped_column(String(16), nullable=False)
    label_no_won: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    label_yes_won: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    label_is_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    label_is_void: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    label_confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    label_source_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label_source_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    label_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_json: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class BacktestRun(Base):
    """Persisted metadata + summary for one read-only backtest run (v0.7+)."""

    __tablename__ = "backtest_runs"
    __table_args__ = (
        Index("ix_backtest_runs_created_at", "created_at"),
        Index("ix_backtest_runs_versions", "split_version", "feature_version", "backtest_version"),
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    backtest_version: Mapped[str] = mapped_column(String(128), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    split_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    config_json: Mapped[dict] = mapped_column(_JSON, nullable=False)
    summary_json: Mapped[dict] = mapped_column(_JSON, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    test_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BacktestTrade(Base):
    """Per-trade rows for a backtest run (hypothetical entries; not live orders)."""

    __tablename__ = "backtest_trades"
    __table_args__ = (Index("ix_backtest_trades_run_id", "run_id"),)

    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    trade_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    market_ticker: Mapped[str | None] = mapped_column(String(512), nullable=True)
    cluster_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    split_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    no_ask_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fee_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gross_pnl_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    net_pnl_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scored: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unscored_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[dict] = mapped_column(_JSON, nullable=False)


class ShadowBucketScanRun(Base):
    """One persisted shadow bucket scan execution (v0.17a)."""

    __tablename__ = "shadow_bucket_scan_runs"
    __table_args__ = (
        Index("ix_shadow_bucket_scan_runs_shadow_version", "shadow_version"),
        Index("ix_shadow_bucket_scan_runs_experiment_name", "experiment_name"),
        Index("ix_shadow_bucket_scan_runs_version_started_at", "shadow_version", "started_at"),
        Index("ix_shadow_bucket_scan_runs_status", "status"),
    )

    scan_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    shadow_version: Mapped[str] = mapped_column(String(128), nullable=False)
    experiment_name: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    markets_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orderbooks_attempted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orderbooks_successful: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orderbooks_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entries_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejections_recorded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fill_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_json: Mapped[dict | list | None] = mapped_column(_JSON, nullable=True)
    error_json: Mapped[dict | list | None] = mapped_column(_JSON, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class ShadowBucketEntry(Base):
    """Simulated NO bucket fill held to resolution (paper only)."""

    __tablename__ = "shadow_bucket_entries"
    __table_args__ = (
        UniqueConstraint(
            "shadow_version",
            "experiment_name",
            "market_ticker",
            "bucket_price_cents",
            name="uq_shadow_bucket_entries_version_experiment_market_bucket",
        ),
        Index("ix_shadow_bucket_entries_shadow_version", "shadow_version"),
        Index("ix_shadow_bucket_entries_experiment_name", "experiment_name"),
        Index("ix_shadow_bucket_entries_scan_run_id", "scan_run_id"),
        Index("ix_shadow_bucket_entries_bucket_price_cents", "bucket_price_cents"),
        Index("ix_shadow_bucket_entries_bucket_name", "bucket_name"),
        Index("ix_shadow_bucket_entries_market_ticker", "market_ticker"),
        Index("ix_shadow_bucket_entries_observed_at", "observed_at"),
        Index("ix_shadow_bucket_entries_version_bucket", "shadow_version", "bucket_price_cents"),
        Index("ix_shadow_bucket_entries_version_market", "shadow_version", "market_ticker"),
        Index("ix_shadow_bucket_entries_version_scored", "shadow_version", "scored"),
        Index("ix_shadow_bucket_entries_bucket_scored", "bucket_price_cents", "scored"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shadow_version: Mapped[str] = mapped_column(String(128), nullable=False)
    experiment_name: Mapped[str] = mapped_column(String(128), nullable=False)
    scan_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bucket_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    bucket_name: Mapped[str] = mapped_column(String(32), nullable=False)
    market_ticker: Mapped[str] = mapped_column(String(512), nullable=False)
    event_ticker: Mapped[str | None] = mapped_column(String(256), nullable=True)
    series_ticker: Mapped[str | None] = mapped_column(String(256), nullable=True)
    observed_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    close_time: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    seconds_to_close: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yes_bid_best_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    no_bid_best_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    implied_no_ask_best_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    no_spread_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contracts_requested: Mapped[int] = mapped_column(Integer, nullable=False)
    contracts_filled: Mapped[int] = mapped_column(Integer, nullable=False)
    simulated_avg_no_fill_cents: Mapped[float] = mapped_column(Float, nullable=False)
    simulated_worst_no_fill_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_tolerance_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    slippage_cents: Mapped[float | None] = mapped_column(Float, nullable=True)
    visible_fillable_contracts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fill_quality: Mapped[str] = mapped_column(String(32), nullable=False)
    gross_cost_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    fee_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    net_cost_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    settlement_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    settlement_result: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gross_pnl_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    net_pnl_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fee_drag_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unscored_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_debug_json: Mapped[dict | list | None] = mapped_column(_JSON, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class ShadowBucketMarketObservation(Base):
    """Compact per-market shadow scan denominator (no full orderbook storage)."""

    __tablename__ = "shadow_bucket_market_observations"
    __table_args__ = (
        UniqueConstraint(
            "shadow_version",
            "experiment_name",
            "market_ticker",
            name="uq_shadow_bucket_market_observations_version_experiment_market",
        ),
        Index("ix_shadow_bucket_market_obs_shadow_version", "shadow_version"),
        Index("ix_shadow_bucket_market_obs_experiment_name", "experiment_name"),
        Index("ix_shadow_bucket_market_obs_market_ticker", "market_ticker"),
        Index(
            "ix_shadow_bucket_market_obs_version_entered",
            "shadow_version",
            "ever_entered_any_bucket",
        ),
        Index("ix_shadow_bucket_market_obs_series", "series_ticker"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shadow_version: Mapped[str] = mapped_column(String(128), nullable=False)
    experiment_name: Mapped[str] = mapped_column(String(128), nullable=False)
    market_ticker: Mapped[str] = mapped_column(String(512), nullable=False)
    event_ticker: Mapped[str | None] = mapped_column(String(256), nullable=True)
    series_ticker: Mapped[str | None] = mapped_column(String(256), nullable=True)
    first_seen_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    times_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orderbooks_attempted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orderbooks_successful: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orderbooks_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_observed_no_ask_cents: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_observed_no_bid_cents: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_observed_spread_cents: Mapped[float | None] = mapped_column(Float, nullable=True)
    ever_entered_any_bucket: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    entered_buckets_json: Mapped[dict | list | None] = mapped_column(_JSON, nullable=True)
    closest_bucket_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    closest_bucket_distance_cents: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_rejection_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    settlement_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    settlement_result: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
