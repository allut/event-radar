"""Add missing indexes: events.status, raw_events.source_id

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-05

"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_events_status", "events", ["status"])
    op.create_index("ix_raw_events_source_id", "raw_events", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_events_status", table_name="events")
    op.drop_index("ix_raw_events_source_id", table_name="raw_events")
