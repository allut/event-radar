"""add Event.venue_id FK to venues (#176)

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-28

"""

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("venue_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_events_venue_id_venues",
        "events",
        "venues",
        ["venue_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_events_venue_id", "events", ["venue_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_events_venue_id", table_name="events")
    op.drop_constraint("fk_events_venue_id_venues", "events", type_="foreignkey")
    op.drop_column("events", "venue_id")
