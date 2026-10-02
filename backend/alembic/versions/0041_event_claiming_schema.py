"""Data model foundation for organizer event claiming (#409/#410): a
`publishers` table, a `claims` table, `event_sources.publisher_id`, and
`events.pinned_fields`. Schema only — no application code reads/writes these
yet.

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publishers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_publishers_source_external",
        "publishers",
        ["source_id", "external_id"],
        unique=True,
    )

    op.add_column(
        "event_sources",
        sa.Column(
            "publisher_id",
            sa.BigInteger(),
            sa.ForeignKey("publishers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_table(
        "claims",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "organizer_id",
            sa.BigInteger(),
            sa.ForeignKey("organizers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column(
            "publisher_id",
            sa.BigInteger(),
            sa.ForeignKey("publishers.id"),
            nullable=True,
        ),
        sa.Column("event_series_key", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_claims_organizer_id", "claims", ["organizer_id"])
    op.create_index("ix_claims_publisher_id", "claims", ["publisher_id"])

    op.add_column(
        "events",
        sa.Column(
            "pinned_fields",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "pinned_fields")

    op.drop_index("ix_claims_publisher_id", table_name="claims")
    op.drop_index("ix_claims_organizer_id", table_name="claims")
    op.drop_table("claims")

    op.drop_column("event_sources", "publisher_id")

    op.drop_index("ix_publishers_source_external", table_name="publishers")
    op.drop_table("publishers")
