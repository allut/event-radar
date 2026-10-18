"""Restriction clearance on promotions (#612).

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
    op.add_column("promotions", sa.Column("restriction_cleared", sa.String(length=16), nullable=True))
    op.add_column("promotions", sa.Column("restriction_clearance_by", sa.String(length=16), nullable=True))
    op.add_column("promotions", sa.Column("restriction_clearance_note", sa.Text(), nullable=True))
    op.add_column(
        "promotions",
        sa.Column("restriction_cleared_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    for col in (
        "restriction_cleared_at",
        "restriction_clearance_note",
        "restriction_clearance_by",
        "restriction_cleared",
    ):
        op.drop_column("promotions", col)
