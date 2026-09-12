"""add user_identities / organizer_identities + pending_google_sub (#293)

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-10

"""

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_magic_links",
        sa.Column("pending_google_sub", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "organizer_magic_links",
        sa.Column("pending_google_sub", sa.String(length=255), nullable=True),
    )

    op.create_table(
        "user_identities",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_sub", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("provider", "provider_sub"),
    )
    op.create_index(
        "ix_user_identities_user_id", "user_identities", ["user_id"]
    )

    op.create_table(
        "organizer_identities",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "organizer_id",
            sa.BigInteger(),
            sa.ForeignKey("organizers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_sub", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("provider", "provider_sub"),
    )
    op.create_index(
        "ix_organizer_identities_organizer_id",
        "organizer_identities",
        ["organizer_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_organizer_identities_organizer_id", table_name="organizer_identities")
    op.drop_table("organizer_identities")

    op.drop_index("ix_user_identities_user_id", table_name="user_identities")
    op.drop_table("user_identities")

    op.drop_column("organizer_magic_links", "pending_google_sub")
    op.drop_column("auth_magic_links", "pending_google_sub")
