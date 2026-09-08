"""Backfill NULL currency on events that carry a price (issue #236)

A free event legitimately loses its currency at ingest (see
app/ingestion/pricing.py::normalize_currency) and nothing downstream filled
it in before this release's adapter/refetch fixes — 26 live rows currently
have a price with currency NULL, which fails the JSON-LD prerender
validation gate's `offers.priceCurrency is required when lowPrice is
present` check.

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-08

"""

import sqlalchemy as sa
from alembic import op

from app._generated.shared_constants import DEFAULT_CURRENCY

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE events SET currency = :currency "
            "WHERE price_min IS NOT NULL AND currency IS NULL"
        ).bindparams(currency=DEFAULT_CURRENCY)
    )


def downgrade() -> None:
    # No-op: the pre-backfill state (which rows were NULL) is not
    # recoverable and carries no meaning — a NULL currency alongside a
    # price was itself the bug, not data worth restoring.
    pass
