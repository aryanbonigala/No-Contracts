"""Add research_market_labels and extend research_feature_rows with label fields (v0.8).

Revision ID: 0004_market_outcome_labels
Revises: 0003_backtest_runs
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_market_outcome_labels"
down_revision = "0003_backtest_runs"
branch_labels = None
depends_on = None


def json_type() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )


def upgrade() -> None:
    op.create_table(
        "research_market_labels",
        sa.Column("market_ticker", sa.String(length=512), nullable=False),
        sa.Column("label_version", sa.String(length=64), nullable=False),
        sa.Column("label_market_result", sa.String(length=16), nullable=False),
        sa.Column("label_no_won", sa.Boolean(), nullable=True),
        sa.Column("label_yes_won", sa.Boolean(), nullable=True),
        sa.Column("label_is_resolved", sa.Boolean(), nullable=False),
        sa.Column("label_is_void", sa.Boolean(), nullable=False),
        sa.Column("label_confidence", sa.String(length=16), nullable=False),
        sa.Column("label_source_field", sa.String(length=64), nullable=True),
        sa.Column("label_source_value", sa.Text(), nullable=True),
        sa.Column("label_reason", sa.Text(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_json", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["market_ticker"],
            ["raw_markets.market_ticker"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("market_ticker", "label_version"),
    )
    op.create_index(
        "ix_research_market_labels_version",
        "research_market_labels",
        ["label_version"],
        unique=False,
    )
    op.add_column("research_feature_rows", sa.Column("label_no_won", sa.Boolean(), nullable=True))
    op.add_column("research_feature_rows", sa.Column("label_yes_won", sa.Boolean(), nullable=True))
    op.add_column("research_feature_rows", sa.Column("label_is_resolved", sa.Boolean(), nullable=True))
    op.add_column("research_feature_rows", sa.Column("label_is_void", sa.Boolean(), nullable=True))
    op.add_column("research_feature_rows", sa.Column("label_confidence", sa.String(length=16), nullable=True))
    op.add_column(
        "research_feature_rows",
        sa.Column("outcome_label_version", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_research_feature_rows_outcome_label_version",
        "research_feature_rows",
        ["outcome_label_version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_research_feature_rows_outcome_label_version", table_name="research_feature_rows")
    op.drop_column("research_feature_rows", "outcome_label_version")
    op.drop_column("research_feature_rows", "label_confidence")
    op.drop_column("research_feature_rows", "label_is_void")
    op.drop_column("research_feature_rows", "label_is_resolved")
    op.drop_column("research_feature_rows", "label_yes_won")
    op.drop_column("research_feature_rows", "label_no_won")
    op.drop_index("ix_research_market_labels_version", table_name="research_market_labels")
    op.drop_table("research_market_labels")
