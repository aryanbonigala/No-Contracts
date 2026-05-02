"""Frozen initial schema (v0.5.4).

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-02

This revision is **explicit frozen DDL** (``op.create_table`` / ``op.drop_table``).
It captures the schema as of Kalshi NO Carry v0.5.4 so revision ``0001`` always
materializes the same physical tables even if ORM models change later.

JSON columns use ``sa.JSON().with_variant(postgresql.JSONB(...), "postgresql")``,
matching ``kalshi_no_carry.db.schema`` (JSON on SQLite, JSONB on Postgres).

``strategy_splits`` uses a composite primary key on ``(cluster_id, split_version)``
and a foreign key to ``event_clusters.cluster_id`` with ``ON DELETE CASCADE``.

Downgrade drops tables in dependency-safe order (children before parents).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def json_type() -> sa.types.TypeEngine:
    """Portable JSON: SQLite ``JSON``; PostgreSQL ``JSONB`` (matches ORM ``_JSON``)."""
    return sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )


def upgrade() -> None:
    op.create_table(
        "api_fetch_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("params_json", json_type(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_fetch_log_fetched_at", "api_fetch_log", ["fetched_at"], unique=False)

    op.create_table(
        "raw_events",
        sa.Column("event_ticker", sa.String(length=256), nullable=False),
        sa.Column("series_ticker", sa.String(length=256), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("raw_json", json_type(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_ticker"),
    )
    op.create_index("ix_raw_events_series_ticker", "raw_events", ["series_ticker"], unique=False)
    op.create_index("ix_raw_events_status", "raw_events", ["status"], unique=False)
    op.create_index("ix_raw_events_fetched_at", "raw_events", ["fetched_at"], unique=False)

    op.create_table(
        "raw_markets",
        sa.Column("market_ticker", sa.String(length=512), nullable=False),
        sa.Column("event_ticker", sa.String(length=256), nullable=True),
        sa.Column("series_ticker", sa.String(length=256), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("subtitle", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiration_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settlement_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=True),
        sa.Column("yes_bid_cents", sa.Integer(), nullable=True),
        sa.Column("yes_ask_cents", sa.Integer(), nullable=True),
        sa.Column("no_bid_cents", sa.Integer(), nullable=True),
        sa.Column("no_ask_cents", sa.Integer(), nullable=True),
        sa.Column("last_price_cents", sa.Integer(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("open_interest", sa.Integer(), nullable=True),
        sa.Column("raw_json", json_type(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("market_ticker"),
    )
    op.create_index("ix_raw_markets_event_ticker", "raw_markets", ["event_ticker"], unique=False)
    op.create_index("ix_raw_markets_series_ticker", "raw_markets", ["series_ticker"], unique=False)
    op.create_index("ix_raw_markets_status", "raw_markets", ["status"], unique=False)
    op.create_index("ix_raw_markets_open_time", "raw_markets", ["open_time"], unique=False)
    op.create_index("ix_raw_markets_close_time", "raw_markets", ["close_time"], unique=False)
    op.create_index(
        "ix_raw_markets_expiration_time",
        "raw_markets",
        ["expiration_time"],
        unique=False,
    )
    op.create_index(
        "ix_raw_markets_settlement_time",
        "raw_markets",
        ["settlement_time"],
        unique=False,
    )
    op.create_index("ix_raw_markets_result", "raw_markets", ["result"], unique=False)
    op.create_index("ix_raw_markets_fetched_at", "raw_markets", ["fetched_at"], unique=False)

    op.create_table(
        "raw_orderbook_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("market_ticker", sa.String(length=512), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("best_yes_bid_cents", sa.Integer(), nullable=True),
        sa.Column("best_yes_bid_size", sa.Integer(), nullable=True),
        sa.Column("best_no_bid_cents", sa.Integer(), nullable=True),
        sa.Column("best_no_bid_size", sa.Integer(), nullable=True),
        sa.Column("best_yes_ask_cents", sa.Integer(), nullable=True),
        sa.Column("best_yes_ask_size", sa.Integer(), nullable=True),
        sa.Column("best_no_ask_cents", sa.Integer(), nullable=True),
        sa.Column("best_no_ask_size", sa.Integer(), nullable=True),
        sa.Column("raw_json", json_type(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_raw_orderbook_market_fetched",
        "raw_orderbook_snapshots",
        ["market_ticker", "fetched_at"],
        unique=False,
    )
    op.create_index(
        "ix_raw_orderbook_snapshots_market_ticker",
        "raw_orderbook_snapshots",
        ["market_ticker"],
        unique=False,
    )
    op.create_index(
        "ix_raw_orderbook_snapshots_fetched_at",
        "raw_orderbook_snapshots",
        ["fetched_at"],
        unique=False,
    )

    op.create_table(
        "event_clusters",
        sa.Column("cluster_id", sa.String(length=256), nullable=False),
        sa.Column("cluster_key", sa.String(length=256), nullable=True),
        sa.Column("event_ticker", sa.String(length=256), nullable=True),
        sa.Column("series_ticker", sa.String(length=256), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("representative_title", sa.Text(), nullable=True),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_json", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("cluster_id"),
    )
    op.create_index("ix_event_clusters_cluster_key", "event_clusters", ["cluster_key"], unique=False)
    op.create_index("ix_event_clusters_event_ticker", "event_clusters", ["event_ticker"], unique=False)
    op.create_index("ix_event_clusters_series_ticker", "event_clusters", ["series_ticker"], unique=False)
    op.create_index("ix_event_clusters_close_time", "event_clusters", ["close_time"], unique=False)

    op.create_table(
        "strategy_splits",
        sa.Column("cluster_id", sa.String(length=256), nullable=False),
        sa.Column("split_version", sa.String(length=64), nullable=False),
        sa.Column("split_name", sa.String(length=32), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["cluster_id"],
            ["event_clusters.cluster_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("cluster_id", "split_version"),
    )
    op.create_index("ix_strategy_splits_split_name", "strategy_splits", ["split_name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_strategy_splits_split_name", table_name="strategy_splits")
    op.drop_table("strategy_splits")

    op.drop_index("ix_event_clusters_close_time", table_name="event_clusters")
    op.drop_index("ix_event_clusters_series_ticker", table_name="event_clusters")
    op.drop_index("ix_event_clusters_event_ticker", table_name="event_clusters")
    op.drop_index("ix_event_clusters_cluster_key", table_name="event_clusters")
    op.drop_table("event_clusters")

    op.drop_index("ix_raw_orderbook_snapshots_fetched_at", table_name="raw_orderbook_snapshots")
    op.drop_index("ix_raw_orderbook_snapshots_market_ticker", table_name="raw_orderbook_snapshots")
    op.drop_index("ix_raw_orderbook_market_fetched", table_name="raw_orderbook_snapshots")
    op.drop_table("raw_orderbook_snapshots")

    op.drop_index("ix_raw_markets_fetched_at", table_name="raw_markets")
    op.drop_index("ix_raw_markets_result", table_name="raw_markets")
    op.drop_index("ix_raw_markets_settlement_time", table_name="raw_markets")
    op.drop_index("ix_raw_markets_expiration_time", table_name="raw_markets")
    op.drop_index("ix_raw_markets_close_time", table_name="raw_markets")
    op.drop_index("ix_raw_markets_open_time", table_name="raw_markets")
    op.drop_index("ix_raw_markets_status", table_name="raw_markets")
    op.drop_index("ix_raw_markets_series_ticker", table_name="raw_markets")
    op.drop_index("ix_raw_markets_event_ticker", table_name="raw_markets")
    op.drop_table("raw_markets")

    op.drop_index("ix_raw_events_fetched_at", table_name="raw_events")
    op.drop_index("ix_raw_events_status", table_name="raw_events")
    op.drop_index("ix_raw_events_series_ticker", table_name="raw_events")
    op.drop_table("raw_events")

    op.drop_index("ix_api_fetch_log_fetched_at", table_name="api_fetch_log")
    op.drop_table("api_fetch_log")