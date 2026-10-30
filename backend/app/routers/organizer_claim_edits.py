"""Claim-editing surface (#416): the dedicated pinned-field editor a granted
claimant uses to correct "their" event — distinct from EventSubmit, whose
form has no vocabulary for the pinned/synced field split. Locked entirely
until the claim is granted. See CONTEXT.md's Event Claiming glossary and
docs/organizer-portal.md.
"""

import logging
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.claims.lifecycle import ClaimError, own_claim_or_404
from app.claims.pinning import (
    apply_pins,
    claim_event_for_id,
    fetch_fresh_price,
    organizer_covered_event_count,
    pin_key,
    price_mismatch,
    scaled_claim_edit_cap,
)
from app._generated.shared_constants import (
    CLAIM_ERROR_CODE_DORMANT,
    CLAIM_ERROR_CODE_NOT_GRANTED,
    CLAIM_STATUS_APPROVED,
    LOCALE_EN,
    LOCALE_RU,
    ORGANIZER_MAX_CATEGORIES,
)
from app.constants.claims import (
    CLAIM_UNPIN_KEY_MAX_LEN,
    CLAIM_UNPIN_MAX_ITEMS,
    ERROR_CLAIM_DORMANT,
    ERROR_CLAIM_EDIT_URL_DOMAIN,
    ERROR_CLAIM_EVENT_NOT_FOUND,
    ERROR_CLAIM_NOT_GRANTED,
    ERROR_DAILY_CLAIM_EDIT_LIMIT,
)
from app.constants.core import LOCALE_ET, TALLINN_TZ
from app.constants.events import (
    ERROR_EVENT_CANCELLED,
    ERROR_EVENT_URL_SCHEME,
    EVENT_STATUS_CANCELLED,
    EVENT_STATUS_CLASSIFIED,
)
from app.constants.http import HTTP_TIMEOUT_SECONDS
from app.constants.organizer import (
    ORGANIZER_CURRENCY_MAX_LEN,
    ORGANIZER_DESCRIPTION_MAX_LEN,
    ORGANIZER_TITLE_MAX_LEN,
)
from app.constants.rate_limits import RATE_LIMIT_SUBMIT
from app.constants.security import URL_MAX_LEN
from app.db import get_db
from app.promotions.restriction import reassess_after_edit
from app.promotions.windows import now_tallinn
from app.ingestion.http_client import host_matches_domain, safe_render_url
from app.ingestion.pricing import normalize_currency
from app.models.models import ClaimEditAttempt, Event, Organizer
from app.publish import publish_pending
from app.rate_limit import limiter
from app.auth.dependencies import get_current_organizer
from app.routers.utils import (
    PriceField,
    apply_moderation_flags,
    apply_price_edit,
    check_image_host,
    fold_legacy_category,
    merged_localized,
    organizer_sanitize,
    prepend_organizer_categories,
    serialize_event,
    validate_categories,
    validate_price_ordering,
    validate_time_ordering,
    validate_tz_aware,
)
from app.events.queries import select_events_with_classification
from app.events.venue import resolve_venue_name

log = logging.getLogger(__name__)
router = APIRouter(prefix="/organizer/claims", tags=["organizer-claims"])


