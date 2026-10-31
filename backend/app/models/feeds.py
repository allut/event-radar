from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants.ranking import (
    PASSIVE_SIGNALS_SQL_PREDICATE,
    PREFERENCE_SIGNALS_SQL_PREDICATE,
)
from app.db import Base

if TYPE_CHECKING:
    from app.models.events import Event
    from app.models.users import User


class UserEventFeedback(Base):
    __tablename__ = "user_event_feedback"
    __table_args__ = (
        Index("ix_user_event_feedback_user_created", "user_id", "created_at"),
        # Partial unique index: current-state model, but ONLY for the explicit
        # preference signals (like/dislike/bookmark, see PREFERENCE_SIGNALS).
        # "view"/"click_external" are passive analytics signals fired on every
        # page view / ticket-link click (routers/feedback.py, frontend
        # trackExternalClick()) — they must stay append-only/multi-row, so this
        # index deliberately does NOT cover them (a plain table-wide unique
        # constraint would let a ticket click silently overwrite a bookmark).
        Index(
            "uq_user_event_feedback_preference_signal",
            "user_id",
            "event_id",
            unique=True,
            postgresql_where=text(PREFERENCE_SIGNALS_SQL_PREDICATE),
        ),
        # Serves GET /feedback/events (Saved Events) as an index-only scan over
        # just the explicit preference-signal rows — the same partial predicate
        # as the unique index above, so it never touches the far larger
        # append-only view/click_external analytics rows (Big-O audit M1).
        Index(
            "ix_user_event_feedback_user_signal_created",
            "user_id",
            "signal",
            "created_at",
            postgresql_where=text(PREFERENCE_SIGNALS_SQL_PREDICATE),
        ),
        # Passive analytics signals: at most one row per (user, event, signal,
        # UTC day), so a client firing view/click_external at the rate limit
        # can't grow the table without bound (OWASP audit #9). POST /feedback
        # inserts with ON CONFLICT DO NOTHING against this index.
        Index(
            "uq_user_event_feedback_passive_signal_day",
            "user_id",
            "event_id",
            "signal",
            text("((created_at AT TIME ZONE 'UTC')::date)"),
            unique=True,
            postgresql_where=text(PASSIVE_SIGNALS_SQL_PREDICATE),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    signal: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="feedback")
    event: Mapped["Event"] = relationship(back_populates="feedback")


class DailyFeed(Base):
    __tablename__ = "daily_feeds"
    __table_args__ = (
        UniqueConstraint("user_id", "feed_date"),
        # cleanup.py's DailyFeed.feed_date < cutoff has no user_id filter — the
        # UniqueConstraint above leads with user_id, so this indexless-for-that-
        # predicate query was unusable by it.
        Index("ix_daily_feeds_feed_date", "feed_date"),
        # admin.py's event-inspector event_ids.contains([id]) (`@>`) check was
        # a full scan of every active user's feed row per event-inspector open
        # (Big-O audit #5, item 2.9).
        Index("ix_daily_feeds_event_ids_gin", "event_ids", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    feed_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False, default=list
    )
    built_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="daily_feeds")
