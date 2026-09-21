"""Dedup claimed tiebreak (#418): claims.dormant, set when a claimed event
loses a claimed-vs-claimed dedup collision to a better-quality duplicate —
see app/models/models.py::Claim and app/dedup/rules.py.

Revision ID: 0046
Revises: 0045
Create Date: 2026-09-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "claims",
        sa.Column("dormant", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("claims", "dormant")
