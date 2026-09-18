"""Drop users.theme_preference and organizers.theme_preference (ADR 0003):
the resolved theme is now device-driven with a browser-local, expiring
override — there is no durable account-level theme to store.

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("users", "theme_preference")
    op.drop_column("organizers", "theme_preference")


def downgrade() -> None:
    op.add_column(
        "organizers", sa.Column("theme_preference", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "users", sa.Column("theme_preference", sa.String(length=10), nullable=True)
    )
