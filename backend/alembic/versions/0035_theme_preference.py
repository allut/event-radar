"""add theme_preference to users and organizers (#249)

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-04

"""

import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("theme_preference", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "organizers",
        sa.Column("theme_preference", sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizers", "theme_preference")
    op.drop_column("users", "theme_preference")
