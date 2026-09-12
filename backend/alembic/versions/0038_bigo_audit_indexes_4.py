"""Fourth Big-O audit pass: /feedback/events (Saved Events) had no index
covering (user_id, signal, created_at), so it descended the far larger
append-only view/click_external analytics rows on that table looking for a
handful of preference-signal rows; send_daily_digests' opted-in-population
query had no index at all and seq-scanned users.

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-11
"""

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

_PREFERENCE_SIGNALS_WHERE = "signal IN ('bookmark', 'dislike', 'like')"
_DIGEST_ELIGIBLE_WHERE = "email_digest_opt_in AND email_verified"


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_user_event_feedback_user_signal_created "
        "ON user_event_feedback (user_id, signal, created_at) "
        f"WHERE {_PREFERENCE_SIGNALS_WHERE}"
    )
    op.execute(
        "CREATE INDEX ix_users_digest_eligible ON users (id) "
        f"WHERE {_DIGEST_ELIGIBLE_WHERE}"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_digest_eligible")
    op.execute("DROP INDEX IF EXISTS ix_user_event_feedback_user_signal_created")
