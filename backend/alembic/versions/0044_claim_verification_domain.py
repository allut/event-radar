"""Claim entry portal UX (#415): verification_domain column on `claims` —
persists the DNS-TXT domain (KUMU/ECH's hardcoded institutional domain, or a
resolved Piletilevi promoter domain) so the pending screen can render
"add this TXT record" instructions without re-resolving the domain on load.

Revision ID: 0044
Revises: 0043
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "claims",
        sa.Column("verification_domain", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("claims", "verification_domain")
