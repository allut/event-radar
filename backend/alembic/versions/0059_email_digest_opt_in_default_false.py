"""users.email_digest_opt_in: new users default to off (real opt-in, #574).

Only the column default changes. Existing rows keep their value, so users who
never chose stay subscribed until they unsubscribe or re-choose in Settings.

Revision ID: 0059
Revises: 0058
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "email_digest_opt_in",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("false"),
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "email_digest_opt_in",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("true"),
    )
