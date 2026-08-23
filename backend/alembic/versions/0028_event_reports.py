"""add event_reports table and events.cancellation_reason column

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-23

"""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("cancellation_reason", sa.String(length=20), nullable=True),
    )
    op.create_table(
        "event_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column(
            "is_illegal_allegation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="open",
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_event_reports_user_event",
        "event_reports",
        ["user_id", "event_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_event_reports_user_event", table_name="event_reports")
    op.drop_table("event_reports")
    op.drop_column("events", "cancellation_reason")
