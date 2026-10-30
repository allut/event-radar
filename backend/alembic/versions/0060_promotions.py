"""Promotions (#600): the promotions table and events.promotion_restriction.

events.promotion_restriction is deliberately NOT added to the
trg_events_set_updated_at column list (migration 0050): starting, ending or
assessing a Promotion must never move the event's change marker.

Revision ID: 0060
Revises: 0059
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("promotion_restriction", sa.String(length=16), nullable=True),
    )
    op.create_table(
        "promotions",
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
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("net_price_cents", sa.Integer(), nullable=False),
        sa.Column("vat_rate_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "is_complimentary", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("complimentary_note", sa.Text(), nullable=True),
        sa.Column("invoice_reference", sa.String(length=64), nullable=True),
        sa.Column("invoice_source", sa.String(length=20), nullable=True),
        sa.Column("advertiser_legal_name", sa.String(length=255), nullable=False),
        sa.Column("advertiser_registry_code", sa.String(length=32), nullable=False),
        sa.Column("billing_email", sa.String(length=255), nullable=True),
        sa.Column("granted_by", sa.String(length=16), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(length=40), nullable=True),
        sa.Column("end_note", sa.Text(), nullable=True),
        sa.Column("refunded_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("refund_note", sa.Text(), nullable=True),
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
            "status IN ('unpaid', 'paid', 'ended_early', 'void')",
            name="ck_promotions_status",
        ),
        sa.CheckConstraint("end_date >= start_date", name="ck_promotions_window_order"),
        sa.CheckConstraint("days >= 1", name="ck_promotions_days_positive"),
    )
    op.create_index("ix_promotions_event_id", "promotions", ["event_id"])
    op.create_index("ix_promotions_organizer_id", "promotions", ["organizer_id"])
    op.create_index(
        "ix_promotions_status_window",
        "promotions",
        ["status", "start_date", "end_date"],
    )


def downgrade() -> None:
    op.drop_table("promotions")
    op.drop_column("events", "promotion_restriction")