class PatchClaimEventBody(BaseModel):
    # Deploy-skew safety net only (#453) — the current frontend always
    # targets a specific covered event via the path
    # (PATCH /{claim_id}/events/{event_id}), never this field. Honored only
    # by the no-id route as a fallback for a browser tab still running a
    # pre-#453 cached bundle; the path-based route always uses its own path
    # parameter and ignores this field entirely.
    event_id: int | None = None
    title: str | None = Field(None, max_length=ORGANIZER_TITLE_MAX_LEN)
    title_en: str | None = Field(None, max_length=ORGANIZER_TITLE_MAX_LEN)
    title_ru: str | None = Field(None, max_length=ORGANIZER_TITLE_MAX_LEN)
    description: str | None = Field(None, max_length=ORGANIZER_DESCRIPTION_MAX_LEN)
    description_en: str | None = Field(None, max_length=ORGANIZER_DESCRIPTION_MAX_LEN)
    description_ru: str | None = Field(None, max_length=ORGANIZER_DESCRIPTION_MAX_LEN)
    image_url: str | None = Field(default=None, max_length=URL_MAX_LEN)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    url: str | None = Field(default=None, max_length=URL_MAX_LEN)
    categories: list[str] | None = None
    price_min: PriceField | None = None
    price_max: PriceField | None = None
    currency: str | None = Field(None, max_length=ORGANIZER_CURRENCY_MAX_LEN)
    has_free_tier: bool | None = None
    accept_new_price: bool = False
    # Field keys to hand back to automatic source syncing (pin_key() shape) —
    # applied before this request's own edits, so an edit to a field also
    # named here still ends up pinned (#416 acceptance: "an explicit un-pin
    # control hands a field back... without re-entering its original value",
    # which presumes the two are never sent together in practice).
    unpin: list[Annotated[str, Field(max_length=CLAIM_UNPIN_KEY_MAX_LEN)]] = Field(
        default_factory=list, max_length=CLAIM_UNPIN_MAX_ITEMS
    )

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _tz_aware(cls, v: datetime | None) -> datetime | None:
        return validate_tz_aware(v)

    @model_validator(mode="before")
    @classmethod
    def _fold_legacy_category(cls, data: Any) -> Any:
        return fold_legacy_category(data)

    @field_validator("categories")
    @classmethod
    def _valid_categories(cls, v: list[str] | None) -> list[str] | None:
        return validate_categories(v)

    @field_validator("title")
    @classmethod
    def _non_blank_title(cls, v: str | None) -> str | None:
        # Unlike description/url/image_url (nullable — clearing them is a
        # legitimate edit), title has no "empty" state: publish_pending's
        # gate already rejects a blank title, but rejecting it here instead
        # gives the organizer an immediate 422 rather than a save that
        # silently never republishes.
        if v is not None and not v.strip():
            raise ValueError("title must not be blank")
        return v

    @model_validator(mode="after")
    def _ordering(self) -> "PatchClaimEventBody":
        validate_time_ordering(self.starts_at, self.ends_at)
        validate_price_ordering(self.price_min, self.price_max)
        return self


async def _own_granted_claim_or_404(db: AsyncSession, claim_id: int, organizer_id: int):
    try:
        claim = await own_claim_or_404(db, claim_id, organizer_id)
    except ClaimError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.http_detail) from exc
    if claim.status != CLAIM_STATUS_APPROVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": ERROR_CLAIM_NOT_GRANTED, "code": CLAIM_ERROR_CODE_NOT_GRANTED},
        )
    # #422: a dormant claim lost a dedup collision to another claimed
    # duplicate — its pins stop applying, so editing must lock too (a save
    # here would just get silently reverted by the next refetch pass, per
    # bulk_dormant_pinned_event_ids in app/claims/lifecycle.py).
    if claim.dormant:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": ERROR_CLAIM_DORMANT, "code": CLAIM_ERROR_CODE_DORMANT},
        )
    return claim


async def _claim_event_or_404(db: AsyncSession, claim, event_id: int | None = None) -> Event:
    event = await claim_event_for_id(db, claim, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_CLAIM_EVENT_NOT_FOUND
        )
    return event


def _serialize_claim_event(event: Event, mismatch: dict | None) -> dict:
    """serialize_event() resolves title/description to one display-locale
    string — the editing surface needs the raw per-locale maps too (mirrors
    organizer_events.py::list_own_events, which layers the same three
    columns on for the identical reason: editing every locale independently,
    not just showing the resolved one)."""
    payload = serialize_event(event)
    payload["title_localized"] = event.title_localized
    payload["description_localized"] = event.description_localized
    payload["pinned_fields"] = list(event.pinned_fields)
    payload["price_mismatch"] = mismatch
    return payload


async def _load_claim_event(
    claim_id: int, event_id: int | None, current_organizer: Organizer, db: AsyncSession
) -> dict:
    """The claim-editing surface's load: current field values, which are
    pinned, and any price-mismatch diff (recomputed fresh on every load —
    #416 stores no persisted mismatch record). event_id (#437) targets one
    specific event covered by a Publisher claim's #436 event list; omitted,
    or on a Series claim, falls back to the single representative event."""
    claim = await _own_granted_claim_or_404(db, claim_id, current_organizer.id)
    event = await _claim_event_or_404(db, claim, event_id)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        fresh = await fetch_fresh_price(client, event)
    return _serialize_claim_event(event, price_mismatch(event, fresh))


