"""Big-O audit P4/L2: indexes for the publish gate, the Fienta publisher
stamp and the quality sort.

- ix_events_classified_live_until: publish_pending's UPDATE reads only
  'classified' rows that haven't ended. The status index alone walks every
  classified row ever (rejects never leave that status); this partial
  expression index range-scans the live ones.
- ix_event_sources_unstamped: _stamp_missing_fienta_publishers scans event
  sources with no publisher_id for one source. Partial on publisher_id IS
  NULL, so stamped rows (the vast majority) never enter the index.
- ix_event_classifications_quality_score is rebuilt as quality_score DESC
  NULLS LAST, the order every quality sort asks for. A backward scan of the
  ascending index yields NULLS FIRST, so the planner sorted instead.

Revision ID: 0070
Revises: 0069
Create Date: 2026-10-27
"""

from alembic import op

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_events_classified_live_until ON events "
        "(coalesce(ends_at, starts_at)) WHERE status = 'classified'"
    )
    op.execute(
        "CREATE INDEX ix_event_sources_unstamped ON event_sources "
        "(source_id, event_id) WHERE publisher_id IS NULL"
    )
    op.drop_index(
        "ix_event_classifications_quality_score", table_name="event_classifications"
    )
    op.execute(
        "CREATE INDEX ix_event_classifications_quality_score ON event_classifications "
        "(quality_score DESC NULLS LAST)"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_event_classifications_quality_score", table_name="event_classifications"
    )
    op.create_index(
        "ix_event_classifications_quality_score",
        "event_classifications",
        ["quality_score"],
    )
    op.drop_index("ix_event_sources_unstamped", table_name="event_sources")
    op.drop_index("ix_events_classified_live_until", table_name="events")
