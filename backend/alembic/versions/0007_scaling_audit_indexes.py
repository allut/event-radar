"""Scaling audit indexes: auth_magic_links.user_id, event_sources(source_id, external_id).

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-20
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_auth_magic_links_user_id",
        "auth_magic_links",
        ["user_id"],
    )
    # Pre-flight: any pre-existing duplicate (source_id, external_id) rows
    # would block the unique index. Ingestion already gates against dupes,
    # but manual imports or earlier bugs could have left orphans — keep the
    # smallest event_sources.id for each (source, external_id) and delete
    # the rest. NULL external_id is treated as distinct by NULLS DISTINCT
    # so we explicitly skip NULL rows here.
    op.execute(
        """
        DELETE FROM event_sources
        WHERE external_id IS NOT NULL
          AND id NOT IN (
            SELECT MIN(id)
            FROM event_sources
            WHERE external_id IS NOT NULL
            GROUP BY source_id, external_id
          )
        """
    )
    op.create_index(
        "ix_event_sources_source_external",
        "event_sources",
        ["source_id", "external_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_event_sources_source_external", table_name="event_sources"
    )
    op.drop_index("ix_auth_magic_links_user_id", table_name="auth_magic_links")
