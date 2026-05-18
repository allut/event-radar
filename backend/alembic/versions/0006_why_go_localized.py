"""Add why_go_localized JSONB column to event_classifications.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "event_classifications",
        sa.Column("why_go_localized", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("event_classifications", "why_go_localized")
