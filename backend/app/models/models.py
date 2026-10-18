from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    FetchedValue,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
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

from app._generated.shared_constants import DEFAULT_USER_CITY, DEFAULT_USER_LOCALE
from app.constants.claims import CLAIM_STATUS_APPROVED, CLAIM_STATUS_PENDING
from app.constants.events import (
    EVENT_SEARCH_TEXT_SQL,
    EVENT_STATUS_DRAFT,
    EVENT_STATUS_PUBLISHED,
)
from app.constants.ingestion import PUBLISHER_STATUS_ACTIVE
from app.constants.ranking import (
    PASSIVE_SIGNALS_SQL_PREDICATE,
    PREFERENCE_SIGNALS_SQL_PREDICATE,
)
from app.constants.reports import REPORT_STATUS_OPEN
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
    __table_args__ = (
        # Serves send_daily_digests' opted-in-population query (email/digest.py)
        # as an index-only scan instead of a full-table seq scan (Big-O audit M6).
        Index(
            "ix_users_digest_eligible",
            "id",
            postgresql_where=text("email_digest_opt_in AND email_verified"),
        ),
    )

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
    # Opt-in: new users start off and choose at onboarding (GDPR Art. 4(11)
    # consent needs an affirmative act). Rows created before 0059 keep "true".
    email_digest_opt_in: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # Email ad consent (app/email/consent.py): the fast gate at send time, plus
    # the wording version consented to. Starts off; subscribing is never consent.
    email_ad_consent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    email_ad_consent_version: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True
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
    # Set when this magic link was sent to confirm a pending Google-identity
    # link (ADR 0002) rather than to start a session — the sub is written
    # into user_identities only once the link is used.
    pending_google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship(back_populates="magic_links")


class UserIdentity(Base):
    """A linked external sign-in provider identity (ADR 0002) — e.g. Google's
    stable `sub`. Never shared with organizer_identities: the same Google
    account may hold both a User row and an Organizer row that never merge
    (docs/security.md "Auth", track separation)."""

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_sub"),
        Index("ix_user_identities_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_sub: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship()


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
    # per docs/organizer-portal.md "Organizer Settings".
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Durable "has authenticated" signal (mirrors User.email_verified). The
    # weekly cleanup prunes organizers where this is NULL; magic-link rows are
    # themselves pruned, so they can't serve as that evidence.
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
    # Set when this magic link was sent to confirm a pending Google-identity
    # link (ADR 0002) rather than to start a session — mirrors
    # AuthMagicLink.pending_google_sub.
    pending_google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)

    organizer: Mapped["Organizer"] = relationship(back_populates="magic_links")


