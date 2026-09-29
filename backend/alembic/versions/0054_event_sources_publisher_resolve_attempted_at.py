"""event_sources.publisher_resolve_attempted_at: cooldown for the live Fienta
organizer re-query in backfill_publisher_ids (Big-O audit M8). A listing the
crawl could not resolve is skipped until PUBLISHER_RESOLVE_RETRY_COOLDOWN
passes, instead of being re-crawled every 6h run.

Revision ID: 0054
Revises: 0053
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "event_sources",
        sa.Column(
            "publisher_resolve_attempted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("event_sources", "publisher_resolve_attempted_at")
