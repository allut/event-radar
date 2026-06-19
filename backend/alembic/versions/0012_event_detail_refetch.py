"""Add events.detail_refetched_at / detail_refetch_count for the daily detail-refetch sync.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("detail_refetched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column(
            "detail_refetch_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "detail_refetch_count")
    op.drop_column("events", "detail_refetched_at")
