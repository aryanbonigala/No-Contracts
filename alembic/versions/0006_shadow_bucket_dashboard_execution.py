"""v0.18 shadow dashboard: execution probe rows + richer entry diagnostics.

Revision ID: 0006_shadow_bucket_dashboard_execution
Revises: 0005_shadow_bucket_experiment
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_shadow_bucket_dashboard_execution"
down_revision = "0005_shadow_bucket_experiment"
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )


def upgrade() -> None:
    op.add_column(
        "shadow_bucket_entries",
        sa.Column("contracts_unfilled", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "shadow_bucket_entries",
        sa.Column("eligible_depth_contracts", sa.Integer(), nullable=True),
    )
    op.add_column(
        "shadow_bucket_entries",
        sa.Column("best_no_fill_cents", sa.Integer(), nullable=True),
    )
    op.add_column(
        "shadow_bucket_entries",
        sa.Column(
            "execution_notes_json",
            json_type(),
            nullable=True,
        ),
    )
    op.create_table(
        "shadow_bucket_execution_probes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scan_run_id", sa.String(length=64), nullable=False),
        sa.Column("shadow_version", sa.String(length=128), nullable=False),
        sa.Column("experiment_name", sa.String(length=128), nullable=False),
        sa.Column("market_ticker", sa.String(length=512), nullable=False),
        sa.Column("bucket_price_cents", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seconds_to_close", sa.Integer(), nullable=True),
        sa.Column("event_ticker", sa.String(length=256), nullable=True),
        sa.Column("series_ticker", sa.String(length=256), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("contracts_requested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contracts_filled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contracts_unfilled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("eligible_depth_contracts", sa.Integer(), nullable=True),
        sa.Column("avg_no_fill_cents", sa.Float(), nullable=True),
        sa.Column("best_no_fill_cents", sa.Integer(), nullable=True),
        sa.Column("worst_no_fill_cents", sa.Integer(), nullable=True),
        sa.Column("target_price_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("entry_tolerance_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("slippage_cents", sa.Float(), nullable=True),
        sa.Column("fill_quality", sa.String(length=32), nullable=False),
        sa.Column("gross_cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fee_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skip_failure_reason", sa.String(length=128), nullable=True),
        sa.Column("linked_entry_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["scan_run_id"],
            ["shadow_bucket_scan_runs.scan_run_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["linked_entry_id"],
            ["shadow_bucket_entries.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scan_run_id",
            "market_ticker",
            "bucket_price_cents",
            name="uq_shadow_bucket_probes_scan_market_bucket",
        ),
    )
    op.create_index(
        "ix_shadow_bucket_probes_shadow_version",
        "shadow_bucket_execution_probes",
        ["shadow_version"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_probes_experiment_name",
        "shadow_bucket_execution_probes",
        ["experiment_name"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_probes_bucket",
        "shadow_bucket_execution_probes",
        ["bucket_price_cents"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_bucket_probes_scan_bucket",
        "shadow_bucket_execution_probes",
        ["scan_run_id", "bucket_price_cents"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_shadow_bucket_probes_scan_bucket", table_name="shadow_bucket_execution_probes")
    op.drop_index("ix_shadow_bucket_probes_bucket", table_name="shadow_bucket_execution_probes")
    op.drop_index("ix_shadow_bucket_probes_experiment_name", table_name="shadow_bucket_execution_probes")
    op.drop_index("ix_shadow_bucket_probes_shadow_version", table_name="shadow_bucket_execution_probes")
    op.drop_table("shadow_bucket_execution_probes")
    op.drop_column("shadow_bucket_entries", "execution_notes_json")
    op.drop_column("shadow_bucket_entries", "best_no_fill_cents")
    op.drop_column("shadow_bucket_entries", "eligible_depth_contracts")
    op.drop_column("shadow_bucket_entries", "contracts_unfilled")
