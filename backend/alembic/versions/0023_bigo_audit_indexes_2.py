"""Second Big-O audit pass: sargable coalesce(ends_at, starts_at) expression
index (backs event_not_ended_filter and browse.py's date-range filter, on the
largest and forever-growing table in the schema), event_classifications.
quality_score (showcase/browse quality sort/publish gate), events.price_min
(browse.py price sort), user_event_scores.event_id and daily_feeds.feed_date
(both cleanup.py DELETE predicates whose only existing index leads with the
wrong column), and a composite (submitted_by_organizer_id, created_at)
replacing the single-column organizer index (organizer_events.py's daily
submission-cap query and list_own_events both filter/sort on both columns).

ix_raw_events_source_id already exists in the DB (migration 0002) — it was
only missing from the RawEvent ORM declaration (fixed in models.py, no DB
change needed for that one, same as the historical ix_events_status drift).

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-02
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_events_live_until ON events (coalesce(ends_at, starts_at))"
    )
    op.create_index("ix_events_price_min", "events", ["price_min"])
    op.create_index(
        "ix_event_classifications_quality_score",
        "event_classifications",
        ["quality_score"],
    )
    op.create_index("ix_user_event_scores_event_id", "user_event_scores", ["event_id"])
    op.create_index("ix_daily_feeds_feed_date", "daily_feeds", ["feed_date"])

    op.drop_index("ix_events_submitted_by_organizer_id", table_name="events")
    op.create_index(
        "ix_events_organizer_created",
        "events",
        ["submitted_by_organizer_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_events_organizer_created", table_name="events")
    op.create_index(
        "ix_events_submitted_by_organizer_id", "events", ["submitted_by_organizer_id"]
    )

    op.drop_index("ix_daily_feeds_feed_date", table_name="daily_feeds")
    op.drop_index("ix_user_event_scores_event_id", table_name="user_event_scores")
    op.drop_index(
        "ix_event_classifications_quality_score", table_name="event_classifications"
    )
    op.drop_index("ix_events_price_min", table_name="events")
    op.execute("DROP INDEX IF EXISTS ix_events_live_until")
