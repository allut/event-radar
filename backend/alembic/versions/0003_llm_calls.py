"""Add llm_calls table for LLM audit log and response cache

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-07

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("task", sa.String(20), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("response_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_calls_content_hash", "llm_calls", ["content_hash"])
    op.create_index("ix_llm_calls_task_created", "llm_calls", ["task", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_task_created", table_name="llm_calls")
    op.drop_index("ix_llm_calls_content_hash", table_name="llm_calls")
    op.drop_table("llm_calls")
