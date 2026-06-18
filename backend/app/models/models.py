from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType

from app.constants import DEFAULT_USER_CITY, DEFAULT_USER_LOCALE, EVENT_STATUS_DRAFT
from app.db import Base


class CIText(UserDefinedType):
    """PostgreSQL citext extension type — case-insensitive text."""

    cache_ok = True

    def get_col_spec(self, **kw):
        return "CITEXT"


# ---------------------------------------------------------------------------
# Users & Auth
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(CIText(), nullable=False, unique=True)
    locale: Mapped[str] = mapped_column(
        String(2), nullable=False, default=DEFAULT_USER_LOCALE
    )
    home_city: Mapped[str] = mapped_column(
        String(100), nullable=False, default=DEFAULT_USER_CITY
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    email_digest_opt_in: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    # Bumped by /auth/logout-all to invalidate every previously-issued session
    # token at once ("log out everywhere") — compared against the "v" claim in
    # the signed token by get_current_user (routers/auth.py).
    session_token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )

    magic_links: Mapped[list["AuthMagicLink"]] = relationship(back_populates="user")
    user_personas: Mapped[list["UserPersona"]] = relationship(back_populates="user")
    feedback: Mapped[list["UserEventFeedback"]] = relationship(back_populates="user")
    event_scores: Mapped[list["UserEventScore"]] = relationship(back_populates="user")
    daily_feeds: Mapped[list["DailyFeed"]] = relationship(back_populates="user")


class AuthMagicLink(Base):
    __tablename__ = "auth_magic_links"
    __table_args__ = (Index("ix_auth_magic_links_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="magic_links")


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    display_name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name_et: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name_ru: Mapped[str] = mapped_column(String(100), nullable=False)
    affinity_vector: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    user_personas: Mapped[list["UserPersona"]] = relationship(back_populates="persona")


class UserPersona(Base):
    __tablename__ = "user_personas"
    __table_args__ = (UniqueConstraint("user_id", "persona_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id"), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    user: Mapped["User"] = relationship(back_populates="user_personas")
    persona: Mapped["Persona"] = relationship(back_populates="user_personas")


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    ingestion_runs: Mapped[list["IngestionRun"]] = relationship(back_populates="source")
    raw_events: Mapped[list["RawEvent"]] = relationship(back_populates="source")
    event_sources: Mapped[list["EventSource"]] = relationship(back_populates="source")


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped["Source"] = relationship(back_populates="ingestion_runs")


class RawEvent(Base):
    __tablename__ = "raw_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    source: Mapped["Source"] = relationship(back_populates="raw_events")


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_starts_at_status", "starts_at", "status"),
        Index("ix_events_dedup_group_id", "dedup_group_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    title_orig: Mapped[str] = mapped_column(Text, nullable=False)
    description_orig: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    venue_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    venue_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_min: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_max: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EVENT_STATUS_DRAFT
    )
    is_explicit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )
    is_out_of_area: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )
    dedup_group_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    sources: Mapped[list["EventSource"]] = relationship(back_populates="event")
    classification: Mapped["EventClassification | None"] = relationship(
        back_populates="event", uselist=False
    )
    feedback: Mapped[list["UserEventFeedback"]] = relationship(back_populates="event")
    scores: Mapped[list["UserEventScore"]] = relationship(back_populates="event")


class EventSource(Base):
    __tablename__ = "event_sources"
    __table_args__ = (
        Index(
            "ix_event_sources_source_external",
            "source_id",
            "external_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    event: Mapped["Event"] = relationship(back_populates="sources")
    source: Mapped["Source"] = relationship(back_populates="event_sources")


class EventClassification(Base):
    __tablename__ = "event_classifications"
    __table_args__ = (
        Index(
            "ix_event_classifications_categories",
            "categories",
            postgresql_using="gin",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    categories: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    vibes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    why_go_bullets: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    why_go_localized: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    language_detected: Mapped[str | None] = mapped_column(String(5), nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    event: Mapped["Event"] = relationship(back_populates="classification")


# ---------------------------------------------------------------------------
# Feedback & Feeds
# ---------------------------------------------------------------------------


class UserEventFeedback(Base):
    __tablename__ = "user_event_feedback"
    __table_args__ = (
        Index("ix_user_event_feedback_user_created", "user_id", "created_at"),
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


class UserEventScore(Base):
    __tablename__ = "user_event_scores"
    __table_args__ = (UniqueConstraint("user_id", "event_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="event_scores")
    event: Mapped["Event"] = relationship(back_populates="scores")


class DailyFeed(Base):
    __tablename__ = "daily_feeds"
    __table_args__ = (UniqueConstraint("user_id", "feed_date"),)

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


# ---------------------------------------------------------------------------
# Newsletter Inbound Email
# ---------------------------------------------------------------------------


class RawInboundEmail(Base):
    __tablename__ = "raw_inbound_emails"
    __table_args__ = (Index("ix_raw_inbound_emails_received_at", "received_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    from_addr: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    to_addr: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    subject: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ---------------------------------------------------------------------------
# LLM Audit Log
# ---------------------------------------------------------------------------


class LlmCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_content_hash", "content_hash"),
        Index("ix_llm_calls_task_created", "task", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task: Mapped[str] = mapped_column(String(20), nullable=False)
    event_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
