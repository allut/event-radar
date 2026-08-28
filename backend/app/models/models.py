from datetime import date, datetime
from typing import Any

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
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType

from app.constants import (
    DEFAULT_USER_CITY,
    DEFAULT_USER_LOCALE,
    EVENT_STATUS_DRAFT,
    PREFERENCE_SIGNALS_SQL_PREDICATE,
)
from app.db import Base


class CIText(UserDefinedType):
    """PostgreSQL citext extension type — case-insensitive text."""

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "CITEXT"


# ---------------------------------------------------------------------------
# Users & Auth
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(CIText(), nullable=False, unique=True)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
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
    __table_args__ = (
        Index("ix_auth_magic_links_user_id", "user_id"),
        Index("ix_auth_magic_links_expires_at", "expires_at"),
    )

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
# Organizers (direct event submission)
# ---------------------------------------------------------------------------


class Organizer(Base):
    """A separate account track from User — organizers submit events directly,
    authenticated via their own magic-link stack (distinct salts, see
    app/auth/tokens.py), never consumer sign-in."""

    __tablename__ = "organizers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(CIText(), nullable=False, unique=True)
    locale: Mapped[str] = mapped_column(
        String(2), nullable=False, default=DEFAULT_USER_LOCALE
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Bumped by /organizer/auth/logout-all to invalidate every previously-issued
    # organizer session token at once — mirrors User.session_token_version.
    session_token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    # False until an admin approves this organizer's first submission
    # (POST /admin/submissions/{id}/approve). An unverified organizer's events
    # are excluded from the publish gate (app/publish.py) regardless of
    # otherwise clearing it, so a brand-new self-registered account can't push
    # a live event into every user's feed/inbox with no human in the loop.
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # Optional display name (#175) — no logo/contact-info fields, out of scope
    # per docs/organizer-portal.md's Organizer Profile section.
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    magic_links: Mapped[list["OrganizerMagicLink"]] = relationship(
        back_populates="organizer"
    )


class OrganizerMagicLink(Base):
    __tablename__ = "organizer_magic_links"
    __table_args__ = (
        Index("ix_organizer_magic_links_organizer_id", "organizer_id"),
        Index("ix_organizer_magic_links_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organizer_id: Mapped[int] = mapped_column(
        ForeignKey("organizers.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    organizer: Mapped["Organizer"] = relationship(back_populates="magic_links")


class OrganizerImageUpload(Base):
    """One row per successful Cloudinary upload (POST /organizer/events/image).

    Exists purely to count-then-act against ORGANIZER_DAILY_IMAGE_UPLOAD_CAP —
    an upload can happen before the organizer ever submits/edits an event, so
    it can't be derived from Event rows the way ORGANIZER_DAILY_SUBMISSION_CAP
    counts Event.created_at. Never read back, no retention sweep — cheap
    enough to keep indefinitely, and its count feeds a rolling day-window
    query rather than an aggregate that would grow stale.
    """

    __tablename__ = "organizer_image_uploads"
    __table_args__ = (
        Index("ix_organizer_image_uploads_organizer_id", "organizer_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organizer_id: Mapped[int] = mapped_column(
        ForeignKey("organizers.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Venue(Base):
    """A reusable venue an organizer builds up across event submissions
    (docs/organizer-portal.md, #173). Per-locale text columns mirror the
    Persona pattern rather than Event's JSONB localized-field pattern, since
    a venue has no ingestion path that fills locales piecemeal. price_min/
    price_max/currency are copy-in defaults for a submission form, not
    authoritative pricing — the Event row created from a venue owns its own
    price fields. geocode_attempted_at is a separate cooldown clock from
    Event's own column of the same name."""

    __tablename__ = "venues"
    __table_args__ = (Index("ix_venues_organizer_id", "organizer_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organizer_id: Mapped[int] = mapped_column(
        ForeignKey("organizers.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_ru: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    address_en: Mapped[str | None] = mapped_column(String(500), nullable=True)
    address_ru: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_min: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_max: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    geocode_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


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
    __table_args__ = (Index("ix_ingestion_runs_started_at", "started_at"),)

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
    __table_args__ = (
        Index("ix_raw_events_fetched_at", "fetched_at"),
        # Composite serves ingest_skip_ids' (source_id, fetched_at >= cutoff)
        # predicate directly instead of a bitmap-AND over two single-column
        # indexes; also covers source_id-only lookups (leftmost prefix).
        Index("ix_raw_events_source_fetched", "source_id", "fetched_at"),
    )

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
        # Created by migration 0002 but was missing here — a create_all-built
        # schema (tests) lacked it until this declaration was added back.
        Index("ix_events_status", "status"),
        # Explore keyword search (`ILIKE '%q%'`) can't use a B-tree on a
        # leading wildcard; trigram GIN indexes accelerate it. Requires the
        # pg_trgm extension (enabled in migration 0020).
        Index(
            "ix_events_title_orig_trgm",
            "title_orig",
            postgresql_using="gin",
            postgresql_ops={"title_orig": "gin_trgm_ops"},
        ),
        Index(
            "ix_events_description_orig_trgm",
            "description_orig",
            postgresql_using="gin",
            postgresql_ops={"description_orig": "gin_trgm_ops"},
        ),
        # Partial indexes matching the geocode/refetch pending-candidate
        # queries (ORDER BY ... NULLS FIRST LIMIT N over a narrow predicate).
        Index(
            "ix_events_geocode_attempted_at",
            "geocode_attempted_at",
            postgresql_where=text("venue_address IS NOT NULL AND lat IS NULL"),
        ),
        Index(
            "ix_events_detail_refetched_at",
            "detail_refetched_at",
            postgresql_where=text("url IS NOT NULL"),
        ),
        # Composite, not single-column: serves both organizer_events.py's daily
        # submission-cap query (submitted_by_organizer_id = X AND created_at >=
        # day_start) and list_own_events's (submitted_by_organizer_id = X ORDER
        # BY created_at DESC) — a single-column index on submitted_by_organizer_id
        # alone would leave created_at as a heap filter/sort on the organizer's
        # entire history.
        Index(
            "ix_events_organizer_created",
            "submitted_by_organizer_id",
            "created_at",
        ),
        # Admin review-queue candidate query (Phase 2): needs_review IS TRUE.
        Index(
            "ix_events_needs_review",
            "needs_review",
            postgresql_where=text("needs_review"),
        ),
        # event_not_ended_filter()'s OR (ends_at >= now) / (ends_at IS NULL AND
        # starts_at >= now) can't use a plain B-tree — this expression index
        # backs it (and _date_range_filter's identical coalesce(ends_at,
        # starts_at) >= date_from_start in browse.py), on the largest table in
        # the schema, which grows forever since events rows are never deleted.
        Index(
            "ix_events_live_until",
            text("coalesce(ends_at, starts_at)"),
        ),
        # ORDER BY events.price_min ASC NULLS LAST (browse.py's price sort, Path A).
        Index("ix_events_price_min", "price_min"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    title_orig: Mapped[str] = mapped_column(Text, nullable=False)
    description_orig: Mapped[str | None] = mapped_column(Text, nullable=True)
    important_info: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    is_non_event: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )
    has_free_tier: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )
    detail_refetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    detail_refetch_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    geocode_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    title_localized: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    description_localized: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    important_info_localized: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    dedup_group_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Kept current by a DB trigger (migration 0027), not an ORM-level
    # `onupdate` — most writers (dedup/classify/publish/geocode) bulk-UPDATE
    # via SQLAlchemy Core, which bypasses ORM column defaults. The trigger
    # only bumps this when a column other than detail_refetched_at/
    # detail_refetch_count/geocode_attempted_at (pure sync-bookkeeping,
    # written on every daily/6-hourly pass regardless of real change)
    # actually changed, so the prerender pipeline's change-detection (issue
    # #80) doesn't see a false "changed" marker on every ingestion pass.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Organizer direct-submission fields (Phase 1). NULL for every
    # scraper-ingested event. See CLAUDE.md Data Flow for the submit ->
    # inline classify -> inline publish -> post-hoc review lifecycle.
    submitted_by_organizer_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("organizers.id", ondelete="SET NULL"),
        nullable=True,
    )
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )
    # Why a cancelled event was cancelled — NULL for events cancelled before
    # this column existed (no backfill of historical rows) and for events
    # that were never cancelled. See VALID_EVENT_CANCELLATION_REASONS.
    cancellation_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)

    sources: Mapped[list["EventSource"]] = relationship(back_populates="event")
    classification: Mapped["EventClassification | None"] = relationship(
        back_populates="event", uselist=False
    )
    feedback: Mapped[list["UserEventFeedback"]] = relationship(back_populates="event")
    scores: Mapped[list["UserEventScore"]] = relationship(back_populates="event")
    reports: Mapped[list["EventReport"]] = relationship(back_populates="event")


class EventSource(Base):
    __tablename__ = "event_sources"
    __table_args__ = (
        Index(
            "ix_event_sources_source_external",
            "source_id",
            "external_id",
            unique=True,
        ),
        # Backs the NOT EXISTS(event_id=...) correlated subquery in
        # refetch.py::_select_candidates (organizer-submission exclusion) —
        # without it that lookup is a per-candidate sequential scan.
        Index("ix_event_sources_event_id", "event_id"),
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
        Index(
            "ix_event_classifications_vibes",
            "vibes",
            postgresql_using="gin",
        ),
        # ORDER BY quality_score DESC NULLS LAST — public.py showcase,
        # browse.py's quality sort (Path A) and For-you pool ordering, and the
        # publish gate's quality_score >= PUBLISH_MIN_QUALITY_SCORE subquery.
        Index("ix_event_classifications_quality_score", "quality_score"),
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


class EventReport(Base):
    """A user-filed report that an event is inappropriate — distinct from
    UserEventFeedback (like/dislike/bookmark) and the organizer-submission
    review queue (needs_review)."""

    __tablename__ = "event_reports"
    __table_args__ = (
        Index(
            "uq_event_reports_user_event",
            "user_id",
            "event_id",
            unique=True,
        ),
        Index(
            "ix_event_reports_open_event",
            "event_id",
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_event_reports_event_created", "event_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    is_illegal_allegation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'open'"), default="open"
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship()
    event: Mapped["Event"] = relationship(back_populates="reports")


# ---------------------------------------------------------------------------
# Feedback & Feeds
# ---------------------------------------------------------------------------


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
    __table_args__ = (
        UniqueConstraint("user_id", "event_id"),
        # cleanup.py's UserEventScore.event_id.in_(ended_event_ids) leads with
        # event_id — the UniqueConstraint above only backs (user_id, event_id),
        # leading with user_id, so this table (the largest by row count) was
        # seq-scanned by that weekly cleanup query without this.
        Index("ix_user_event_scores_event_id", "event_id"),
    )

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
    __table_args__ = (
        UniqueConstraint("user_id", "feed_date"),
        # cleanup.py's DailyFeed.feed_date < cutoff has no user_id filter — the
        # UniqueConstraint above leads with user_id, so this indexless-for-that-
        # predicate query was unusable by it.
        Index("ix_daily_feeds_feed_date", "feed_date"),
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
        # ix_llm_calls_task_created leads with `task`, so the retention
        # cleanup's date-only predicate (no task filter) can't range-scan it.
        Index("ix_llm_calls_created_at", "created_at"),
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


# ---------------------------------------------------------------------------
# Admin Audit Log
# ---------------------------------------------------------------------------


class AdminAction(Base):
    """Append-only durable record of a destructive/moderation admin action
    (takedown, retract, approve, resolve reports, pipeline run) — the report
    feature carries legal obligations that generally assume this is
    reconstructible after the fact (see docs/research/ on report-feature
    legal duties). Written inside the same transaction as the mutation it
    records where the endpoint has one open; survives an outage of the
    LOG_SHIP_URL log drain, unlike the structured log line alone. There is no
    admins table (see ADR 0001), so there is no actor column — "a login
    happened" is the only fact the admin auth model asserts."""

    __tablename__ = "admin_actions"
    __table_args__ = (Index("ix_admin_actions_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
