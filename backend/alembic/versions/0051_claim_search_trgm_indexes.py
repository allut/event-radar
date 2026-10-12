"""Claim-discovery trigram indexes (M9)

GET /organizer/claims/search ORed an indexed title_orig ILIKE with an
unindexed title_localized JSONB-extract ILIKE, so the OR forced a seq scan of
events; /suggestions ILIKEd events.url unindexed. Adds a pg_trgm GIN
expression index over the combined title haystack and one over url. Plain
index creates; fully reversible. pg_trgm itself came with migration 0020.

Revision ID: 0051
Revises: 0050
Create Date: 2026-09-29
"""

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None

# Frozen copy of app.constants.events.EVENT_SEARCH_TEXT_SQL — the query side must
# match textually; tests/test_claim_search_indexes.py guards the drift.
SEARCH_TEXT_SQL = (
    "coalesce(title_orig, '') || ' ' || "
    "coalesce(title_localized ->> 'et', '') || ' ' || "
    "coalesce(title_localized ->> 'en', '') || ' ' || "
    "coalesce(title_localized ->> 'ru', '')"
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_events_search_text_trgm ON events "
        f"USING gin (({SEARCH_TEXT_SQL}) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_events_url_trgm ON events USING gin (url gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_events_url_trgm", table_name="events")
    op.drop_index("ix_events_search_text_trgm", table_name="events")
