"""Add title_localized and description_localized JSONB columns to events.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("title_localized", JSONB, nullable=True))
    op.add_column("events", sa.Column("description_localized", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("events", "description_localized")
    op.drop_column("events", "title_localized")
