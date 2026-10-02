"""user_event_feedback: one passive-signal row per (user, event, signal, UTC day)

"view"/"click_external" rows were appended on every hit (up to the endpoint's
rate limit per IP) and nothing ever deleted them, so the table grew without
bound (OWASP audit #9). They are pure analytics — ranking reads only
like/dislike rows — so a partial unique index over the passive signals bounds
growth to one row per user, event, signal and UTC day while keeping history.
POST /feedback now inserts them with ON CONFLICT DO NOTHING.

The index predicate is frozen to the complement of the three preference
signals (like/dislike/bookmark), the same set migration 0019's partial unique
index covers.

Defensive DELETE first: keeps the earliest row per bucket so the index build
cannot collide with historical duplicates. Not reversible data-wise (the
deleted duplicates are gone); the downgrade just drops the index.

Revision ID: 0055
Revises: 0054
Create Date: 2026-10-01
"""

from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None

_INDEX = "uq_user_event_feedback_passive_signal_day"
_PASSIVE_PREDICATE = "NOT (signal IN ('bookmark', 'dislike', 'like'))"
_DAY_EXPR = "((created_at AT TIME ZONE 'UTC')::date)"


def upgrade() -> None:
    op.execute(
        f"""
        DELETE FROM user_event_feedback f
        USING (
            SELECT id, row_number() OVER (
                PARTITION BY user_id, event_id, signal, {_DAY_EXPR}
                ORDER BY id
            ) AS rn
            FROM user_event_feedback
            WHERE {_PASSIVE_PREDICATE}
        ) d
        WHERE f.id = d.id AND d.rn > 1
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX}
        ON user_event_feedback (user_id, event_id, signal, {_DAY_EXPR})
        WHERE {_PASSIVE_PREDICATE}
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX {_INDEX}")
