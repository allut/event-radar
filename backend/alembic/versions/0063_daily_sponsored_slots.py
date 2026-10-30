"""Daily 5 Sponsored slot store (#607) and Promotion Daily 5 reach.

One row per user per Tallinn day, apart from daily_feeds so no consent-free
path can pick it up. promotions.daily5_reach holds the distinct-user count.

Revision ID: 0063
Revises: 0062
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_sponsored_slots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slot_date", sa.Date(), nullable=False),
        sa.Column(
            "promotion_id",
            sa.BigInteger(),
            sa.ForeignKey("promotions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("is_swap", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "replaced_promotion_id",
            sa.BigInteger(),
            sa.ForeignKey("promotions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("user_id", "slot_date", name="uq_daily_sponsored_slots_user_date"),
    )
    op.create_index("ix_daily_sponsored_slots_slot_date", "daily_sponsored_slots", ["slot_date"])
    op.create_index(
        "ix_daily_sponsored_slots_promotion_id", "daily_sponsored_slots", ["promotion_id"]
    )
    op.add_column("promotions", sa.Column("daily5_reach", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("promotions", "daily5_reach")
    op.drop_index("ix_daily_sponsored_slots_promotion_id", table_name="daily_sponsored_slots")
    op.drop_index("ix_daily_sponsored_slots_slot_date", table_name="daily_sponsored_slots")
    op.drop_table("daily_sponsored_slots")
