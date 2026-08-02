"""add organizer_image_uploads

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-03

"""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizer_image_uploads",
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
        "ix_organizer_image_uploads_organizer_id",
        "organizer_image_uploads",
        ["organizer_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_organizer_image_uploads_organizer_id", table_name="organizer_image_uploads"
    )
    op.drop_table("organizer_image_uploads")
