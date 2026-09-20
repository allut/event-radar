"""Partial unique index on publishers(source_id) WHERE external_id IS NULL
(#411 code-review finding): Postgres unique indexes treat NULL as distinct,
so the existing (source_id, external_id) unique index alone allows two
KUMU/Estonia Concert Hall-style constant Publisher rows per source. This
closes that gap.

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_publishers_source_null_external",
        "publishers",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_publishers_source_null_external", table_name="publishers")
