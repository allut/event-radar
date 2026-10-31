from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.events import Event
    from app.models.organizers import Organizer


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
        Index(
            "uq_promotions_stripe_checkout_session_id",
            "stripe_checkout_session_id",
            unique=True,
            postgresql_where=text("stripe_checkout_session_id IS NOT NULL"),
        ),
        Index(
            "ix_promotions_stripe_payment_intent_id",
            "stripe_payment_intent_id",
            postgresql_where=text("stripe_payment_intent_id IS NOT NULL"),
        ),
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
    # Card checkout (#618). A manual or complimentary Promotion leaves all NULL.
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_invoice_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checkout_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invoice_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What the Organizer attested and accepted at checkout, and which wording.
    content_policy_attested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_policy_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # The Organizer's statement that the registry code is its own business, at
    # card checkout. A Promotion granted from a request keeps it on that request
    # (source_request_id); a direct grant and an older checkout leave it NULL.
    business_attested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terms_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
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
    # NULL on a request made before the business attestation existed.
    business_attested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    event: Mapped["Event"] = relationship()
    organizer: Mapped["Organizer"] = relationship()


class StripeCustomer(Base):
    """The Stripe Customer an Organizer pays as for one registry code (#618),
    so a repeat checkout reuses it instead of creating another."""

    __tablename__ = "stripe_customers"
    __table_args__ = (
        UniqueConstraint("organizer_id", "registry_code", name="uq_stripe_customers_organizer_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organizer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizers.id", ondelete="CASCADE"), nullable=False
    )
    registry_code: Mapped[str] = mapped_column(String(32), nullable=False)
    stripe_customer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # What Stripe last got, so a repeat checkout updates the Customer only on
    # a change. NULL on rows from before #628: the next checkout fills them.
    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProcessedStripeEvent(Base):
    """A Stripe event id the webhook has handled (#618): a replay finds its id
    here and changes nothing."""

    __tablename__ = "processed_stripe_events"

    stripe_event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


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
