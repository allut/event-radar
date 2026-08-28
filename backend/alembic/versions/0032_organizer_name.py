"""add organizer name (#175)

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-28

"""

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizers", sa.Column("name", sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("organizers", "name")
