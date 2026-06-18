"""Add events.is_out_of_area for location-based exclusion from the publish gate.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "is_out_of_area",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "is_out_of_area")
