"""Stripe card checkout (#618): promotion checkout columns, the Stripe customer
map and the processed webhook event ids.

Revision ID: 0067
Revises: 0066
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None

_TEXT_COLUMNS = (
    ("stripe_customer_id", sa.String(length=64)),
    ("stripe_checkout_session_id", sa.String(length=255)),
    ("stripe_payment_intent_id", sa.String(length=255)),
    ("stripe_invoice_id", sa.String(length=255)),
    ("invoice_url", sa.Text()),
    ("content_policy_version", sa.String(length=16)),
    ("terms_version", sa.String(length=16)),
)
_TIME_COLUMNS = (
    "checkout_expires_at",
    "content_policy_attested_at",
    "terms_accepted_at",
)


def upgrade() -> None:
    for name, type_ in _TEXT_COLUMNS:
        op.add_column("promotions", sa.Column(name, type_, nullable=True))
    for name in _TIME_COLUMNS:
        op.add_column("promotions", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_promotions_stripe_checkout_session_id",
        "promotions",
        ["stripe_checkout_session_id"],
        unique=True,
        postgresql_where=sa.text("stripe_checkout_session_id IS NOT NULL"),
    )
    op.create_index(
        "ix_promotions_stripe_payment_intent_id",
        "promotions",
        ["stripe_payment_intent_id"],
        postgresql_where=sa.text("stripe_payment_intent_id IS NOT NULL"),
    )
    op.create_table(
        "stripe_customers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "organizer_id",
            sa.BigInteger(),
            sa.ForeignKey("organizers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("registry_code", sa.String(length=32), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "organizer_id", "registry_code", name="uq_stripe_customers_organizer_code"
        ),
    )
    op.create_table(
        "processed_stripe_events",
        sa.Column("stripe_event_id", sa.String(length=255), primary_key=True),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("processed_stripe_events")
    op.drop_table("stripe_customers")
    op.drop_index("ix_promotions_stripe_payment_intent_id", table_name="promotions")
    op.drop_index("uq_promotions_stripe_checkout_session_id", table_name="promotions")
    for name in (*_TIME_COLUMNS, *(n for n, _ in _TEXT_COLUMNS)):
        op.drop_column("promotions", name)
