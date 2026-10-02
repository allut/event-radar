"""events.series_key: trigger-maintained normalized series identity (M6)

Series-claim resolution (claims/pinning.py) scanned up to 2000 not-yet-ended
events in Python to recompute event_series_key() per row. This stores the
serialized key (serialize_event_series_key: normalized title, U+001F,
normalized resolved venue name) in a btree-indexed column instead.

Maintained entirely in the DB so no write site can drift:
- a BEFORE INSERT/UPDATE OF (title_orig, venue_name, venue_id) trigger on
  events recomputes it; a linked venue resolves to coalesce(name_en, name)
  exactly like resolve_venue_name()'s default-locale pick.
- an AFTER UPDATE OF (name, name_en) trigger on venues refreshes the events
  linked to a renamed venue.
event_series_key_sql() mirrors normalized_title() (lowercase, collapse
Unicode whitespace); tests/test_events_series_key_sql.py guards the drift.
series_key is deliberately outside 0050's updated_at column list: it only
changes when a tracked column does.

Revision ID: 0052
Revises: 0051
Create Date: 2026-09-29
"""

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

# Frozen: characters str.split() treats as whitespace, as an ARE bracket body.
WHITESPACE_CLASS = (
    r"[ \t\n\r\f\v\x1c-\x1f\x85\xa0  -     　]+"
)

_NORMALIZE_FN = "event_title_key_sql"
_KEY_FN = "event_series_key_sql"
_EVENT_TRIGGER = "trg_events_set_series_key"
_VENUE_TRIGGER = "trg_venues_refresh_event_series_key"


def upgrade() -> None:
    op.execute("ALTER TABLE events ADD COLUMN series_key text")
    op.execute(
        f"""
        CREATE FUNCTION {_NORMALIZE_FN}(value text) RETURNS text AS $$
            SELECT btrim(regexp_replace(lower(coalesce(value, '')), '{WHITESPACE_CLASS}', ' ', 'g'), ' ')
        $$ LANGUAGE sql IMMUTABLE
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION {_KEY_FN}(title text, venue text) RETURNS text AS $$
            SELECT {_NORMALIZE_FN}(title) || chr(31) || {_NORMALIZE_FN}(venue)
        $$ LANGUAGE sql IMMUTABLE
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION {_EVENT_TRIGGER}() RETURNS trigger AS $$
        DECLARE
            resolved_venue text;
        BEGIN
            IF NEW.venue_id IS NOT NULL THEN
                SELECT coalesce(nullif(v.name_en, ''), v.name) INTO resolved_venue
                FROM venues v WHERE v.id = NEW.venue_id;
            ELSE
                resolved_venue := NEW.venue_name;
            END IF;
            NEW.series_key := {_KEY_FN}(NEW.title_orig, resolved_venue);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_EVENT_TRIGGER}
        BEFORE INSERT OR UPDATE OF title_orig, venue_name, venue_id ON events
        FOR EACH ROW EXECUTE FUNCTION {_EVENT_TRIGGER}()
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION {_VENUE_TRIGGER}() RETURNS trigger AS $$
        BEGIN
            UPDATE events
            SET series_key = {_KEY_FN}(
                title_orig, coalesce(nullif(NEW.name_en, ''), NEW.name)
            )
            WHERE venue_id = NEW.id;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_VENUE_TRIGGER}
        AFTER UPDATE OF name, name_en ON venues
        FOR EACH ROW EXECUTE FUNCTION {_VENUE_TRIGGER}()
        """
    )
    # Backfill. Statement-level trigger-free: the row trigger only fires on
    # the listed columns, so series_key alone does not re-enter it.
    op.execute(
        f"""
        UPDATE events e
        SET series_key = {_KEY_FN}(
            e.title_orig,
            CASE WHEN e.venue_id IS NOT NULL
                 THEN (SELECT coalesce(nullif(v.name_en, ''), v.name)
                       FROM venues v WHERE v.id = e.venue_id)
                 ELSE e.venue_name END
        )
        """
    )
    op.execute("CREATE INDEX ix_events_series_key_starts_at ON events (series_key, starts_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_events_series_key_starts_at")
    op.execute(f"DROP TRIGGER IF EXISTS {_VENUE_TRIGGER} ON venues")
    op.execute(f"DROP FUNCTION IF EXISTS {_VENUE_TRIGGER}()")
    op.execute(f"DROP TRIGGER IF EXISTS {_EVENT_TRIGGER} ON events")
    op.execute(f"DROP FUNCTION IF EXISTS {_EVENT_TRIGGER}()")
    op.execute(f"DROP FUNCTION IF EXISTS {_KEY_FN}(text, text)")
    op.execute(f"DROP FUNCTION IF EXISTS {_NORMALIZE_FN}(text)")
    op.execute("ALTER TABLE events DROP COLUMN series_key")
