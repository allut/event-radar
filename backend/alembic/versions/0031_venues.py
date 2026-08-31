"""add venues table (organizer reusable venues, #174)

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-28

"""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "venues",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("organizer_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("name_en", sa.String(length=255), nullable=True),
        sa.Column("name_ru", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("address_en", sa.String(length=500), nullable=True),
        sa.Column("address_ru", sa.String(length=500), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("price_min", sa.Numeric(10, 2), nullable=True),
        sa.Column("price_max", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("geocode_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organizer_id"], ["organizers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_venues_organizer_id", "venues", ["organizer_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_venues_organizer_id", table_name="venues")
    op.drop_table("venues")
