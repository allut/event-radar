"""Promotion requests (#614): promotion_requests and promotions.source_request_id.

Revision ID: 0066
Revises: 0065
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promotion_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.ForeignKey("events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "organizer_id",
            sa.BigInteger(),
            sa.ForeignKey("organizers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("advertiser_legal_name", sa.String(length=255), nullable=False),
        sa.Column("advertiser_registry_code", sa.String(length=32), nullable=False),
        sa.Column("billing_email", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(length=16), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terms_version", sa.SmallInteger(), nullable=False),
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'granted', 'declined', 'withdrawn', 'expired')",
            name="ck_promotion_requests_status",
        ),
        sa.CheckConstraint(
            "end_date >= start_date", name="ck_promotion_requests_window_order"
        ),
    )
    op.create_index(
        "uq_promotion_requests_one_pending_per_event",
        "promotion_requests",
        ["event_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_promotion_requests_organizer_id",
        "promotion_requests",
        ["organizer_id", "created_at"],
    )
    op.create_index("ix_promotion_requests_status", "promotion_requests", ["status"])
    op.add_column(
        "promotions",
        sa.Column(
            "source_request_id",
            sa.BigInteger(),
            sa.ForeignKey("promotion_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("promotions", "source_request_id")
    op.drop_table("promotion_requests")
