"""drop venues.address_en/address_ru (#174 follow-up — address doesn't localize)

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-29

"""

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("venues", "address_en")
    op.drop_column("venues", "address_ru")


def downgrade() -> None:
    op.add_column("venues", sa.Column("address_en", sa.String(length=500), nullable=True))
    op.add_column("venues", sa.Column("address_ru", sa.String(length=500), nullable=True))