@router.get("/{claim_id}/event")
@limiter.shared_limit(RATE_LIMIT_SUBMIT, scope="claim_event_get")
async def get_claim_event(
    claim_id: int,
    request: Request,
    event_id: int | None = None,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """No-id load: the single representative event (or Series-claim match).
    A specific covered event is loaded via GET /{claim_id}/events/{event_id}
    instead (#453) — a query-string id here (`...?event_id=...`) reads as an
    analytics-beacon URL shape and gets silently dropped by ad/tracker
    blockers (ERR_BLOCKED_BY_CLIENT), so the current frontend never sends
    this query param. It's still accepted and honored here as a deploy-skew
    safety net: a browser tab still running a pre-#453 cached bundle after a
    Cloudflare Pages deploy would otherwise have its `event_id` silently
    dropped, falling back to the representative event and applying an edit
    to the wrong one with no error at all — worse than the request simply
    failing. shared_limit keeps this and the path-based route (below) on one
    bucket, matching the single route this used to be."""
    return await _load_claim_event(claim_id, event_id, current_organizer, db)


@router.get("/{claim_id}/events/{event_id}")
@limiter.shared_limit(RATE_LIMIT_SUBMIT, scope="claim_event_get")
async def get_claim_event_by_id(
    claim_id: int,
    event_id: int,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Path-based load of one specific event covered by a Publisher claim
    (#437, moved off the query string by #453) — see _load_claim_event."""
    return await _load_claim_event(claim_id, event_id, current_organizer, db)


async def _claims_edited_today(db: AsyncSession, organizer_id: int) -> int:
    day_start = datetime.now(TALLINN_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        await db.scalar(
            select(func.count())
            .select_from(ClaimEditAttempt)
            .where(
                ClaimEditAttempt.organizer_id == organizer_id,
                ClaimEditAttempt.created_at >= day_start,
            )
        )
        or 0
    )


async def _save_claim_event(
    claim_id: int,
    event_id: int | None,
    body: PatchClaimEventBody,
    current_organizer: Organizer,
    db: AsyncSession,
) -> dict:
    """Save a claim edit: per-field pin/unpin, prepend-only categories, a
    url capped to the claim's verified domain, and price fields kept
    co-authoritative with no pin/unpin toggle. Resets status to 'classified'
    and synchronously re-runs the publish gate in the same request — a
    passing edit flips straight back to 'published'; a failing one is left
    at 'classified' with no retry job (#416). event_id targets one specific
    event covered by a Publisher claim (#437); None falls back to the single
    representative event, same as the GET load."""
    claim = await _own_granted_claim_or_404(db, claim_id, current_organizer.id)

    covered = await organizer_covered_event_count(db, current_organizer.id)
    cap = scaled_claim_edit_cap(covered)
    if await _claims_edited_today(db, current_organizer.id) >= cap:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=ERROR_DAILY_CLAIM_EDIT_LIMIT
        )
    # Counts this attempt regardless of outcome (ClaimEditAttempt docstring)
    # — committed now, in its own transaction, before any event mutation.
    # get_db's session has no implicit commit-on-exit, so without this eager
    # commit a later 4xx (unknown event, cancelled event, a bad url/image_url)
    # would roll the insert back along with everything else, silently
    # exempting failing requests from the cap.
    db.add(ClaimEditAttempt(organizer_id=current_organizer.id))
    await db.commit()

    event = await _claim_event_or_404(db, claim, event_id)
    if event.status == EVENT_STATUS_CANCELLED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_EVENT_CANCELLED)

    fields_set = body.model_fields_set
    pinned = set(event.pinned_fields)
    to_pin: set[str] = set()
    to_unpin = {k for k in body.unpin if isinstance(k, str)}

    if fields_set & {"title", "title_en", "title_ru"}:
        existing = event.title_localized or {}
        if "title" in fields_set and body.title is not None:
            event.title_orig = body.title
            to_pin.add(pin_key("title", LOCALE_ET))
        if "title_en" in fields_set:
            to_pin.add(pin_key("title", LOCALE_EN))
        if "title_ru" in fields_set:
            to_pin.add(pin_key("title", LOCALE_RU))
        event.title_localized = merged_localized(
            existing, event.title_orig, body, fields_set, "title"
        )
    if fields_set & {"description", "description_en", "description_ru"}:
        existing = event.description_localized or {}
        if "description" in fields_set:
            event.description_orig = organizer_sanitize(body.description)
            to_pin.add(pin_key("description", LOCALE_ET))
        if "description_en" in fields_set:
            to_pin.add(pin_key("description", LOCALE_EN))
        if "description_ru" in fields_set:
            to_pin.add(pin_key("description", LOCALE_RU))
        event.description_localized = merged_localized(
            existing,
            event.description_orig,
            body,
            fields_set,
            "description",
            sanitize=organizer_sanitize,
        )

    if "image_url" in fields_set:
        event.image_url = check_image_host(body.image_url)
        to_pin.add(pin_key("image_url"))

    if "starts_at" in fields_set and body.starts_at is not None:
        event.starts_at = body.starts_at
        to_pin.add(pin_key("starts_at"))
    if "ends_at" in fields_set:
        event.ends_at = body.ends_at
        to_pin.add(pin_key("ends_at"))

    if "url" in fields_set:
        allowed_domain = claim.verification_domain or (
            urlparse(event.url).hostname if event.url else None
        )
        if body.url:
            # Validate + re-serialize FIRST, then pin the host of the stored
            # form: urlparse and a browser disagree on "\\"/userinfo spellings
            # (OWASP audit M-1), so the host we check must be the host we render.
            safe_url = safe_render_url(body.url)
            if not safe_url:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_EVENT_URL_SCHEME
                )
            candidate_host = urlparse(safe_url).hostname
            if (
                allowed_domain is None
                or candidate_host is None
                or not host_matches_domain(candidate_host, allowed_domain)
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_CLAIM_EDIT_URL_DOMAIN
                )
            event.url = safe_url
        else:
            event.url = None
        to_pin.add(pin_key("url"))

    if "categories" in fields_set and body.categories:
        await prepend_organizer_categories(
            db, event.id, body.categories, max_total=ORGANIZER_MAX_CATEGORIES
        )

    # FAQ #claimed-edits describes this behaviour — update the copy (all locales) if it changes
    # Price fields: co-authoritative, never pinned (#416 — CONTEXT.md's Event
    # Claiming glossary). accept_new_price adopts a freshly recomputed ingest
    # price instead of whatever price_* the request body carried — the only
    # case this save needs to fetch the source detail page at all; an
    # unrelated edit (title, dates, ...) must not pay for an outbound
    # third-party request it has nothing to do with.
    fresh = None
    if body.accept_new_price:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            fresh = await fetch_fresh_price(client, event)
        if fresh is not None:
            event.price_min = fresh.price_min
            event.price_max = fresh.price_max
            has_price = fresh.price_min is not None or fresh.price_max is not None
            event.currency = normalize_currency(fresh.currency, has_price)
            if fresh.has_free_tier:
                event.has_free_tier = True
    elif fields_set & {"price_min", "price_max", "currency", "has_free_tier"}:
        apply_price_edit(event, body, fields_set)
        if "has_free_tier" in fields_set and body.has_free_tier is not None:
            event.has_free_tier = body.has_free_tier

    event.pinned_fields = apply_pins(list(pinned), pin=to_pin, unpin=to_unpin)

    moderated_venue_name = resolve_venue_name(event)
    apply_moderation_flags(event, moderated_venue_name)

    event.status = EVENT_STATUS_CLASSIFIED
    saved_event_id = event.id
    # Re-assess the Promotion restriction on this edit (#612), best-effort.
    await reassess_after_edit(db, event, now_tallinn())
    await publish_pending(db, event_ids=[saved_event_id], diagnostics=False)
    final_status = await db.scalar(select(Event.status).where(Event.id == saved_event_id))
    await db.commit()

    reloaded = await db.scalar(
        select_events_with_classification().where(Event.id == saved_event_id)
    )
    assert reloaded is not None  # just-updated row, guaranteed present
    mismatch = price_mismatch(reloaded, fresh)
    return {**_serialize_claim_event(reloaded, mismatch), "status": final_status}


@router.patch("/{claim_id}/event")
@limiter.shared_limit(RATE_LIMIT_SUBMIT, scope="claim_event_patch")
async def update_claim_event(
    claim_id: int,
    body: PatchClaimEventBody,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """No-id save: targets the single representative event (or Series-claim
    match) — see _save_claim_event. A specific covered event is saved via
    PATCH /{claim_id}/events/{event_id} instead (#453). Falls back to
    body.event_id (deploy-skew safety net — see PatchClaimEventBody) when
    present, rather than silently misapplying the edit to the representative
    event instead of the one a stale client meant. shared_limit keeps this
    and the path-based route (below) on one bucket, matching the single
    route this used to be."""
    return await _save_claim_event(claim_id, body.event_id, body, current_organizer, db)


@router.patch("/{claim_id}/events/{event_id}")
@limiter.shared_limit(RATE_LIMIT_SUBMIT, scope="claim_event_patch")
async def update_claim_event_by_id(
    claim_id: int,
    event_id: int,
    body: PatchClaimEventBody,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Path-based save of one specific event covered by a Publisher claim
    (#437, moved off the query string by #453) — see _save_claim_event."""
    return await _save_claim_event(claim_id, event_id, body, current_organizer, db)
