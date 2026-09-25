"""Piletilevi two-tier auto-grant + Series justification (#428):
claims.verification_contact (resolved Piletilevi mailbox evidence for the
piletilevi_mailbox mechanism) and claims.justification (required, at the
service layer, for a Series claim) — see app/models/models.py::Claim.

Revision ID: 0047
Revises: 0046
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("claims", sa.Column("verification_contact", sa.String(320), nullable=True))
    op.add_column("claims", sa.Column("justification", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("claims", "justification")
    op.drop_column("claims", "verification_contact")
