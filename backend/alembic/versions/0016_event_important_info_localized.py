"""Add important_info_localized JSONB column to events.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("important_info_localized", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("events", "important_info_localized")
