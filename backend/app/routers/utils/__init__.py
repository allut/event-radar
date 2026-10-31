"""Shared serialization helpers for event routers."""

import logging
from collections.abc import Callable
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app._generated.shared_constants import (
    LOCALE_EN,
    LOCALE_RU,
    ORGANIZER_MAX_CATEGORIES,
    PROMOTION_ERROR_REQUEST_DAILY_LIMIT,
    VALID_CATEGORIES,
)
from app.constants.claims import (
    CLAIM_DNS_TXT_RECORD_LABEL,
    CLAIM_DNS_VERIFICATION_MECHANISMS,
    ERROR_CLAIM_EDIT_CATEGORIES_CAP,
)
from app.constants.core import LOCALE_ET, TALLINN_TZ
from app.constants.events import (
    EVENT_STATUS_CANCELLED,
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
    PRICE_MAX_VALUE,
)
from app.constants.organizer import (
    ERROR_IMAGE_HOST_NOT_ALLOWED,
    ERROR_VENUE_NOT_FOUND,
)
from app.constants.promotions import (
    PROMOTION_ADVERTISER_NAME_MAX_CHARS,
    PROMOTION_BILLING_EMAIL_MAX_CHARS,
    PROMOTION_CONFLICT_ERROR_CODES,
    PROMOTION_INVOICE_REFERENCE_MAX_LEN,
    PROMOTION_NOTE_MAX_CHARS,
    PROMOTION_REGISTRY_CODE_MAX_LEN,
)
from app.constants.reports import (
    ERROR_INVALID_REPORT_REASON,
    VALID_REPORT_REASONS,
)
from app.constants.security import (
    ORGANIZER_HTML_SANITIZE_ALLOWED_ATTRS,
    ORGANIZER_HTML_SANITIZE_ALLOWED_TAGS,
)
from app.events.queries import event_not_ended_filter
from app.ingestion.content_filters import content_flags, localized_text_values
from app.ingestion.http_client import own_cloudinary_url
from app.ingestion.pricing import normalize_currency
from app.ingestion.sanitize import sanitize_html
from app.promotions.grant import PromotionRefused
from app.models.events import Event, EventClassification
from app.models.organizers import Venue

log = logging.getLogger(__name__)


PriceField = Annotated[float, Field(ge=0, lt=PRICE_MAX_VALUE, allow_inf_nan=False)]
"""Every request-body price_* field. events.price_* are Numeric(10,2), so an
unbounded float (or JSON's Infinity) overflows into a DataError 500 — the same
bound ingest enforces through parse_bounded_price (OWASP audit M-6)."""


async def replace_organizer_categories(
    db: AsyncSession, event_id: int, categories: list[str]
) -> None:
    """Set an event's classification categories to exactly the organizer's picks.

    Used for an organizer's own submissions (create + edit): their set is
    authoritative, so LLM-derived categories are dropped rather than merged —
    keeping them would inflate persona affinity, which sums weights over every
    category (`_affinity_for_vector`). If no classification row exists yet
    (e.g. classify_event's LLM call failed), a bare one is created so the pick
    isn't silently dropped."""
    classification = await db.scalar(
        select(EventClassification).where(EventClassification.event_id == event_id)
    )
    if classification is None:
        db.add(EventClassification(event_id=event_id, categories=categories))
        return
    classification.categories = categories


async def prepend_organizer_categories(
    db: AsyncSession,
    event_id: int,
    categories: list[str],
    max_total: int | None = None,
) -> None:
    """Prepend organizer-chosen categories onto an event's classification.

    Used by claim edits (#416's prepend-only rule): the claimed event's
    existing categories are never removed. The picks lead the list in the
    order given (those already present are skipped), existing categories
    follow; a bare classification row is created if none exists yet.

    `max_total` caps the resulting list: if adding the genuinely new picks
    would exceed it, 422 and nothing is changed. Existing categories are
    never trimmed, so an event already over the cap simply can't gain more."""
    classification = await db.scalar(
        select(EventClassification).where(EventClassification.event_id == event_id)
    )
    existing = classification.categories if classification is not None else []
    new = [c for c in categories if c not in existing]
    if max_total is not None and new and len(existing) + len(new) > max_total:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_CLAIM_EDIT_CATEGORIES_CAP,
        )
    if classification is None:
        db.add(EventClassification(event_id=event_id, categories=categories))
        return
    if new:
        classification.categories = [*new, *existing]


def validate_tz_aware(v: datetime | None) -> datetime | None:
    """Shared by organizer_events.py's SubmitEventBody/PatchEventBody
    starts_at/ends_at validators."""
    if v is not None and v.tzinfo is None:
        raise ValueError("must be timezone-aware")
    return v


def validate_categories(v: list[str] | None) -> list[str] | None:
    """Shared by organizer_events.py's SubmitEventBody/PatchEventBody and
    organizer_claim_edits.py's ClaimEditBody `categories` validators. Dedupes
    (order kept) before applying the ORGANIZER_MAX_CATEGORIES cap."""
    if v is None:
        return None
    for c in v:
        if c not in VALID_CATEGORIES:
            raise ValueError(f"invalid category: {c!r}")
    deduped = list(dict.fromkeys(v))
    if len(deduped) > ORGANIZER_MAX_CATEGORIES:
        raise ValueError(f"at most {ORGANIZER_MAX_CATEGORIES} categories")
    return deduped


