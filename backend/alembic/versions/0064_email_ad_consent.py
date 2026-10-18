"""Email ad consent (#610): users flag + wording version, append-only log.

Revision ID: 0064
Revises: 0063
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "email_ad_consent", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "users", sa.Column("email_ad_consent_version", sa.SmallInteger(), nullable=True)
    )
    op.create_table(
        "email_ad_consent_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("wording_version", sa.SmallInteger(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("locale", sa.String(length=2), nullable=False),
    )
    op.create_index(
        "ix_email_ad_consent_log_user_id", "email_ad_consent_log", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("email_ad_consent_log")
    op.drop_column("users", "email_ad_consent_version")
    op.drop_column("users", "email_ad_consent")
