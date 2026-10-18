"""Promotion delivery counters (#606): promotion_daily_stats.

One row per Promotion per Tallinn day, unique on (promotion_id, day), never
pruned. Anonymous counts only.

Revision ID: 0061
Revises: 0060
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

_COUNTERS = (
    "explore_served",
    "daily5_placed",
    "digest_sent",
    "web_opens",
    "digest_opens",
    "slot_dislikes",
)


def upgrade() -> None:
    op.create_table(
        "promotion_daily_stats",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "promotion_id",
            sa.BigInteger(),
            sa.ForeignKey("promotions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("gate_outcome", sa.String(length=16), nullable=True),
        sa.Column("gate_reason", sa.String(length=40), nullable=True),
        *[sa.Column(c, sa.Integer(), nullable=False, server_default="0") for c in _COUNTERS],
        sa.UniqueConstraint(
            "promotion_id", "day", name="uq_promotion_daily_stats_promotion_day"
        ),
    )


def downgrade() -> None:
    op.drop_table("promotion_daily_stats")
