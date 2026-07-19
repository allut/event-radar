"""Big-O audit fixes: pg_trgm search indexes, geocode/refetch partial indexes,
vibes GIN index, raw_events/ingestion_runs retention indexes, llm_calls created_at
index, and the ix_events_status schema-drift fix (index already existed via 0002,
just wasn't declared on the model — no DB change needed for that one).

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-19
"""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Explore keyword search (`ILIKE '%q%'`) — a leading wildcard can't use a
    # B-tree; trigram GIN indexes accelerate it.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_events_title_orig_trgm ON events "
        "USING gin (title_orig gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_events_description_orig_trgm ON events "
        "USING gin (description_orig gin_trgm_ops)"
    )

    # Geocode pending query: venue_address IS NOT NULL AND lat IS NULL,
    # ORDER BY geocode_attempted_at NULLS FIRST LIMIT 200.
    op.execute(
        "CREATE INDEX ix_events_geocode_attempted_at ON events "
        "(geocode_attempted_at) WHERE venue_address IS NOT NULL AND lat IS NULL"
    )

    # Refetch candidates: url IS NOT NULL, ORDER BY detail_refetched_at NULLS
    # FIRST LIMIT 1000, daily.
    op.execute(
        "CREATE INDEX ix_events_detail_refetched_at ON events "
        "(detail_refetched_at) WHERE url IS NOT NULL"
    )

    # Explore vibe facet — categories already has a GIN index, vibes did not.
    op.create_index(
        "ix_event_classifications_vibes",
        "event_classifications",
        ["vibes"],
        postgresql_using="gin",
    )

    # Weekly cleanup DELETEs.
    op.create_index("ix_raw_events_fetched_at", "raw_events", ["fetched_at"])
    op.create_index("ix_ingestion_runs_started_at", "ingestion_runs", ["started_at"])

    # Cleanup-by-date: ix_llm_calls_task_created leads with `task`, so a
    # date-only predicate (no task filter) can't range-scan it.
    op.create_index("ix_llm_calls_created_at", "llm_calls", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_created_at", table_name="llm_calls")
    op.drop_index("ix_ingestion_runs_started_at", table_name="ingestion_runs")
    op.drop_index("ix_raw_events_fetched_at", table_name="raw_events")
    op.drop_index(
        "ix_event_classifications_vibes", table_name="event_classifications"
    )
    op.execute("DROP INDEX IF EXISTS ix_events_detail_refetched_at")
    op.execute("DROP INDEX IF EXISTS ix_events_geocode_attempted_at")
    op.execute("DROP INDEX IF EXISTS ix_events_description_orig_trgm")
    op.execute("DROP INDEX IF EXISTS ix_events_title_orig_trgm")
