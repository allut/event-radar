"""Organizer accounts + magic-link auth, and events.submitted_by_organizer_id /
events.needs_review for direct organizer event submission (Phase 1 backend core).

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import CITEXT

from app._generated.shared_constants import DEFAULT_USER_LOCALE

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("email", CITEXT(), nullable=False, unique=True),
        sa.Column(
            "locale", sa.String(2), nullable=False, server_default=DEFAULT_USER_LOCALE
        ),
        sa.Column(
            "session_token_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "organizer_magic_links",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "organizer_id",
            sa.BigInteger(),
            sa.ForeignKey("organizers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_organizer_magic_links_organizer_id",
        "organizer_magic_links",
        ["organizer_id"],
    )

    op.add_column(
        "events",
        sa.Column(
            "submitted_by_organizer_id",
            sa.BigInteger(),
            sa.ForeignKey("organizers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "events",
        sa.Column(
            "needs_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_events_submitted_by_organizer_id",
        "events",
        ["submitted_by_organizer_id"],
    )
    op.execute(
        "CREATE INDEX ix_events_needs_review ON events (needs_review) "
        "WHERE needs_review"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_events_needs_review")
    op.drop_index("ix_events_submitted_by_organizer_id", table_name="events")
    op.drop_column("events", "needs_review")
    op.drop_column("events", "submitted_by_organizer_id")
    op.drop_index(
        "ix_organizer_magic_links_organizer_id", table_name="organizer_magic_links"
    )
    op.drop_table("organizer_magic_links")
    op.drop_table("organizers")
