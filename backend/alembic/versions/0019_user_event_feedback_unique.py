"""user_event_feedback: partial unique (user_id, event_id) for preference signals.

Current-state model for the explicit preference signals only (like/dislike/
bookmark). "view"/"click_external" are passive analytics signals fired on
every page view / ticket-link click and must stay append-only/multi-row — a
plain table-wide unique constraint would let a ticket click (click_external)
silently overwrite a user's bookmark, so the index is partial
(``WHERE signal IN ('like','dislike','bookmark')``) and excludes them.

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Pre-flight: keep the most-recent row per (user_id, event_id) among the
    # preference signals only — that is the user's current preference — and
    # drop the rest. "view"/"click_external" rows are untouched: they are
    # legitimately multi-row per (user_id, event_id) and outside this index.
    op.execute(
        """
        DELETE FROM user_event_feedback
        WHERE signal IN ('like', 'dislike', 'bookmark')
          AND id NOT IN (
            SELECT DISTINCT ON (user_id, event_id) id
            FROM user_event_feedback
            WHERE signal IN ('like', 'dislike', 'bookmark')
            ORDER BY user_id, event_id, created_at DESC, id DESC
          )
        """
    )
    op.create_index(
        "uq_user_event_feedback_preference_signal",
        "user_event_feedback",
        ["user_id", "event_id"],
        unique=True,
        postgresql_where=sa.text("signal IN ('like', 'dislike', 'bookmark')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_user_event_feedback_preference_signal",
        table_name="user_event_feedback",
    )
