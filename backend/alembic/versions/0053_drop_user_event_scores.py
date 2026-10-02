"""Drop user_event_scores: the per-(user, event) score read-through cache

build_daily_feeds now recomputes scores every run (per-event factors are
precomputed once and the persona-affinity memo makes the user x event pass
cheap — Big-O audit H4), so the cache table, its invalidation on every
like/dislike/persona change and its weekly cleanup are gone. The table was the
largest by row count; dropping it also drops its indexes.

Downgrade recreates the empty table (the cache is rebuildable by design).

Revision ID: 0053
Revises: 0052
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("user_event_scores")


def downgrade() -> None:
    op.create_table(
        "user_event_scores",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "event_id"),
    )
    op.create_index("ix_user_event_scores_event_id", "user_event_scores", ["event_id"])
