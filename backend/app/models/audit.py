from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AdminAction(Base):
    """Append-only durable record of a destructive/moderation admin action
    (takedown, retract, approve, resolve reports, pipeline run) — the report
    feature carries legal obligations that generally assume this is
    reconstructible after the fact. Written inside the same transaction as the mutation it
    records where the endpoint has one open; survives an outage of the
    LOG_SHIP_URL log drain, unlike the structured log line alone. There is no
    admins table, so there is no actor column — "a login
    happened" is the only fact the admin auth model asserts."""

    __tablename__ = "admin_actions"
    __table_args__ = (
        Index("ix_admin_actions_created_at", "created_at"),
        # Revoked-claim tombstone lookup (organizer_claims.py) filters
        # action + target and takes the newest row.
        Index("ix_admin_actions_action_target", "action", "target", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
