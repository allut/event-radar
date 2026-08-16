"""add events.updated_at, kept current via trigger

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-15

"""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

_TRIGGER_FUNCTION = "trg_events_set_updated_at"
_TRIGGER_NAME = "events_set_updated_at"


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # A trigger, not an ORM/app-level `onupdate=`, so updated_at stays
    # correct no matter which code path writes the row — dedup/classify/
    # publish/geocode all bulk-UPDATE via SQLAlchemy Core (app/publish.py,
    # app/dedup/rules.py, app/ingestion/geocode/__init__.py,
    # app/llm/classifier.py), which bypasses ORM column defaults.
    #
    # Only bumps updated_at when a column *other* than the excluded
    # sync-bookkeeping ones actually changed. detail_refetched_at/
    # detail_refetch_count (app/ingestion/refetch.py's _mark_synced) and
    # geocode_attempted_at (app/ingestion/geocode) are written on every
    # daily/6-hourly pass over the whole catalog regardless of whether any
    # real content changed — without this exclusion, the prerender
    # pipeline's change-detection (issue #80) would see a marker mismatch
    # for nearly every event on every run and re-render the whole catalog,
    # defeating the copy-forward optimization it exists to provide.
    op.execute(
        f"""
        CREATE FUNCTION {_TRIGGER_FUNCTION}() RETURNS trigger AS $$
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
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER_NAME}
        BEFORE UPDATE ON events
        FOR EACH ROW
        EXECUTE FUNCTION {_TRIGGER_FUNCTION}();
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON events;")
    op.execute(f"DROP FUNCTION IF EXISTS {_TRIGGER_FUNCTION}();")
    op.drop_column("events", "updated_at")
