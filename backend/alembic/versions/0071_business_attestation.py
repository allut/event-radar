"""Business attestation: when the Organizer confirmed the registry code on a
Promotion is its own business (security audit). Existing rows stay
NULL: they were made before the attestation existed.

Revision ID: 0071
Revises: 0070
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


_TABLES = ("promotions", "promotion_requests")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table, sa.Column("business_attested_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "business_attested_at")
