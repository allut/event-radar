"""Third Big-O audit pass: event_reports had no event_id index at all (five
open-report/admin-inspector queries seq-scanned the never-pruned table), the
two magic-link tables' expires_at columns were unindexed (weekly cleanup
DELETEs seq-scan), and raw_events' source_id + fetched_at were two separate
single-column indexes doing a bitmap-AND where ingest_skip_ids wants a
composite.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-27
"""

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_event_reports_open_event ON event_reports (event_id) "
        "WHERE status = 'open'"
    )
    op.create_index(
        "ix_event_reports_event_created", "event_reports", ["event_id", "created_at"]
    )

    op.create_index("ix_auth_magic_links_expires_at", "auth_magic_links", ["expires_at"])
    op.create_index(
        "ix_organizer_magic_links_expires_at", "organizer_magic_links", ["expires_at"]
    )

    op.drop_index("ix_raw_events_source_id", table_name="raw_events")
    op.create_index(
        "ix_raw_events_source_fetched", "raw_events", ["source_id", "fetched_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_raw_events_source_fetched", table_name="raw_events")
    op.create_index("ix_raw_events_source_id", "raw_events", ["source_id"])

    op.drop_index(
        "ix_organizer_magic_links_expires_at", table_name="organizer_magic_links"
    )
    op.drop_index("ix_auth_magic_links_expires_at", table_name="auth_magic_links")

    op.drop_index("ix_event_reports_event_created", table_name="event_reports")
    op.execute("DROP INDEX IF EXISTS ix_event_reports_open_event")
