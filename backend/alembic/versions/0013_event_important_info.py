"""Add events.important_info for Piletilevi's "Important information" detail section.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("important_info", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("events", "important_info")
