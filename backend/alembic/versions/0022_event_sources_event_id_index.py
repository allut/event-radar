"""Index event_sources.event_id — backs the NOT EXISTS(event_id=...) correlated
subquery in refetch.py::_select_candidates (organizer-submission exclusion),
which otherwise runs a sequential scan of event_sources per refetch candidate.

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-31
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_event_sources_event_id",
        "event_sources",
        ["event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_sources_event_id", table_name="event_sources")
