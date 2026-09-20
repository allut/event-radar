"""Claim lifecycle backend (#413): verification_mechanism/proof_token/
last_checked_at/resolved_at columns on `claims`, plus the two partial unique
indexes that reject a duplicate/racing claim against the same Publisher or
Series at insert time.

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

CLAIM_ACTIVE_STATUSES_SQL = "status IN ('pending', 'approved')"


def upgrade() -> None:
    op.add_column(
        "claims",
        sa.Column("verification_mechanism", sa.String(length=30), nullable=True),
    )
    # No NOT NULL backfill concern — `claims` is schema-only so far (#409/#410),
    # no application code has written a row yet (0041's docstring).
    op.add_column(
        "claims",
        sa.Column("proof_token", sa.String(length=64), nullable=False),
    )
    op.add_column(
        "claims",
        sa.Column(
            "last_checked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "claims",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_claims_active_publisher",
        "claims",
        ["publisher_id"],
        unique=True,
        postgresql_where=sa.text(
            f"{CLAIM_ACTIVE_STATUSES_SQL} AND publisher_id IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_claims_active_series",
        "claims",
        ["event_series_key"],
        unique=True,
        postgresql_where=sa.text(
            f"{CLAIM_ACTIVE_STATUSES_SQL} AND event_series_key IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_claims_active_series", table_name="claims")
    op.drop_index("ix_claims_active_publisher", table_name="claims")

    op.drop_column("claims", "resolved_at")
    op.drop_column("claims", "last_checked_at")
    op.drop_column("claims", "proof_token")
    op.drop_column("claims", "verification_mechanism")
