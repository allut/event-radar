"""raw_inbound_emails table for newsletter webhook

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_inbound_emails",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("from_addr", sa.Text(), server_default="", nullable=False),
        sa.Column("to_addr", sa.Text(), server_default="", nullable=False),
        sa.Column("subject", sa.Text(), server_default="", nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_raw_inbound_emails_received_at",
        "raw_inbound_emails",
        ["received_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_raw_inbound_emails_received_at", table_name="raw_inbound_emails")
    op.drop_table("raw_inbound_emails")