class OrganizerIdentity(Base):
    """Mirrors UserIdentity for the organizer auth track — see its docstring
    for why this is a separate table rather than a shared one."""

    __tablename__ = "organizer_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_sub"),
        Index("ix_organizer_identities_organizer_id", "organizer_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organizer_id: Mapped[int] = mapped_column(
        ForeignKey("organizers.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_sub: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    organizer: Mapped["Organizer"] = relationship()


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
        # Composite, not single-column: the daily-cap count query filters on
        # both organizer_id and created_at, and this table has no retention
        # sweep (see class docstring), so a single-column index leaves
        # created_at as a heap filter over the organizer's entire history —
        # same treatment events.submitted_by_organizer_id got in 0023 (Big-O
        # audit #5, item 2.9).
        Index("ix_organizer_image_uploads_organizer_created", "organizer_id", "created_at"),
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
    (docs/organizer-portal.md, #173). name/name_en/name_ru mirror the
    Persona per-locale-column pattern rather than Event's JSONB
    localized-field pattern, since a venue has no ingestion path that fills
    locales piecemeal. address is a single non-localized column — street
    names don't translate across locales. price_min/price_max/currency are
    copy-in defaults for a submission form, not authoritative pricing — the
    Event row created from a venue owns its own price fields.
    geocode_attempted_at is a separate cooldown clock from Event's own
    column of the same name."""

    __tablename__ = "venues"
    # (organizer_id, created_at) serves both the per-organizer list and the
    # daily-cap count in organizer_venues.py (Big-O audit L); supersedes the
    # bare organizer_id index.
    __table_args__ = (
        Index("ix_venues_organizer_created", "organizer_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organizer_id: Mapped[int] = mapped_column(
        ForeignKey("organizers.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_ru: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
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


class Publisher(Base):
    """The real-world entity an event-claiming Claim is granted against — see
    CONTEXT.md's Event Claiming glossary. One per Fienta organizer id, the
    whole source for KUMU/Estonia Concert Hall (external_id NULL), or one per
    resolved Piletilevi promoter id. Distinct from `Organizer` (the portal
    account that holds a claim)."""

    __tablename__ = "publishers"
    __table_args__ = (
        Index(
            "ix_publishers_source_external",
            "source_id",
            "external_id",
            unique=True,
        ),
        # Postgres unique indexes don't treat NULL as a duplicate, so the
        # index above alone allows two KUMU/ECH-style constant rows
        # (external_id NULL) per source — this partial index closes that gap
        # for the one-per-source-with-no-external_id case (#411 review
        # finding).
        Index(
            "ix_publishers_source_null_external",
            "source_id",
            unique=True,
            postgresql_where=text("external_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text(f"'{PUBLISHER_STATUS_ACTIVE}'"),
        default=PUBLISHER_STATUS_ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source: Mapped["Source"] = relationship()


class Claim(Base):
    """An organizer's claim over a Publisher or an event series — see
    CONTEXT.md's Event Claiming glossary (Publisher claim / Series claim).
    Polymorphic over `kind`: a Publisher claim sets `publisher_id`, a Series
    claim sets `event_series_key` (the `event_series_key()` tuple from
    `events/queries.py`, serialized as `"<normalized_title>\\x1f<normalized_venue>"`)
    and always requires `justification` (#428 — a Series claim never
    auto-grants, so this is the claimant's only input at creation time)."""

    __tablename__ = "claims"
    __table_args__ = (
        Index("ix_claims_organizer_id", "organizer_id"),
        Index("ix_claims_publisher_id", "publisher_id"),
        # active_claim_for_target's Series arm (every public GET /events/{id})
        # filters event_series_key + status IN (pending, approved); the
        # approved-only unique index above can't serve the pending half.
        Index(
            "ix_claims_series_status",
            "event_series_key",
            "status",
            postgresql_where=text("event_series_key IS NOT NULL"),
        ),
        # Admin claims list: status filter + ORDER BY created_at.
        Index("ix_claims_status_created", "status", "created_at"),
        # Reject a duplicate/racing *approved* claim against the same
        # Publisher or Series at the DB layer (#431, slice 1 of #425) —
        # narrowed from pending-or-approved so multiple pending claims can
        # coexist on the same target (proof-preempts-assertion at auto-grant
        # time instead). Postgres unique indexes don't treat NULL as a
        # duplicate, so each is scoped to the rows that actually carry that
        # key, exactly like ix_publishers_source_null_external.
        Index(
            "ix_claims_active_publisher",
            "publisher_id",
            unique=True,
            postgresql_where=text(
                f"status = '{CLAIM_STATUS_APPROVED}' AND publisher_id IS NOT NULL"
            ),
        ),
        Index(
            "ix_claims_active_series",
            "event_series_key",
            unique=True,
            postgresql_where=text(
                f"status = '{CLAIM_STATUS_APPROVED}' AND event_series_key IS NOT NULL"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organizer_id: Mapped[int] = mapped_column(
        ForeignKey("organizers.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    publisher_id: Mapped[int | None] = mapped_column(
        ForeignKey("publishers.id"), nullable=True
    )
    event_series_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text(f"'{CLAIM_STATUS_PENDING}'"),
        default=CLAIM_STATUS_PENDING,
    )
    # #412's verdict for this claim — one of VALID_CLAIM_VERIFICATION_MECHANISMS.
    # NULL only for the brief window between insert and the inline
    # verification call that fills it in the same request (#413).
    verification_mechanism: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    # System-generated proof token (app/claims/fienta_token.py::generate_claim_token)
    # the organizer places in their listing/DNS — reused by every recheck.
    proof_token: Mapped[str] = mapped_column(String(64), nullable=False)
    # Domain the DNS-TXT check ran against (KUMU/ECH's hardcoded institutional
    # domain, or a Piletilevi promoter's resolved contact domain) — persisted
    # so the #415 pending screen can render "add this TXT record" without
    # re-resolving a Piletilevi promoter's domain on every page load. NULL for
    # the fienta_token/admin_review mechanisms, which have no domain to show.
    verification_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # (#428) The resolved Piletilevi promoter contact mailbox a
    # piletilevi_mailbox check compared the claimant's account email
    # against — persisted (match or mismatch) so the admin queue can show
    # both emails as evidence without re-resolving the promoter page. NULL
    # for every other mechanism.
    verification_contact: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # (#428) Organizer-supplied reason a Series claim was made — required
    # only for kind=CLAIM_KIND_SERIES (enforced in app/claims/lifecycle.py,
    # not a DB constraint, same pattern as verification_domain's
    # mechanism-conditional NULL-ness). NULL for a Publisher claim.
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Bumped at creation and by every POST .../recheck — expire_stale_claims
    # (app/claims/lifecycle.py) compares this, not created_at, against
    # CLAIM_EXPIRY_DAYS so an organizer actively retrying isn't expired out
    # from under them.
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Set once status leaves CLAIM_STATUS_PENDING (approved/cancelled/expired/
    # revoked) — NULL while pending.
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Set by dedup's canonical-selection pass (#418) when this claim's event
    # lost a claimed-vs-claimed collision to a better-quality duplicate —
    # its pins stop applying while dormant, but the row is never
    # deleted/revoked; re-cleared the moment this claim's target is
    # canonical again. Orthogonal to `status` (an APPROVED claim can be
    # dormant) — see CONTEXT.md's Event Claiming glossary.
    dormant: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )

    organizer: Mapped["Organizer"] = relationship()
    publisher: Mapped["Publisher | None"] = relationship()


class ClaimEditAttempt(Base):
    """One row per claim-editing-surface save attempt (#416) — backs the
    daily claim-edit cap, which counts attempts (not successful publishes)
    scoped per-organizer across every event they hold a claim on, mirroring
    how ORGANIZER_DAILY_SUBMISSION_CAP counts `Event` rows. The cap itself is
    ORGANIZER_DAILY_CLAIM_EDIT_CAP scaled by covered-event count (#438 — see
    claims/pinning.py::scaled_claim_edit_cap), not a flat constant. A
    dedicated table rather than reusing an existing one because no other row
    is written unconditionally on every claim-edit PATCH regardless of
    outcome."""

    __tablename__ = "claim_edit_attempts"
    __table_args__ = (
        Index("ix_claim_edit_attempts_organizer_created", "organizer_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organizer_id: Mapped[int] = mapped_column(
        ForeignKey("organizers.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


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
        # admin.py's event-inspector RawEvent↔EventSource join matches on
        # (source_id, external_id) — only (source_id, fetched_at) existed, so
        # external_id was a heap filter over the source's whole raw history
        # (Big-O audit #5, item 2.9).
        Index("ix_raw_events_source_external", "source_id", "external_id"),
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
# Promotions
# ---------------------------------------------------------------------------


class Promotion(Base):
    """A paid (or complimentary) window of whole Tallinn days during which one
    owned event may fill Sponsored slots. `status` is commercial only;
    scheduled / live / finished are computed from the window and today's
    Tallinn date (app/promotions/windows.py). See docs/data-model.md."""

    __tablename__ = "promotions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('unpaid', 'paid', 'ended_early', 'void')",
            name="ck_promotions_status",
        ),
        CheckConstraint("end_date >= start_date", name="ck_promotions_window_order"),
        CheckConstraint("days >= 1", name="ck_promotions_days_positive"),
        Index("ix_promotions_event_id", "event_id"),
        Index("ix_promotions_organizer_id", "organizer_id"),
        # Cap accounting and the list read promotions by window.
        Index("ix_promotions_status_window", "status", "start_date", "end_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("events.id", ondelete="RESTRICT"), nullable=False
    )
    # The owning Organizer resolved at grant time (a commercial snapshot; a
    # later ownership change is handled by the fill gate, not by rewriting it).
    organizer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizers.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # Inclusive Tallinn dates.
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    net_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    vat_rate_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    is_complimentary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )
    complimentary_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invoice_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Advertiser snapshot shown in the "REKLAAM" caption and invoiced to.
    advertiser_legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    advertiser_registry_code: Mapped[str] = mapped_column(String(32), nullable=False)
    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "admin" for a direct grant; NULL for checkout and system. There is no
    # admins table (ADR 0001), so no admin id.
    granted_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    end_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    refunded_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    refund_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Restriction clearance (#612): the Promotion restriction an admin
    # deliberately reviewed and cleared. It covers only that restriction.
    restriction_cleared: Mapped[str | None] = mapped_column(String(16), nullable=True)
    restriction_clearance_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    restriction_clearance_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    restriction_cleared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Distinct users the Daily 5 slot was stored for over the window. Recomputed
    # nightly by build_daily_feeds and frozen once the window has ended (#607).
    daily5_reach: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The Promotion request an admin granted this from (#615); NULL for a
    # direct grant.
    source_request_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promotion_requests.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    event: Mapped["Event"] = relationship()
    organizer: Mapped["Organizer"] = relationship()


class PromotionRequest(Base):
    """An Organizer's request for a Promotion on an event they own (#614). An
    admin grants it (creating the Promotion, #615) or declines it with a reason.
    `status` is pending | granted | declined | withdrawn | expired. At most one
    pending request per event (partial unique index). See docs/organizer-portal.md."""

    __tablename__ = "promotion_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'granted', 'declined', 'withdrawn', 'expired')",
            name="ck_promotion_requests_status",
        ),
        CheckConstraint("end_date >= start_date", name="ck_promotion_requests_window_order"),
        Index(
            "uq_promotion_requests_one_pending_per_event",
            "event_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_promotion_requests_organizer_id", "organizer_id", "created_at"),
        Index("ix_promotion_requests_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("events.id", ondelete="RESTRICT"), nullable=False
    )
    organizer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizers.id", ondelete="RESTRICT"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    advertiser_legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    advertiser_registry_code: Mapped[str] = mapped_column(String(32), nullable=False)
    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "admin" once an admin resolved it (no admins table, ADR 0001).
    resolved_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terms_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    terms_accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    event: Mapped["Event"] = relationship()
    organizer: Mapped["Organizer"] = relationship()


class PromotionDailyStat(Base):
    """Anonymous delivery totals for one Promotion on one Tallinn day (#606).
    Never pruned. No viewer identifiers: only counts. Written by the in-process
    counter's bulk upsert (app/promotions/counters.py) and, for the gate and
    Daily 5 / digest columns, by their own tickets. See docs/pipeline.md."""

    __tablename__ = "promotion_daily_stats"
    __table_args__ = (
        UniqueConstraint("promotion_id", "day", name="uq_promotion_daily_stats_promotion_day"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    promotion_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promotions.id", ondelete="RESTRICT"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    gate_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    gate_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    explore_served: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    daily5_placed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    digest_sent: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    web_opens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    digest_opens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    slot_dislikes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class DailySponsoredSlot(Base):
    """One user's Daily 5 Sponsored slot for one Tallinn day (#607). Kept apart
    from `daily_feeds` so no consent-free path can pick it up, and pruned on
    the same retention. `promotion_id` is NULL when a mid-day swap found
    nothing left, so the collapse sticks for the day. Feeds the Daily 5 slot,
    the digest slot, the 3-day cooldown and Daily 5 reach. See
    docs/pipeline.md."""

    __tablename__ = "daily_sponsored_slots"
    __table_args__ = (
        UniqueConstraint("user_id", "slot_date", name="uq_daily_sponsored_slots_user_date"),
        Index("ix_daily_sponsored_slots_slot_date", "slot_date"),
        Index("ix_daily_sponsored_slots_promotion_id", "promotion_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    slot_date: Mapped[date] = mapped_column(Date, nullable=False)
    promotion_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promotions.id", ondelete="RESTRICT"), nullable=True
    )
    is_swap: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )
    replaced_promotion_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promotions.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PromotionSnapshot(Base):
    """What a Promotion displayed at one moment: taken when it becomes paid
    and on every edit or re-point while scheduled or live. Append-only and
    never pruned, so an Organizer's or regulator's question about what ran can
    be answered after the event row has changed."""

    __tablename__ = "promotion_snapshots"
    __table_args__ = (Index("ix_promotion_snapshots_promotion_id", "promotion_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    promotion_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promotions.id", ondelete="RESTRICT"), nullable=False
    )
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    event_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title_et: Mapped[str | None] = mapped_column(Text, nullable=True)
    title_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    title_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    venue_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    event_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    net_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    vat_rate_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    label_text: Mapped[str] = mapped_column(Text, nullable=False)


# ---------------------------------------------------------------------------
# Admin Audit Log
# ---------------------------------------------------------------------------


class AdminAction(Base):
    """Append-only durable record of a destructive/moderation admin action
    (takedown, retract, approve, resolve reports, pipeline run) — the report
    feature carries legal obligations that generally assume this is
    reconstructible after the fact. Written inside the same transaction as the mutation it
    records where the endpoint has one open; survives an outage of the
    LOG_SHIP_URL log drain, unlike the structured log line alone. There is no
    admins table (see ADR 0001), so there is no actor column — "a login
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


class EmailAdConsentLog(Base):
    """Email ad consent record, append-only: one row per grant or withdrawal.
    Deleted with the account (FK cascade), after `account_deletion` is logged."""

    __tablename__ = "email_ad_consent_log"
    __table_args__ = (Index("ix_email_ad_consent_log_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    wording_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    locale: Mapped[str] = mapped_column(String(2), nullable=False)
