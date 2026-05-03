"""Add research_feature_rows (v0.6 feature engineering dataset).

Revision ID: 0002_feature_rows
Revises: 0001_initial_schema

Frozen explicit DDL. JSON summary column uses JSON/JSONB variant like 0001.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_feature_rows"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def json_type() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )


def upgrade() -> None:
    op.create_table(
        "research_feature_rows",
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("split_version", sa.String(length=64), nullable=False),
        sa.Column("feature_version", sa.String(length=64), nullable=False),
        sa.Column("market_ticker", sa.String(length=512), nullable=False),
        sa.Column("event_ticker", sa.String(length=256), nullable=True),
        sa.Column("cluster_id", sa.String(length=256), nullable=False),
        sa.Column("split_name", sa.String(length=32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("market_title", sa.Text(), nullable=True),
        sa.Column("event_title", sa.Text(), nullable=True),
        sa.Column("representative_title", sa.Text(), nullable=True),
        sa.Column("series_ticker", sa.String(length=256), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("market_status", sa.String(length=64), nullable=True),
        sa.Column("market_close_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("market_expiration_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("market_settlement_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("best_yes_bid_cents", sa.Integer(), nullable=True),
        sa.Column("best_yes_ask_cents", sa.Integer(), nullable=True),
        sa.Column("best_no_bid_cents", sa.Integer(), nullable=True),
        sa.Column("best_no_ask_cents", sa.Integer(), nullable=True),
        sa.Column("yes_bid_size", sa.Integer(), nullable=True),
        sa.Column("yes_ask_size", sa.Integer(), nullable=True),
        sa.Column("no_bid_size", sa.Integer(), nullable=True),
        sa.Column("no_ask_size", sa.Integer(), nullable=True),
        sa.Column("yes_mid_cents", sa.Integer(), nullable=True),
        sa.Column("no_mid_cents", sa.Integer(), nullable=True),
        sa.Column("yes_spread_cents", sa.Integer(), nullable=True),
        sa.Column("no_spread_cents", sa.Integer(), nullable=True),
        sa.Column("yes_market_crossed_or_locked", sa.Boolean(), nullable=True),
        sa.Column("no_market_crossed_or_locked", sa.Boolean(), nullable=True),
        sa.Column("seconds_to_close", sa.Float(), nullable=True),
        sa.Column("minutes_to_close", sa.Float(), nullable=True),
        sa.Column("hours_to_close", sa.Float(), nullable=True),
        sa.Column("days_to_close", sa.Float(), nullable=True),
        sa.Column("snapshot_hour_utc", sa.Integer(), nullable=True),
        sa.Column("snapshot_day_of_week_utc", sa.Integer(), nullable=True),
        sa.Column("is_near_close_1h", sa.Boolean(), nullable=False),
        sa.Column("is_near_close_6h", sa.Boolean(), nullable=False),
        sa.Column("is_near_close_24h", sa.Boolean(), nullable=False),
        sa.Column("no_ask_cents", sa.Integer(), nullable=True),
        sa.Column("no_bid_cents", sa.Integer(), nullable=True),
        sa.Column("no_cost_cents", sa.Integer(), nullable=True),
        sa.Column("no_payout_cents", sa.Integer(), nullable=False),
        sa.Column("gross_no_profit_if_correct_cents", sa.Integer(), nullable=True),
        sa.Column("gross_no_loss_if_wrong_cents", sa.Integer(), nullable=True),
        sa.Column("required_no_probability_before_fees", sa.Float(), nullable=True),
        sa.Column("estimated_taker_fee_cents", sa.Integer(), nullable=True),
        sa.Column("required_no_probability_after_fees", sa.Float(), nullable=True),
        sa.Column("no_edge_placeholder", sa.Float(), nullable=True),
        sa.Column("has_complete_executable_prices", sa.Boolean(), nullable=False),
        sa.Column("missing_price_reason", sa.Text(), nullable=True),
        sa.Column("raw_orderbook_depth_summary", json_type(), nullable=True),
        sa.Column("label_market_result", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["raw_orderbook_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("snapshot_id", "split_version", "feature_version"),
    )
    op.create_index(
        "ix_research_feature_rows_market_ticker",
        "research_feature_rows",
        ["market_ticker"],
        unique=False,
    )
    op.create_index(
        "ix_research_feature_rows_event_ticker",
        "research_feature_rows",
        ["event_ticker"],
        unique=False,
    )
    op.create_index(
        "ix_research_feature_rows_cluster_id",
        "research_feature_rows",
        ["cluster_id"],
        unique=False,
    )
    op.create_index(
        "ix_research_feature_rows_fetched_at",
        "research_feature_rows",
        ["fetched_at"],
        unique=False,
    )
    op.create_index(
        "ix_research_feature_rows_split_feature",
        "research_feature_rows",
        ["split_version", "feature_version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_research_feature_rows_split_feature", table_name="research_feature_rows")
    op.drop_index("ix_research_feature_rows_fetched_at", table_name="research_feature_rows")
    op.drop_index("ix_research_feature_rows_cluster_id", table_name="research_feature_rows")
    op.drop_index("ix_research_feature_rows_event_ticker", table_name="research_feature_rows")
    op.drop_index("ix_research_feature_rows_market_ticker", table_name="research_feature_rows")
    op.drop_table("research_feature_rows")
