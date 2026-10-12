"""events.source_gone_since: when the detail-refetch first saw the source page gone.

Set on the first 404/410 from an event's detail page and cleared by any later
successful fetch. Once the page has stayed gone for
REFETCH_GONE_CANCEL_AFTER_DAYS the refetch cancels the event.

Bookkeeping column: deliberately absent from the 0050 updated_at trigger's
tracked-column list, like geocode_attempted_at.

Revision ID: 0058
Revises: 0057
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("source_gone_since", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("events", "source_gone_since")
