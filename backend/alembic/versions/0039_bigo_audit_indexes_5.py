"""Fifth Big-O audit pass: organizer_image_uploads had only a single-column
organizer_id index though its daily-cap count query (and this table's total
lack of a retention sweep) filters on (organizer_id, created_at); raw_events
had no index covering (source_id, external_id), so admin.py's event-inspector
RawEvent<->EventSource join scanned the source's whole raw history; events had
no index at all backing is_explicit/is_non_event (public_event_filter, on
every public read path) or has_free_tier (browse.py's free-filter OR-arm);
daily_feeds.event_ids had no GIN index, so admin.py's event-inspector
`event_ids @> [id]` check scanned every active user's feed row.

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-17
"""

from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

_PUBLIC_EVENT_WHERE = "status = 'published' AND NOT is_explicit AND NOT is_non_event"


def upgrade() -> None:
    op.drop_index(
        "ix_organizer_image_uploads_organizer_id",
        table_name="organizer_image_uploads",
    )
    op.create_index(
        "ix_organizer_image_uploads_organizer_created",
        "organizer_image_uploads",
        ["organizer_id", "created_at"],
    )

    op.create_index(
        "ix_raw_events_source_external", "raw_events", ["source_id", "external_id"]
    )

    op.execute(
        "CREATE INDEX ix_events_public_starts_at ON events (starts_at) "
        f"WHERE {_PUBLIC_EVENT_WHERE}"
    )
    op.execute(
        "CREATE INDEX ix_events_has_free_tier ON events (has_free_tier) "
        "WHERE has_free_tier"
    )

    op.create_index(
        "ix_daily_feeds_event_ids_gin",
        "daily_feeds",
        ["event_ids"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_daily_feeds_event_ids_gin", table_name="daily_feeds")
    op.execute("DROP INDEX IF EXISTS ix_events_has_free_tier")
    op.execute("DROP INDEX IF EXISTS ix_events_public_starts_at")
    op.drop_index("ix_raw_events_source_external", table_name="raw_events")
    op.drop_index(
        "ix_organizer_image_uploads_organizer_created",
        table_name="organizer_image_uploads",
    )
    op.create_index(
        "ix_organizer_image_uploads_organizer_id",
        "organizer_image_uploads",
        ["organizer_id"],
    )
