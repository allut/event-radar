from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app._generated.shared_constants import DEFAULT_USER_CITY, DEFAULT_USER_LOCALE
from app.db import Base
from app.models.types import CIText

if TYPE_CHECKING:
    from app.models.feeds import DailyFeed, UserEventFeedback


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
