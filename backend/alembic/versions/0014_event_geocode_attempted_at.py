"""Add events.geocode_attempted_at for the geocode failure cooldown.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("geocode_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("events", "geocode_attempted_at")
