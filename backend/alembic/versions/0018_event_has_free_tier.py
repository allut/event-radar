"""Add events.has_free_tier for paid events that also offer free tiers/groups.

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "has_free_tier",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "has_free_tier")
