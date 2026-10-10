"""events.venue_extract_attempted_at: cooldown for the venue-extract geocode
sub-pass. An event whose suspect venue_name the LLM resolved to "no address" is
skipped until VENUE_EXTRACT_RETRY_INTERVAL_DAYS passes, so those rows cannot
fill the per-run window and starve newer candidates (Big-O audit #3).

Bookkeeping column: deliberately absent from the 0050 updated_at trigger's
tracked-column list, like geocode_attempted_at.

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "venue_extract_attempted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "venue_extract_attempted_at")
