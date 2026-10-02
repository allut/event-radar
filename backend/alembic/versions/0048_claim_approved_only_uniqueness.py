"""Duplicate/contested claims (#431, slice 1 of #425): narrow the active-claim
partial unique indexes from "one pending-or-approved claim per target" to
"one approved claim per target" — multiple pending claims may now coexist on
the same Publisher/Series target, each with its own proof token. upgrade()
needs no defensive cleanup: the prior index already enforced uniqueness
across pending+approved, a strict superset of the new approved-only
constraint, so no historical approved-vs-approved duplicate can exist.
downgrade() does need one, the other way around: by the time a rollback
runs there may be real coexisting-pending-claims rows (this migration's
whole point), which would collide with the wider index being restored — see
its own comment.

Revision ID: 0048
Revises: 0047
Create Date: 2026-09-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None

CLAIM_APPROVED_ONLY_SQL = "status = 'approved'"


def upgrade() -> None:
    op.drop_index("ix_claims_active_publisher", table_name="claims")
    op.drop_index("ix_claims_active_series", table_name="claims")
    op.create_index(
        "ix_claims_active_publisher",
        "claims",
        ["publisher_id"],
        unique=True,
        postgresql_where=sa.text(
            f"{CLAIM_APPROVED_ONLY_SQL} AND publisher_id IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_claims_active_series",
        "claims",
        ["event_series_key"],
        unique=True,
        postgresql_where=sa.text(
            f"{CLAIM_APPROVED_ONLY_SQL} AND event_series_key IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_claims_active_publisher", table_name="claims")
    op.drop_index("ix_claims_active_series", table_name="claims")
    # Defensive (CLAUDE.md migrations rule): this migration's whole point is
    # to let multiple pending claims coexist per target, so by the time a
    # downgrade runs there may be real ones — recreating the wider
    # pending-or-approved index without first resolving them would fail with
    # a duplicate-key error. Cancel every claim but one per target (the
    # approved one if there is one, else the newest pending one) rather than
    # deleting rows outright.
    op.execute(
        """
        UPDATE claims
        SET status = 'cancelled', resolved_at = now()
        WHERE status IN ('pending', 'approved')
          AND publisher_id IS NOT NULL
          AND id NOT IN (
            SELECT DISTINCT ON (publisher_id) id
            FROM claims
            WHERE status IN ('pending', 'approved') AND publisher_id IS NOT NULL
            ORDER BY publisher_id, (status = 'approved') DESC, id DESC
          )
        """
    )
    op.execute(
        """
        UPDATE claims
        SET status = 'cancelled', resolved_at = now()
        WHERE status IN ('pending', 'approved')
          AND event_series_key IS NOT NULL
          AND id NOT IN (
            SELECT DISTINCT ON (event_series_key) id
            FROM claims
            WHERE status IN ('pending', 'approved') AND event_series_key IS NOT NULL
            ORDER BY event_series_key, (status = 'approved') DESC, id DESC
          )
        """
    )
    op.create_index(
        "ix_claims_active_publisher",
        "claims",
        ["publisher_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending', 'approved') AND publisher_id IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_claims_active_series",
        "claims",
        ["event_series_key"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending', 'approved') AND event_series_key IS NOT NULL"
        ),
    )
