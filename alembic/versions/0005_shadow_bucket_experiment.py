"""Add shadow bucket scan tables (v0.17a read-only shadow experiment).

Revision ID: 0005_shadow_bucket_experiment
Revises: 0004_market_outcome_labels
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_shadow_bucket_experiment"
down_revision = "0004_market_outcome_labels"
branch_labels = None
depends_on = None


def json_type() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )


def upgrade() -> None:
    op.create_table(
        "shadow_bucket_scan_runs",
        sa.Column("scan_run_id", sa.String(length=64), nullable=False),
        sa.Column("shadow_version", sa.String(length=128), nullable=False),
        sa.Column("experiment_name", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("markets_seen", sa.Integer(), nullable=False),
        sa.Column("orderbooks_attempted", sa.Integer(), nullable=False),
        sa.Column("orderbooks_successful", sa.Integer(), nullable=False),
        sa.Column("orderbooks_failed", sa.Integer(), nullable=False),
        sa.Column("entries_inserted", sa.Integer(), nullable=False),
        sa.Column("rejections_recorded", sa.Integer(), nullable=False),
        sa.Column("fill_failures", sa.Integer(), nullable=False),
        sa.Column("summary_json", json_type(), nullable=True),
        sa.Column("error_json", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scan_run_id"),
    )
    op.create_index(
        "ix_shadow_bucket_scan_runs_shadow_version",
        "shadow_bucket_scan_runs",
        ["shadow_version"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_scan_runs_experiment_name",
        "shadow_bucket_scan_runs",
        ["experiment_name"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_scan_runs_version_started_at",
        "shadow_bucket_scan_runs",
        ["shadow_version", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_scan_runs_status",
        "shadow_bucket_scan_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_scan_runs_started_at",
        "shadow_bucket_scan_runs",
        ["started_at"],
        unique=False,
    )

    op.create_table(
        "shadow_bucket_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("shadow_version", sa.String(length=128), nullable=False),
        sa.Column("experiment_name", sa.String(length=128), nullable=False),
        sa.Column("scan_run_id", sa.String(length=64), nullable=True),
        sa.Column("bucket_price_cents", sa.Integer(), nullable=False),
        sa.Column("bucket_name", sa.String(length=32), nullable=False),
        sa.Column("market_ticker", sa.String(length=512), nullable=False),
        sa.Column("event_ticker", sa.String(length=256), nullable=True),
        sa.Column("series_ticker", sa.String(length=256), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seconds_to_close", sa.Integer(), nullable=True),
        sa.Column("yes_bid_best_cents", sa.Integer(), nullable=True),
        sa.Column("no_bid_best_cents", sa.Integer(), nullable=True),
        sa.Column("implied_no_ask_best_cents", sa.Integer(), nullable=True),
        sa.Column("no_spread_cents", sa.Integer(), nullable=True),
        sa.Column("contracts_requested", sa.Integer(), nullable=False),
        sa.Column("contracts_filled", sa.Integer(), nullable=False),
        sa.Column("simulated_avg_no_fill_cents", sa.Float(), nullable=False),
        sa.Column("simulated_worst_no_fill_cents", sa.Integer(), nullable=True),
        sa.Column("target_price_cents", sa.Integer(), nullable=False),
        sa.Column("entry_tolerance_cents", sa.Integer(), nullable=False),
        sa.Column("slippage_cents", sa.Float(), nullable=True),
        sa.Column("visible_fillable_contracts", sa.Integer(), nullable=True),
        sa.Column("fill_quality", sa.String(length=32), nullable=False),
        sa.Column("gross_cost_cents", sa.Integer(), nullable=False),
        sa.Column("fee_cents", sa.Integer(), nullable=False),
        sa.Column("net_cost_cents", sa.Integer(), nullable=False),
        sa.Column("settlement_status", sa.String(length=64), nullable=True),
        sa.Column("settlement_result", sa.String(length=64), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scored", sa.Boolean(), nullable=False),
        sa.Column("gross_pnl_cents", sa.Integer(), nullable=True),
        sa.Column("net_pnl_cents", sa.Integer(), nullable=True),
        sa.Column("fee_drag_cents", sa.Integer(), nullable=True),
        sa.Column("result_category", sa.String(length=64), nullable=True),
        sa.Column("unscored_reason", sa.String(length=64), nullable=True),
        sa.Column("raw_debug_json", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "shadow_version",
            "experiment_name",
            "market_ticker",
            "bucket_price_cents",
            name="uq_shadow_bucket_entries_version_experiment_market_bucket",
        ),
    )
    op.create_index(
        "ix_shadow_bucket_entries_shadow_version",
        "shadow_bucket_entries",
        ["shadow_version"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_entries_experiment_name",
        "shadow_bucket_entries",
        ["experiment_name"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_entries_scan_run_id",
        "shadow_bucket_entries",
        ["scan_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_entries_bucket_price_cents",
        "shadow_bucket_entries",
        ["bucket_price_cents"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_entries_bucket_name",
        "shadow_bucket_entries",
        ["bucket_name"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_entries_market_ticker",
        "shadow_bucket_entries",
        ["market_ticker"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_entries_observed_at",
        "shadow_bucket_entries",
        ["observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_entries_version_bucket",
        "shadow_bucket_entries",
        ["shadow_version", "bucket_price_cents"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_entries_version_market",
        "shadow_bucket_entries",
        ["shadow_version", "market_ticker"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_entries_version_scored",
        "shadow_bucket_entries",
        ["shadow_version", "scored"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_entries_bucket_scored",
        "shadow_bucket_entries",
        ["bucket_price_cents", "scored"],
        unique=False,
    )

    op.create_table(
        "shadow_bucket_market_observations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("shadow_version", sa.String(length=128), nullable=False),
        sa.Column("experiment_name", sa.String(length=128), nullable=False),
        sa.Column("market_ticker", sa.String(length=512), nullable=False),
        sa.Column("event_ticker", sa.String(length=256), nullable=True),
        sa.Column("series_ticker", sa.String(length=256), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("times_scanned", sa.Integer(), nullable=False),
        sa.Column("orderbooks_attempted", sa.Integer(), nullable=False),
        sa.Column("orderbooks_successful", sa.Integer(), nullable=False),
        sa.Column("orderbooks_failed", sa.Integer(), nullable=False),
        sa.Column("min_observed_no_ask_cents", sa.Float(), nullable=True),
        sa.Column("max_observed_no_bid_cents", sa.Float(), nullable=True),
        sa.Column("min_observed_spread_cents", sa.Float(), nullable=True),
        sa.Column("ever_entered_any_bucket", sa.Boolean(), nullable=False),
        sa.Column("entered_buckets_json", json_type(), nullable=True),
        sa.Column("closest_bucket_price_cents", sa.Integer(), nullable=True),
        sa.Column("closest_bucket_distance_cents", sa.Float(), nullable=True),
        sa.Column("last_rejection_reason", sa.String(length=64), nullable=True),
        sa.Column("settlement_status", sa.String(length=64), nullable=True),
        sa.Column("settlement_result", sa.String(length=64), nullable=True),
        sa.Column("scored", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "shadow_version",
            "experiment_name",
            "market_ticker",
            name="uq_shadow_bucket_market_observations_version_experiment_market",
        ),
    )
    op.create_index(
        "ix_shadow_bucket_market_obs_shadow_version",
        "shadow_bucket_market_observations",
        ["shadow_version"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_market_obs_experiment_name",
        "shadow_bucket_market_observations",
        ["experiment_name"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_market_obs_market_ticker",
        "shadow_bucket_market_observations",
        ["market_ticker"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_market_obs_version_entered",
        "shadow_bucket_market_observations",
        ["shadow_version", "ever_entered_any_bucket"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_market_obs_series",
        "shadow_bucket_market_observations",
        ["series_ticker"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shadow_bucket_market_obs_series",
        table_name="shadow_bucket_market_observations",
    )
    op.drop_index(
        "ix_shadow_bucket_market_obs_version_entered",
        table_name="shadow_bucket_market_observations",
    )
    op.drop_index(
        "ix_shadow_bucket_market_obs_market_ticker",
        table_name="shadow_bucket_market_observations",
    )
    op.drop_index(
        "ix_shadow_bucket_market_obs_experiment_name",
        table_name="shadow_bucket_market_observations",
    )
    op.drop_index(
        "ix_shadow_bucket_market_obs_shadow_version",
        table_name="shadow_bucket_market_observations",
    )
    op.drop_table("shadow_bucket_market_observations")

    op.drop_index("ix_shadow_bucket_entries_bucket_scored", table_name="shadow_bucket_entries")
    op.drop_index("ix_shadow_bucket_entries_version_scored", table_name="shadow_bucket_entries")
    op.drop_index("ix_shadow_bucket_entries_version_market", table_name="shadow_bucket_entries")
    op.drop_index("ix_shadow_bucket_entries_version_bucket", table_name="shadow_bucket_entries")
    op.drop_index("ix_shadow_bucket_entries_observed_at", table_name="shadow_bucket_entries")
    op.drop_index("ix_shadow_bucket_entries_market_ticker", table_name="shadow_bucket_entries")
    op.drop_index("ix_shadow_bucket_entries_bucket_name", table_name="shadow_bucket_entries")
    op.drop_index("ix_shadow_bucket_entries_bucket_price_cents", table_name="shadow_bucket_entries")
    op.drop_index("ix_shadow_bucket_entries_scan_run_id", table_name="shadow_bucket_entries")
    op.drop_index("ix_shadow_bucket_entries_experiment_name", table_name="shadow_bucket_entries")
    op.drop_index("ix_shadow_bucket_entries_shadow_version", table_name="shadow_bucket_entries")
    op.drop_table("shadow_bucket_entries")

    op.drop_index("ix_shadow_bucket_scan_runs_started_at", table_name="shadow_bucket_scan_runs")
    op.drop_index("ix_shadow_bucket_scan_runs_status", table_name="shadow_bucket_scan_runs")
    op.drop_index(
        "ix_shadow_bucket_scan_runs_version_started_at",
        table_name="shadow_bucket_scan_runs",
    )
    op.drop_index(
        "ix_shadow_bucket_scan_runs_experiment_name",
        table_name="shadow_bucket_scan_runs",
    )
    op.drop_index(
        "ix_shadow_bucket_scan_runs_shadow_version",
        table_name="shadow_bucket_scan_runs",
    )
    op.drop_table("shadow_bucket_scan_runs")
