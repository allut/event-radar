from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    FetchedValue,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants.events import (
    EVENT_SEARCH_TEXT_SQL,
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_DRAFT,
    EVENT_STATUS_PUBLISHED,
)
from app.constants.reports import REPORT_STATUS_OPEN
from app.db import Base

if TYPE_CHECKING:
    from app.models.claims import Publisher
    from app.models.feeds import UserEventFeedback
    from app.models.ingestion import Source
    from app.models.organizers import Venue
    from app.models.users import User


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_starts_at_status", "starts_at", "status"),
        Index("ix_events_dedup_group_id", "dedup_group_id"),
        # Created by migration 0002 but was missing here — a create_all-built
        # schema (tests) lacked it until this declaration was added back.
        Index("ix_events_status", "status"),
        # Series-claim lookup by serialized key (M6, migration 0052).
        Index("ix_events_series_key_starts_at", "series_key", "starts_at"),
        # Explore keyword search (`ILIKE '%q%'`) can't use a B-tree on a
        # leading wildcard; trigram GIN indexes accelerate it. Requires the
        # pg_trgm extension (enabled in migration 0020).
        Index(
            "ix_events_title_orig_trgm",
            "title_orig",
            postgresql_using="gin",
            postgresql_ops={"title_orig": "gin_trgm_ops"},
        ),
        # Claim-discovery search (M9): one trigram index over the combined
        # title haystack (constants.EVENT_SEARCH_TEXT_SQL) and one over url
        # (suggestions' domain ILIKE). Migration 0051.
        Index(
            "ix_events_search_text_trgm",
            text(f"({EVENT_SEARCH_TEXT_SQL}) gin_trgm_ops"),
            postgresql_using="gin",
        ),
        Index(
            "ix_events_url_trgm",
            text("url gin_trgm_ops"),
            postgresql_using="gin",
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
        # event_not_ended_filter()/event_ended_filter()'s coalesce(ends_at,
        # starts_at) comparison can't use a plain B-tree — this expression
        # index backs it (and _date_range_filter's identical coalesce(ends_at,
        # starts_at) >= date_from_start in browse.py), on the largest table in
        # the schema, which grows forever since events rows are never deleted.
        Index(
            "ix_events_live_until",
            text("coalesce(ends_at, starts_at)"),
        ),
        # publish_pending's UPDATE: live rows still 'classified'. Rejects never
        # leave that status, so the status index alone walks all of them
        # (Big-O audit P4, migration 0070).
        Index(
            "ix_events_classified_live_until",
            text("coalesce(ends_at, starts_at)"),
            postgresql_where=text(f"status = '{EVENT_STATUS_CLASSIFIED}'"),
        ),
        # ORDER BY events.price_min ASC NULLS LAST (browse.py's price sort, Path A).
        Index("ix_events_price_min", "price_min"),
        Index("ix_events_venue_id", "venue_id"),
        # public_event_filter() (events/queries.py) is applied on every public read path;
        # is_explicit/is_non_event had no index at all, so both were a heap
        # filter after status narrowed the scan. Partial on starts_at — the
        # dominant sort/range column on the public read paths that apply this
        # filter (Big-O audit #5, item 2.9).
        Index(
            "ix_events_public_starts_at",
            "starts_at",
            postgresql_where=text(
                f"status = '{EVENT_STATUS_PUBLISHED}'"
                " AND NOT is_explicit AND NOT is_non_event"
            ),
        ),
        # events/queries.py's free_filter() OR-arm (has_free_tier IS TRUE) — the other
        # arm (price_min = 0) is already covered by ix_events_price_min.
        Index(
            "ix_events_has_free_tier",
            "has_free_tier",
            postgresql_where=text("has_free_tier"),
        ),
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
    # A saved organizer Venue this event was submitted against (#176). When
    # set, venue_name/venue_address are left NULL at write time — the FK
    # becomes the sole venue source for the event going forward (read-path
    # join/resolution is #177, not this ticket).
    venue_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("venues.id", ondelete="SET NULL"), nullable=True
    )
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
    # First time the detail-refetch saw the source page gone (404/410); cleared
    # by any later successful fetch. Sync bookkeeping, untracked by the
    # updated_at trigger like geocode_attempted_at.
    source_gone_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Cooldown clock for the venue-extract sub-pass: stamped when the LLM
    # decided a suspect venue_name carries no street address. Sync bookkeeping,
    # untracked by the updated_at trigger like geocode_attempted_at.
    venue_extract_attempted_at: Mapped[datetime | None] = mapped_column(
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
    # detail_refetch_count/geocode_attempted_at/venue_extract_attempted_at/
    # source_gone_since (pure sync-bookkeeping,
    # written on every daily/6-hourly pass regardless of real change)
    # actually changed, so the prerender pipeline's change-detection (issue
    # #80) doesn't see a false "changed" marker on every ingestion pass.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Organizer direct-submission fields (Phase 1). NULL for every
    # scraper-ingested event. See docs/organizer-portal.md for the submit ->
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
    # Fields a claim (#409/#410) has pinned against overwrite by ingestion/
    # detail-refetch. Entries are field names, or "<field>:<locale>" for a
    # per-locale text field (title_localized/description_localized/
    # important_info_localized). Price fields (price_min/price_max/currency/
    # has_free_tier) never participate — see CONTEXT.md's Event Claiming
    # glossary and issue #410.
    pinned_fields: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )

    # serialize_event_series_key(event_series_key(title_orig, resolved venue
    # name)), maintained by DB triggers (migration 0052) — never written by
    # the app. NULL only on a row the trigger hasn't touched (create_all test
    # schemas have no trigger).
    series_key: Mapped[str | None] = mapped_column(
        Text, nullable=True, server_default=FetchedValue()
    )

    # Content-policy assessment for Promotions: NULL = unassessed, "none" =
    # clear, otherwise a restricted category. Nothing sets it yet (the
    # content-policy ticket does). Untracked by the updated_at trigger, like
    # all Promotion bookkeeping: starting or ending a Promotion never moves
    # the event's change marker.
    promotion_restriction: Mapped[str | None] = mapped_column(String(16), nullable=True)

    sources: Mapped[list["EventSource"]] = relationship(back_populates="event")
    classification: Mapped["EventClassification | None"] = relationship(
        back_populates="event", uselist=False
    )
    feedback: Mapped[list["UserEventFeedback"]] = relationship(back_populates="event")
    reports: Mapped[list["EventReport"]] = relationship(back_populates="event")
    venue: Mapped["Venue | None"] = relationship()


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
        # Publisher -> freshest listing lookups (claims/pinning.py,
        # claims/lifecycle.py, claims/target_resolution.py::bulk_resolve_publisher_events)
        # filter publisher_id and take the highest id; INCLUDE(event_id)
        # makes them index-only (Big-O audit H2).
        Index(
            "ix_event_sources_publisher_id",
            "publisher_id",
            "id",
            postgresql_include=["event_id"],
        ),
        # publish.py::_stamp_missing_fienta_publishers: one source's rows with
        # no publisher yet (Big-O audit P4, migration 0070).
        Index(
            "ix_event_sources_unstamped",
            "source_id",
            "event_id",
            postgresql_where=text("publisher_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Resolved Publisher this listing traces back to (#409/#410). NULL when
    # the source has no resolvable publisher identity yet.
    publisher_id: Mapped[int | None] = mapped_column(
        ForeignKey("publishers.id", ondelete="SET NULL"), nullable=True
    )

    # Last live organizer re-query that failed to resolve publisher_id; the
    # backfill honours PUBLISHER_RESOLVE_RETRY_COOLDOWN against it.
    publisher_resolve_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    event: Mapped["Event"] = relationship(back_populates="sources")
    source: Mapped["Source"] = relationship(back_populates="event_sources")
    publisher: Mapped["Publisher | None"] = relationship()


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
        # Descending with NULLS LAST to match that order (migration 0070).
        Index(
            "ix_event_classifications_quality_score",
            text("quality_score DESC NULLS LAST"),
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
            postgresql_where=text(f"status = '{REPORT_STATUS_OPEN}'"),
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
        String(20),
        nullable=False,
        server_default=text(f"'{REPORT_STATUS_OPEN}'"),
        default=REPORT_STATUS_OPEN,
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
