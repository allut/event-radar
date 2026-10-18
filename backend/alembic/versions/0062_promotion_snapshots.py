"""Promotion content snapshots (#601): what a Promotion displayed, append-only.

Revision ID: 0062
Revises: 0061
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promotion_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "promotion_id",
            sa.BigInteger(),
            sa.ForeignKey("promotions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("title_et", sa.Text(), nullable=True),
        sa.Column("title_en", sa.Text(), nullable=True),
        sa.Column("title_ru", sa.Text(), nullable=True),
        sa.Column("description_excerpt", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("venue_name", sa.Text(), nullable=True),
        sa.Column("event_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("net_price_cents", sa.Integer(), nullable=False),
        sa.Column("vat_rate_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("label_text", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_promotion_snapshots_promotion_id", "promotion_snapshots", ["promotion_id"]
    )


def downgrade() -> None:
    op.drop_table("promotion_snapshots")