def fold_legacy_category(data: Any) -> Any:
    """`mode="before"` model-validator body: fold the deprecated single
    `category` key into `categories`. Frontend (Cloudflare) and backend
    (Render) deploy separately, so an old frontend may still send `category`;
    without this it would be silently dropped as an unknown field. An explicit
    `categories` wins. Remove in a follow-up once no old frontend is live."""
    if isinstance(data, dict) and "category" in data:
        data = dict(data)
        legacy = data.pop("category")
        if "categories" not in data and legacy is not None:
            data["categories"] = [legacy]
    return data


def validate_price_ordering(
    price_min: float | None, price_max: float | None
) -> None:
    """Shared by organizer_events.py's SubmitEventBody/PatchEventBody and
    organizer_venues.py's VenueBody/VenuePatchBody `price_min > price_max`
    ordering check."""
    if price_min is not None and price_max is not None and price_min > price_max:
        raise ValueError("price_min must not be greater than price_max")


def validate_time_ordering(starts_at: datetime | None, ends_at: datetime | None) -> None:
    """Shared by organizer_events.py's SubmitEventBody/PatchEventBody and
    organizer_claim_edits.py's PatchClaimEventBody `ends_at < starts_at`
    ordering check. Both-present only — a patch touching just one of the pair
    can't be checked against the other without a DB round-trip."""
    if starts_at is not None and ends_at is not None and ends_at < starts_at:
        raise ValueError("ends_at must not be before starts_at")


def organizer_sanitize(text: str | None) -> str | None:
    """sanitize_html at the organizer-submission boundary (#267) — the
    narrower Tiptap-tracking allowlist, not the shared ingestion one. Shared
    by organizer_events.py and organizer_claim_edits.py."""
    return sanitize_html(
        text,
        tags=ORGANIZER_HTML_SANITIZE_ALLOWED_TAGS,
        attrs=ORGANIZER_HTML_SANITIZE_ALLOWED_ATTRS,
    )


def localized_dict(
    et: str | None, en: str | None, ru: str | None
) -> dict[str, str] | None:
    """Build a {locale: value} JSONB dict from locale-suffixed request fields,
    dropping absent locales. et is required upstream (see title validation)."""
    out = {
        loc: val
        for loc, val in ((LOCALE_ET, et), (LOCALE_EN, en), (LOCALE_RU, ru))
        if val is not None and val.strip()
    }
    return out or None


def merged_localized(
    existing: dict[str, str] | None,
    orig: str | None,
    body: BaseModel,
    fields_set: set[str],
    base: str,
    *,
    sanitize: Callable[[str | None], str | None] | None = None,
) -> dict[str, str] | None:
    """Rebuild a ``*_localized`` column for a PATCH: a locale present in
    ``fields_set`` (``{base}_en`` / ``{base}_ru`` on ``body``) takes the
    request value (optionally passed through ``sanitize``); an absent one
    keeps its ``existing`` value. ``orig`` is the et/original text."""
    existing = existing or {}
    values = []
    for loc in (LOCALE_EN, LOCALE_RU):
        field = f"{base}_{loc}"
        if field in fields_set:
            value = getattr(body, field)
            values.append(sanitize(value) if sanitize is not None else value)
        else:
            values.append(existing.get(loc))
    return localized_dict(orig, *values)


def apply_price_edit(event: Event, body: Any, fields_set: set[str]) -> None:
    """Apply a PATCH's price_min/price_max/currency to ``event`` and
    re-normalize ``currency``: coerces a raw value and fills the default only
    when the event now carries a price, so a price-only PATCH doesn't leave
    currency NULL and an un-coerced value never lands on the String(3)
    column. Shared by organizer_events.py and organizer_claim_edits.py."""
    if "price_min" in fields_set:
        event.price_min = body.price_min
    if "price_max" in fields_set:
        event.price_max = body.price_max
    has_price = event.price_min is not None or event.price_max is not None
    raw_currency = body.currency if "currency" in fields_set else event.currency
    event.currency = normalize_currency(raw_currency, has_price)


def apply_moderation_flags(
    event: Event, venue_name: str | None, *extra_explicit_texts: str | None
) -> bool:
    """Recheck an organizer-edited event against the explicit/non-event
    keyword filters and set the flags. ``venue_name`` must be the resolved
    venue name (never the raw column, NULL for a venue-linked event); extra
    texts (e.g. ``important_info``) join the explicit scan. Returns True when
    either flag was newly set, so the caller can pull a published event back
    to classified."""
    # Every user-visible text, not just the Estonian originals: EN/RU readers
    # and the digest are served the *_localized values (OWASP audit M-5).
    extras = [
        *(t for t in extra_explicit_texts if t),
        event.important_info,
        *localized_text_values(
            event.title_localized,
            event.description_localized,
            event.important_info_localized,
        ),
    ]
    is_explicit, is_non_event = content_flags(
        event.title_orig, event.description_orig, venue_name, None, extras
    )
    flagged = False
    if is_explicit and not event.is_explicit:
        event.is_explicit = True
        flagged = True
    if is_non_event and not event.is_non_event:
        event.is_non_event = True
        flagged = True
    return flagged


