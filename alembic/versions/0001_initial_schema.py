"""Initial schema — all ORM tables (v0.5.2 baseline).

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-02

This revision applies ``Base.metadata.create_all()`` so the physical schema stays
aligned with ``kalshi_no_carry.db.schema`` (including ``strategy_splits`` composite
primary key on ``(cluster_id, split_version)``).

Downgrade drops all ORM tables (destructive); it does not remove ``alembic_version``.
"""

from __future__ import annotations

from alembic import op

from kalshi_no_carry.db.schema import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
