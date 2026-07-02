"""Add events.is_non_event for non-event listings (gift cards, merch, webinars).

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "is_non_event",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "is_non_event")
