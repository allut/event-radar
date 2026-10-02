"""Claim-editing surface (#416): claim_edit_attempts table backing
ORGANIZER_DAILY_CLAIM_EDIT_CAP — one row per claim-edit PATCH attempt,
regardless of outcome (see app/models/models.py::ClaimEditAttempt).

Revision ID: 0045
Revises: 0044
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claim_edit_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "organizer_id",
            sa.BigInteger(),
            sa.ForeignKey("organizers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_claim_edit_attempts_organizer_created",
        "claim_edit_attempts",
        ["organizer_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_claim_edit_attempts_organizer_created", table_name="claim_edit_attempts")
    op.drop_table("claim_edit_attempts")
