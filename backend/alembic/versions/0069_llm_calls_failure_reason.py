"""llm_calls.failure_reason (#636): why a provider attempt failed, so a
truncated completion is distinguishable from a rate limit or a bad response.

Existing rows stay NULL; successful attempts leave it NULL.

Revision ID: 0069
Revises: 0068
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("failure_reason", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_calls", "failure_reason")
