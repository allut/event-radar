"""Stripe customer billing details (#628): the email and legal name last sent to
Stripe, so a repeat checkout updates the Customer only on a change.

Existing rows stay NULL: the next checkout sends one update and fills them.

Revision ID: 0068
Revises: 0067
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stripe_customers", sa.Column("billing_email", sa.String(length=255), nullable=True))
    op.add_column("stripe_customers", sa.Column("legal_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("stripe_customers", "legal_name")
    op.drop_column("stripe_customers", "billing_email")
