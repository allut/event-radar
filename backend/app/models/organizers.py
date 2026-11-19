from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app._generated.shared_constants import DEFAULT_USER_LOCALE
from app.db import Base
from app.models.types import CIText


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
    # link rather than to start a session — mirrors
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
    (#173). name/name_en/name_ru mirror the
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
