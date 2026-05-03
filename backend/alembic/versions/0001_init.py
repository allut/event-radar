"""Initial schema — all v0 tables

Revision ID: 0001
Revises:
Create Date: 2026-05-03

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # citext gives case-insensitive equality / uniqueness on email.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    # ------------------------------------------------------------------
    # personas  (no FKs — create before users)
    # ------------------------------------------------------------------
    op.create_table(
        "personas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False),
        sa.Column("display_name_en", sa.String(100), nullable=False),
        sa.Column("display_name_et", sa.String(100), nullable=False),
        sa.Column("display_name_ru", sa.String(100), nullable=False),
        sa.Column("affinity_vector", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    # ------------------------------------------------------------------
    # sources  (no FKs)
    # ------------------------------------------------------------------
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("locale", sa.String(2), nullable=False, server_default="en"),
        sa.Column("home_city", sa.String(100), nullable=False, server_default="Tallinn"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Alter email to citext AFTER table creation so the extension is definitely present.
    op.execute("ALTER TABLE users ALTER COLUMN email TYPE citext")
    op.create_unique_constraint("uq_users_email", "users", ["email"])

    # ------------------------------------------------------------------
    # auth_magic_links
    # ------------------------------------------------------------------
    op.create_table(
        "auth_magic_links",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )

    # ------------------------------------------------------------------
    # user_personas
    # ------------------------------------------------------------------
    op.create_table(
        "user_personas",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "persona_id"),
    )

    # ------------------------------------------------------------------
    # ingestion_runs
    # ------------------------------------------------------------------
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # raw_events
    # ------------------------------------------------------------------
    op.create_table(
        "raw_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("title_orig", sa.Text(), nullable=False),
        sa.Column("description_orig", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("venue_name", sa.String(255), nullable=True),
        sa.Column("venue_address", sa.Text(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("price_min", sa.Numeric(10, 2), nullable=True),
        sa.Column("price_max", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("dedup_group_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_events_starts_at_status", "events", ["starts_at", "status"])
    op.create_index("ix_events_dedup_group_id", "events", ["dedup_group_id"])

    # ------------------------------------------------------------------
    # event_sources  (M2M provenance)
    # ------------------------------------------------------------------
    op.create_table(
        "event_sources",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # event_classifications
    # ------------------------------------------------------------------
    op.create_table(
        "event_classifications",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "categories",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "vibes",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("why_go_bullets", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("language_detected", sa.String(5), nullable=True),
        sa.Column("model_used", sa.String(50), nullable=True),
        sa.Column(
            "classified_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(
        "ix_event_classifications_categories",
        "event_classifications",
        ["categories"],
        postgresql_using="gin",
    )

    # ------------------------------------------------------------------
    # user_event_feedback
    # ------------------------------------------------------------------
    op.create_table(
        "user_event_feedback",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("signal", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_event_feedback_user_created",
        "user_event_feedback",
        ["user_id", "created_at"],
    )

    # ------------------------------------------------------------------
    # user_event_scores
    # ------------------------------------------------------------------
    op.create_table(
        "user_event_scores",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "event_id"),
    )

    # ------------------------------------------------------------------
    # daily_feeds
    # ------------------------------------------------------------------
    op.create_table(
        "daily_feeds",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("feed_date", sa.Date(), nullable=False),
        sa.Column(
            "event_ids",
            postgresql.ARRAY(sa.BigInteger()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "built_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "feed_date"),
    )


def downgrade() -> None:
    op.drop_table("daily_feeds")
    op.drop_table("user_event_scores")
    op.drop_index("ix_user_event_feedback_user_created", table_name="user_event_feedback")
    op.drop_table("user_event_feedback")
    op.drop_index(
        "ix_event_classifications_categories", table_name="event_classifications"
    )
    op.drop_table("event_classifications")
    op.drop_table("event_sources")
    op.drop_index("ix_events_dedup_group_id", table_name="events")
    op.drop_index("ix_events_starts_at_status", table_name="events")
    op.drop_table("events")
    op.drop_table("raw_events")
    op.drop_table("ingestion_runs")
    op.drop_table("user_personas")
    op.drop_constraint("uq_users_email", "users")
    op.drop_table("auth_magic_links")
    op.drop_table("users")
    op.drop_table("sources")
    op.drop_table("personas")
