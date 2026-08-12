"""add organizers.verified

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-03

"""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizers",
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Grandfather organizers an admin already implicitly trusted before this
    # gate existed: one with a published, already-reviewed (needs_review=false)
    # event submitted. Everyone else (including brand-new accounts) starts
    # unverified and goes through the new admin-approve gate in app/publish.py.
    op.execute(
        """
        UPDATE organizers
        SET verified = true
        WHERE id IN (
            SELECT DISTINCT submitted_by_organizer_id
            FROM events
            WHERE submitted_by_organizer_id IS NOT NULL
              AND status = 'published'
              AND needs_review = false
        )
        """
    )


def downgrade() -> None:
    op.drop_column("organizers", "verified")
