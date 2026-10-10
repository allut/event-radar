"""organizers.email_verified_at: durable "has authenticated" signal so the
weekly cleanup stops deleting real organizers once their (pruned) magic-link
rows vanish (OWASP audit H-2). Existing rows are backfilled as verified:
every pre-existing organizer predates the fix, and the old predicate already
spared recent ones; leaving them NULL would make the first post-deploy sweep
re-run the same bug.

Revision ID: 0057
Revises: 0056
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizers",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE organizers SET email_verified_at = created_at")


def downgrade() -> None:
    op.drop_column("organizers", "email_verified_at")
