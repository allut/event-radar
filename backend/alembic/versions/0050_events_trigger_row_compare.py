"""events.updated_at trigger: explicit column ROW compare instead of to_jsonb (M11)

The 0027 trigger serialized both NEW and OLD to jsonb on every row UPDATE just
to compare them. This swaps in a ROW(...) IS DISTINCT FROM ROW(...) compare
over an explicit column list, skipping the two jsonb builds per row. The
excluded sync-bookkeeping columns are unchanged. The list is frozen here and
guarded against model drift by tests/test_events_trigger_columns.py — a new
events column needs a follow-up migration that re-issues this function.

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-29
"""

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None

_TRIGGER_FUNCTION = "trg_events_set_updated_at"

# Every events column except updated_at and the sync-bookkeeping columns
# (detail_refetched_at, detail_refetch_count, geocode_attempted_at).
TRACKED_COLUMNS = (
    "id",
    "slug",
    "title_orig",
    "description_orig",
    "important_info",
    "price_hint",
    "starts_at",
    "ends_at",
    "venue_name",
    "venue_address",
    "venue_id",
    "lat",
    "lng",
    "url",
    "image_url",
    "price_min",
    "price_max",
    "currency",
    "status",
    "is_explicit",
    "is_out_of_area",
    "is_non_event",
    "has_free_tier",
    "title_localized",
    "description_localized",
    "important_info_localized",
    "dedup_group_id",
    "created_at",
    "submitted_by_organizer_id",
    "needs_review",
    "cancellation_reason",
    "pinned_fields",
)


def _row(alias: str) -> str:
    return "ROW(" + ", ".join(f"{alias}.{c}" for c in TRACKED_COLUMNS) + ")"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_TRIGGER_FUNCTION}() RETURNS trigger AS $$
        BEGIN
            IF {_row("NEW")} IS DISTINCT FROM {_row("OLD")} THEN
                NEW.updated_at = now();
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_TRIGGER_FUNCTION}() RETURNS trigger AS $$
        BEGIN
            IF (to_jsonb(NEW) - 'updated_at' - 'detail_refetched_at'
                - 'detail_refetch_count' - 'geocode_attempted_at')
               IS DISTINCT FROM
               (to_jsonb(OLD) - 'updated_at' - 'detail_refetched_at'
                - 'detail_refetch_count' - 'geocode_attempted_at')
            THEN
                NEW.updated_at = now();
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
