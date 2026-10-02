"""Big-O audit indexes: event_sources.publisher_id (H2), claims Series-status
and status/created (M7), admin_actions (action, target, created_at) for the
revoked-claim tombstone lookup, and venues (organizer_id, created_at) for the
daily-cap count — replacing the bare ix_venues_organizer_id it supersedes.
All plain index creates/drops; fully reversible.

Revision ID: 0049
Revises: 0048
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_event_sources_publisher_id",
        "event_sources",
        ["publisher_id", "id"],
        postgresql_include=["event_id"],
    )
    op.create_index(
        "ix_claims_series_status",
        "claims",
        ["event_series_key", "status"],
        postgresql_where=sa.text("event_series_key IS NOT NULL"),
    )
    op.create_index("ix_claims_status_created", "claims", ["status", "created_at"])
    op.create_index(
        "ix_admin_actions_action_target",
        "admin_actions",
        ["action", "target", "created_at"],
    )
    op.create_index(
        "ix_venues_organizer_created", "venues", ["organizer_id", "created_at"]
    )
    op.drop_index("ix_venues_organizer_id", table_name="venues")


def downgrade() -> None:
    op.create_index("ix_venues_organizer_id", "venues", ["organizer_id"])
    op.drop_index("ix_venues_organizer_created", table_name="venues")
    op.drop_index("ix_admin_actions_action_target", table_name="admin_actions")
    op.drop_index("ix_claims_status_created", table_name="claims")
    op.drop_index("ix_claims_series_status", table_name="claims")
    op.drop_index("ix_event_sources_publisher_id", table_name="event_sources")
