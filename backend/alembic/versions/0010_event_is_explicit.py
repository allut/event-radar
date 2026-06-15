"""Add events.is_explicit for NSFW / explicit-content exclusion.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "is_explicit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "is_explicit")