async def remoderate_venue_linked_events(db: AsyncSession, venue: Venue) -> None:
    """A saved venue's name/address is resolved onto every event linked to it
    at read time (``resolve_venue_name()``), so renaming the venue changes the
    text shown on already-published events without passing the submit path's
    explicit/non-event checks (OWASP audit #5). Rescan every live linked event
    against the venue's new names, pull a newly flagged published event back to
    classified, and queue them all for post-hoc admin review like any other
    organizer edit. One query regardless of how many events link the venue.
    The caller commits."""
    events = (
        await db.scalars(
            select(Event).where(
                Event.venue_id == venue.id,
                Event.status != EVENT_STATUS_CANCELLED,
                event_not_ended_filter(datetime.now(TALLINN_TZ)),
            )
        )
    ).all()
    for event in events:
        event.needs_review = True
        if (
            apply_moderation_flags(
                event, venue.name, venue.name_en, venue.name_ru, event.important_info
            )
            and event.status == EVENT_STATUS_PUBLISHED
        ):
            event.status = EVENT_STATUS_CLASSIFIED


def validate_report_reason(reason: str) -> None:
    """Shared by POST /reports and GET /admin/reports's ``reason`` filter —
    a single source of truth for the taxonomy check and its error message."""
    if reason not in VALID_REPORT_REASONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_INVALID_REPORT_REASON.format(reasons=sorted(VALID_REPORT_REASONS)),
        )


async def own_venue_or_404(db: AsyncSession, venue_id: int, organizer_id: int) -> Venue:
    """Shared by organizer_events.py and organizer_venues.py — 404-not-403
    ownership check for a saved Venue, mirroring organizer_events.py's own
    ``_own_event_or_404`` convention."""
    venue = await db.scalar(
        select(Venue).where(
            Venue.id == venue_id,
            Venue.organizer_id == organizer_id,
            Venue.deleted_at.is_(None),
        )
    )
    if venue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_VENUE_NOT_FOUND
        )
    return venue


def claim_dns_record_name(mechanism: str | None, domain: str | None) -> str | None:
    """The TXT record name a DNS-TXT/Piletilevi-promoter claim's organizer is
    told to add (#412/#413) — shared by the organizer-facing pending screen
    (organizer_claims.py) and the admin claims queue (admin.py, #420) so the
    two never disagree on the record name shown for the same claim."""
    if mechanism in CLAIM_DNS_VERIFICATION_MECHANISMS and domain:
        return f"{CLAIM_DNS_TXT_RECORD_LABEL}.{domain}"
    return None


def check_image_host(image_url: str | None) -> str | None:
    """Reject an organizer-submission or claim-edit image_url that isn't one of OUR signed
    Cloudinary uploads (``own_cloudinary_url``) and return its re-serialized
    form (None for empty). Parser-differential spellings (``\\``, userinfo,
    ports) are refused up front by ``safe_render_url`` and the stored value is
    its re-serialized form (OWASP audit M-1)."""
    if not image_url:
        return None
    safe = own_cloudinary_url(image_url)
    if safe is not None:
        return safe
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_IMAGE_HOST_NOT_ALLOWED,
    )


def promotion_refusal(refused: PromotionRefused) -> HTTPException:
    """409 when the state of things forbids the command, 429 for the daily
    request ceiling, 422 for bad input; `detail.errors` lists every rule
    broken."""
    codes = [v.code for v in refused.violations]
    if any(c in PROMOTION_CONFLICT_ERROR_CODES for c in codes):
        code = status.HTTP_409_CONFLICT
    elif PROMOTION_ERROR_REQUEST_DAILY_LIMIT in codes:
        code = status.HTTP_429_TOO_MANY_REQUESTS
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(
        status_code=code,
        detail={
            "code": refused.violations[0].code,
            "message": refused.violations[0].message,
            "errors": [v.as_dict() for v in refused.violations],
        },
    )


class PromotionGrantBody(BaseModel):
    start_date: date
    end_date: date
    advertiser_legal_name: str = Field(max_length=PROMOTION_ADVERTISER_NAME_MAX_CHARS)
    advertiser_registry_code: str = Field(max_length=PROMOTION_REGISTRY_CODE_MAX_LEN)
    billing_email: EmailStr | None = Field(
        default=None, max_length=PROMOTION_BILLING_EMAIL_MAX_CHARS
    )
    is_complimentary: bool = False
    complimentary_note: str | None = Field(default=None, max_length=PROMOTION_NOTE_MAX_CHARS)
    invoice_reference: str | None = Field(default=None, max_length=PROMOTION_INVOICE_REFERENCE_MAX_LEN)
    # Required (both) when the event carries a Promotion restriction (#612).
    restriction_clearance_confirmed: bool = False
    restriction_clearance_note: str | None = Field(default=None, max_length=PROMOTION_NOTE_MAX_CHARS)
