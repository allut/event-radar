"""add users.email_verified

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-02

"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "email_verified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    # Backfill: mark every *existing* user verified. We deliberately do NOT try to
    # derive this from auth_magic_links.used_at — cleanup_stale_data() purges
    # auth_magic_links rows once expires_at is > MAGIC_LINK_RETENTION_DAYS (7 days)
    # old, regardless of used_at (app/cleanup.py:64-67), so that history is gone for
    # any user who verified more than a week ago. A blanket backfill grandfathers
    # every pre-migration row (including any already-unverified spam row) — the
    # fix's real target is new signups going forward, and re-deriving "verified"
    # from a purged event log isn't possible without breaking every existing
    # active user's feed/digest.
    op.execute("UPDATE users SET email_verified = true")


def downgrade() -> None:
    op.drop_column("users", "email_verified")
