"""Add backtest_runs and backtest_trades (v0.7 read-only harness output).

Revision ID: 0003_backtest_runs
Revises: 0002_feature_rows

Frozen explicit DDL. JSON columns use JSON/JSONB variant like 0001/0002.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_backtest_runs"
down_revision = "0002_feature_rows"
branch_labels = None
depends_on = None


def json_type() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("backtest_version", sa.String(length=128), nullable=False),
        sa.Column("strategy_name", sa.String(length=128), nullable=False),
        sa.Column("split_version", sa.String(length=64), nullable=False),
        sa.Column("feature_version", sa.String(length=64), nullable=False),
        sa.Column("config_json", json_type(), nullable=False),
        sa.Column("summary_json", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_included", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "ix_backtest_runs_created_at",
        "backtest_runs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_backtest_runs_versions",
        "backtest_runs",
        ["split_version", "feature_version", "backtest_version"],
        unique=False,
    )
    op.create_table(
        "backtest_trades",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("trade_index", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=True),
        sa.Column("market_ticker", sa.String(length=512), nullable=True),
        sa.Column("cluster_id", sa.String(length=256), nullable=True),
        sa.Column("split_name", sa.String(length=32), nullable=True),
        sa.Column("no_ask_cents", sa.Integer(), nullable=True),
        sa.Column("fee_cents", sa.Integer(), nullable=True),
        sa.Column("gross_pnl_cents", sa.Integer(), nullable=True),
        sa.Column("net_pnl_cents", sa.Integer(), nullable=True),
        sa.Column("scored", sa.Boolean(), nullable=False),
        sa.Column("unscored_reason", sa.Text(), nullable=True),
        sa.Column("raw_json", json_type(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["backtest_runs.run_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "trade_index"),
    )
    op.create_index(
        "ix_backtest_trades_run_id",
        "backtest_trades",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_trades_run_id", table_name="backtest_trades")
    op.drop_table("backtest_trades")
    op.drop_index("ix_backtest_runs_versions", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_created_at", table_name="backtest_runs")
    op.drop_table("backtest_runs")
