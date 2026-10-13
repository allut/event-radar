"""Organizer event submission — own-events CRUD + inline classify/publish.

A submitted event is inserted on the adapter-less `user_submission` source
(app/ingestion/registry.py) via the shared insert_normalized_event() helper,
then pushed inline through classify_event()+publish_pending() so it goes live
within the request instead of waiting for the next scheduled pass. It is
flagged needs_review so it still surfaces in the Phase-2 admin review queue
after going live (auto-publish + retractable post-hoc review — see
docs/organizer-portal.md).
"""

import hashlib
import logging
import time
from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app._generated.shared_constants import (
    BROWSE_PAGE_SIZE,
    IMAGE_UPLOAD_ALLOWED_MIME,
    PAGINATION_MAX_OFFSET,
)
from app.constants.core import TALLINN_TZ
from app.constants.events import (
    ERROR_EVENT_CANCELLED,
    ERROR_EVENT_NOT_FOUND,
    ERROR_EVENT_URL_SCHEME,
    EVENT_CANCELLATION_REASON_ORGANIZER_RETRACT,
    EVENT_STATUS_CANCELLED,
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
)
from app.constants.http import HTTP_TIMEOUT_SECONDS
from app.constants.ingestion import SOURCE_SLUG_USER_SUBMISSION
from app.constants.organizer import (
    CLOUDINARY_UPLOAD_URL_TEMPLATE,
    ERROR_DAILY_IMAGE_UPLOAD_LIMIT,
    ERROR_DAILY_SUBMISSION_LIMIT,
    ERROR_EVENT_CREATE_FAILED,
    ERROR_IMAGE_TOO_LARGE,
    ERROR_IMAGE_UPLOAD_FAILED,
    ERROR_IMAGE_UPLOAD_NOT_CONFIGURED,
    ERROR_IMAGE_URL_SCHEME,
    ERROR_SUBMISSION_SOURCE_NOT_CONFIGURED,
    ERROR_UNSUPPORTED_IMAGE_TYPE,
    IMAGE_EXTENSION_BY_MIME,
    IMAGE_MAGIC_BYTES,
    IMAGE_UPLOAD_MAX_BYTES,
    MIME_IMAGE_WEBP,
    ORGANIZER_CURRENCY_MAX_LEN,
    ORGANIZER_DAILY_IMAGE_UPLOAD_CAP,
    ORGANIZER_DAILY_SUBMISSION_CAP,
    ORGANIZER_DESCRIPTION_MAX_LEN,
    ORGANIZER_IMPORTANT_INFO_MAX_LEN,
    ORGANIZER_SUBMISSION_EXTERNAL_ID_PREFIX,
    ORGANIZER_TITLE_MAX_LEN,
    ORGANIZER_VENUE_ADDRESS_MAX_LEN,
    ORGANIZER_VENUE_NAME_MAX_LEN,
    WEBP_FOURCC,
    WEBP_FOURCC_OFFSET,
    WEBP_RIFF_MAGIC,
)
from app.constants.ranking import (
    BROWSE_MAX_PAGE_SIZE,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
)
from app.constants.rate_limits import RATE_LIMIT_BROWSE, RATE_LIMIT_SUBMIT
from app.constants.reports import REPORT_AUTO_RESOLVE_NOTE
from app.constants.security import URL_MAX_LEN
from app.db import get_db
from app.ingestion.adapter import NormalizedEvent, insert_normalized_event
from app.ingestion.content_filters import content_flags
from app.ingestion.http_client import http_post, safe_render_url
from app.ingestion.pricing import normalize_currency
from app.llm.classifier import classify_event
from app.models.models import (
    Event,
    Organizer,
    OrganizerImageUpload,
    Source,
    Venue,
)
from app.publish import publish_pending
from app.rate_limit import limiter
from app.auth.dependencies import get_current_organizer
from app.events.cancellation import (
    cancel_event_and_resolve_reports,
    send_report_resolution_emails,
)
from app.routers.utils import (
    apply_moderation_flags,
    apply_price_edit,
    check_image_host,
    fold_legacy_category,
    localized_dict,
    merged_localized,
    organizer_sanitize,
    own_venue_or_404,
    replace_organizer_categories,
    resolve_locale_param,
    serialize_event,
    validate_categories,
    validate_price_ordering,
    validate_time_ordering,
    validate_tz_aware,
)
from app.events.queries import select_events_with_classification

log = logging.getLogger(__name__)
# Stays under /organizer/* deliberately: ORGANIZER_SESSION_COOKIE_PATH (app/
# constants/auth.py) scopes the organizer_session cookie to Path=/api/organizer —
# a route added outside that prefix would silently never receive the cookie
# and 401 on every call, however correct get_current_organizer's logic is.
router = APIRouter(prefix="/organizer/events", tags=["organizer-events"])


class SubmitEventBody(BaseModel):
    title: str = Field(..., max_length=ORGANIZER_TITLE_MAX_LEN)
    title_en: str | None = Field(None, max_length=ORGANIZER_TITLE_MAX_LEN)
    title_ru: str | None = Field(None, max_length=ORGANIZER_TITLE_MAX_LEN)
    description: str | None = Field(None, max_length=ORGANIZER_DESCRIPTION_MAX_LEN)
    description_en: str | None = Field(None, max_length=ORGANIZER_DESCRIPTION_MAX_LEN)
    description_ru: str | None = Field(None, max_length=ORGANIZER_DESCRIPTION_MAX_LEN)
    important_info: str | None = Field(
        None, max_length=ORGANIZER_IMPORTANT_INFO_MAX_LEN
    )
    important_info_en: str | None = Field(
        None, max_length=ORGANIZER_IMPORTANT_INFO_MAX_LEN
    )
    important_info_ru: str | None = Field(
        None, max_length=ORGANIZER_IMPORTANT_INFO_MAX_LEN
    )
    starts_at: datetime
    ends_at: datetime | None = None
    venue_name: str | None = Field(None, max_length=ORGANIZER_VENUE_NAME_MAX_LEN)
    venue_address: str | None = Field(None, max_length=ORGANIZER_VENUE_ADDRESS_MAX_LEN)
    venue_id: int | None = None
    url: str | None = Field(default=None, max_length=URL_MAX_LEN)
    image_url: str | None = Field(default=None, max_length=URL_MAX_LEN)
    price_min: float | None = Field(None, ge=0)
    price_max: float | None = Field(None, ge=0)
    currency: str | None = Field(None, max_length=ORGANIZER_CURRENCY_MAX_LEN)
    categories: list[str] | None = None

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

    @model_validator(mode="after")
    def _ordering(self) -> "SubmitEventBody":
        validate_time_ordering(self.starts_at, self.ends_at)
        validate_price_ordering(self.price_min, self.price_max)
        return self


class PatchEventBody(BaseModel):
    title: str | None = Field(None, max_length=ORGANIZER_TITLE_MAX_LEN)
    title_en: str | None = Field(None, max_length=ORGANIZER_TITLE_MAX_LEN)
    title_ru: str | None = Field(None, max_length=ORGANIZER_TITLE_MAX_LEN)
    description: str | None = Field(None, max_length=ORGANIZER_DESCRIPTION_MAX_LEN)
    description_en: str | None = Field(None, max_length=ORGANIZER_DESCRIPTION_MAX_LEN)
    description_ru: str | None = Field(None, max_length=ORGANIZER_DESCRIPTION_MAX_LEN)
    important_info: str | None = Field(
        None, max_length=ORGANIZER_IMPORTANT_INFO_MAX_LEN
    )
    important_info_en: str | None = Field(
        None, max_length=ORGANIZER_IMPORTANT_INFO_MAX_LEN
    )
    important_info_ru: str | None = Field(
        None, max_length=ORGANIZER_IMPORTANT_INFO_MAX_LEN
    )
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    venue_name: str | None = Field(None, max_length=ORGANIZER_VENUE_NAME_MAX_LEN)
    venue_address: str | None = Field(None, max_length=ORGANIZER_VENUE_ADDRESS_MAX_LEN)
    venue_id: int | None = None
    url: str | None = Field(default=None, max_length=URL_MAX_LEN)
    image_url: str | None = Field(default=None, max_length=URL_MAX_LEN)
    price_min: float | None = Field(None, ge=0)
    price_max: float | None = Field(None, ge=0)
    currency: str | None = Field(None, max_length=ORGANIZER_CURRENCY_MAX_LEN)
    categories: list[str] | None = None

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

    @model_validator(mode="after")
    def _ordering(self) -> "PatchEventBody":
        # Both-present check only — a patch touching just one of the pair can't
        # be validated against the other without a DB round-trip, and this
        # model has no DB access; the create-time check (SubmitEventBody)
        # already guarantees ends_at >= starts_at at row creation.
        validate_time_ordering(self.starts_at, self.ends_at)
        validate_price_ordering(self.price_min, self.price_max)
        return self


async def _get_user_submission_source(db: AsyncSession) -> Source:
    source = await db.scalar(
        select(Source).where(Source.slug == SOURCE_SLUG_USER_SUBMISSION)
    )
    if source is None:
        # Seeded at startup by seed_sources() — absence means the app never
        # booted with the current registry.py, not a caller error.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ERROR_SUBMISSION_SOURCE_NOT_CONFIGURED,
        )
    return source


async def _own_event_or_404(
    db: AsyncSession, event_id: int, organizer_id: int
) -> Event:
    event = await db.scalar(
        select(Event).where(
            Event.id == event_id, Event.submitted_by_organizer_id == organizer_id
        )
    )
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_EVENT_NOT_FOUND
        )
    return event


@router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT_SUBMIT)
async def submit_event(
    body: SubmitEventBody,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Submit a new event: insert on user_submission, classify + publish inline,
    flag for post-hoc admin review. Daily submission cap is per-organizer
    (DB-backed, since @limiter.limit is IP-keyed and can't enforce that) —
    best-effort: the count-then-insert has no row lock, so concurrent
    requests from the same organizer could exceed the cap by a small margin.
    Accepted as an anti-abuse soft ceiling, not a hard guarantee."""
    day_start = datetime.now(TALLINN_TZ).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    submitted_today = (
        await db.scalar(
            select(func.count())
            .select_from(Event)
            .where(
                Event.submitted_by_organizer_id == current_organizer.id,
                Event.created_at >= day_start,
            )
        )
        or 0
    )
    if submitted_today >= ORGANIZER_DAILY_SUBMISSION_CAP:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=ERROR_DAILY_SUBMISSION_LIMIT,
        )

    source = await _get_user_submission_source(db)
    image_url = check_image_host(body.image_url)
    url = safe_render_url(body.url)
    if body.url and not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_EVENT_URL_SCHEME,
        )

    venue: Venue | None = None
    if body.venue_id is not None:
        venue = await own_venue_or_404(db, body.venue_id, current_organizer.id)

    has_price = body.price_min is not None or body.price_max is not None
    description = organizer_sanitize(body.description)
    important_info = organizer_sanitize(body.important_info)
    normalized = NormalizedEvent(
        external_id=f"{ORGANIZER_SUBMISSION_EXTERNAL_ID_PREFIX}{current_organizer.id}:{uuid4()}",
        title=body.title,
        starts_at=body.starts_at,
        description=description,
        important_info=important_info,
        ends_at=body.ends_at,
        # A saved venue_id is the sole venue source going forward — the
        # free-typed venue_name/venue_address are dropped at write time even
        # if the organizer also sent them (#176).
        venue_name=body.venue_name if body.venue_id is None else None,
        venue_address=body.venue_address if body.venue_id is None else None,
        lat=None,
        lng=None,
        # insert_normalized_event applies safe_external_url (scheme-only) for
        # a user_submission source, not the host-pinned safe_fetchable_url —
        # this event.url is never fetched server-side (refetch.py excludes
        # organizer submissions), so it's render-only like image_url.
        url=url,
        image_url=image_url,
        price_min=body.price_min,
        price_max=body.price_max,
        currency=normalize_currency(body.currency, has_price),
        title_localized=localized_dict(body.title, body.title_en, body.title_ru),
        description_localized=localized_dict(
            description,
            organizer_sanitize(body.description_en),
            organizer_sanitize(body.description_ru),
        ),
        important_info_localized=localized_dict(
            important_info,
            organizer_sanitize(body.important_info_en),
            organizer_sanitize(body.important_info_ru),
        ),
    )

    event = await insert_normalized_event(db, source, normalized)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_EVENT_CREATE_FAILED,
        )
    # insert_normalized_event silently drops a url/image_url the SSRF/scheme
    # guards reject (host not in ALLOWED_SOURCE_HOSTS, bad scheme) — give the
    # organizer an explicit error instead of a silently-vanished field.
    if body.url and not event.url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_EVENT_URL_SCHEME,
        )
    if body.image_url and not event.image_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_IMAGE_URL_SCHEME,
        )

    event.submitted_by_organizer_id = current_organizer.id
    event.venue_id = body.venue_id
    # Populate the relationship in-memory too: classify_event's prompt builder
    # resolves the venue name via event.venue, and an unloaded async lazy load
    # would raise MissingGreenlet.
    event.venue = venue
    event.needs_review = True
    # Capture into plain values before publish_pending(): its bulk UPDATE
    # (WHERE Event.id IN (subquery)) can't use the ORM's "evaluate"
    # synchronize_session strategy and falls back to "fetch", which expires
    # every matched in-session object — including this one, on exactly the
    # happy path where the new event clears the publish gate. Touching an
    # expired attribute afterward would raise MissingGreenlet under the async
    # session (see app/ingestion/adapter.py's commit()-vs-rollback() comment
    # for the same underlying pitfall).
    event_id = event.id
    event_slug = event.slug

    if venue is not None:
        # event.venue_name/venue_address were written NULL (FK is the sole
        # venue source, #176) — insert_normalized_event's Layer-1 keyword
        # prefilter therefore never scanned the venue's real text. Recheck it
        # here so a saved venue's name can't carry unmoderated explicit/
        # non-event content past the flags insert_normalized_event set.
        venue_explicit, venue_non_event = content_flags(
            None, None, venue.name, None, [venue.name_en, venue.name_ru]
        )
        if venue_explicit:
            event.is_explicit = True
        if venue_non_event:
            event.is_non_event = True
    classify_ok = await classify_event(event, db)
    if not classify_ok:
        # LLM outage (every provider failed) — event stays draft, distinct
        # from the normal "not yet reviewed" case; classify_pending's 6h
        # backlog drain will retry it, but this is worth surfacing in ops.
        log.warning("organizer submission event_id=%d classify failed", event.id)
    if body.categories:
        await replace_organizer_categories(db, event_id, body.categories)
    # Single known event, verified status unchanged by this call — scope the
    # UPDATE to it and skip the reject-breakdown diagnostic (unused here, and
    # its cost grows with all-time reject history — see publish_pending()).
    await publish_pending(db, event_ids=[event_id], diagnostics=False)
    final_status = await db.scalar(select(Event.status).where(Event.id == event_id))
    await db.commit()

    return {"id": event_id, "slug": event_slug, "status": final_status}


@router.patch("/{event_id}")
@limiter.limit(RATE_LIMIT_SUBMIT)
async def update_own_event(
    event_id: int,
    body: PatchEventBody,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Edit an own submitted event. Stays live but re-flags for review and
    re-runs the NSFW/non-event content checks (mirrors
    ingestion/refetch.py::_reconcile_venue_name's demote-on-newly-flagged
    behavior) — a clean edit never demotes a published event, but a newly
    unsafe one is pulled back to classified so the publish gate keeps it out
    of the public feed."""
    event = await _own_event_or_404(db, event_id, current_organizer.id)
    if event.status == EVENT_STATUS_CANCELLED:
        # A takedown (admin_takedown_reported_event) is the decisive action
        # for content that had to come down — the organizer must not be able
        # to change the stored content behind that decision after the fact.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=ERROR_EVENT_CANCELLED
        )

    fields_set = body.model_fields_set
    if "title" in fields_set and body.title is not None:
        event.title_orig = body.title
    if "starts_at" in fields_set and body.starts_at is not None:
        event.starts_at = body.starts_at
    if "ends_at" in fields_set:
        event.ends_at = body.ends_at
    linked_venue: Venue | None = None
    if "venue_id" in fields_set and body.venue_id is not None:
        linked_venue = await own_venue_or_404(db, body.venue_id, current_organizer.id)
        event.venue_id = body.venue_id
        event.venue_name = None
        event.venue_address = None
    elif "venue_id" in fields_set and body.venue_id is None:
        # Explicit unlink back to the free-typed path — venue_name/address
        # below (if present in the same patch) then repopulate it.
        event.venue_id = None
    # Gate on the post-update FK state, not just whether this request touched
    # venue_id — otherwise a later PATCH sending only venue_name on an
    # already-linked event (venue_id untouched this request, still set from a
    # prior one) would silently leave both venue_id and venue_name set,
    # violating the "FK is the sole venue source" rule (#176).
    if "venue_name" in fields_set and event.venue_id is None:
        event.venue_name = body.venue_name
    if "venue_address" in fields_set and event.venue_id is None:
        event.venue_address = body.venue_address
    if "url" in fields_set:
        # Same scheme-only guard insert_normalized_event applies at submit
        # time — this event.url is never fetched server-side (refetch.py
        # excludes organizer submissions), so it needs no host pin.
        safe_url = safe_render_url(body.url)
        if body.url and not safe_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_EVENT_URL_SCHEME,
            )
        event.url = safe_url
    if "image_url" in fields_set:
        event.image_url = check_image_host(body.image_url)
    if fields_set & {"price_min", "price_max", "currency"}:
        apply_price_edit(event, body, fields_set)
    # Empty list is a no-op: the LLM set a replace overwrote can't be restored,
    # so an edit must never leave an event uncategorized.
    if "categories" in fields_set and body.categories:
        await replace_organizer_categories(db, event.id, body.categories)
    if "description" in fields_set:
        event.description_orig = organizer_sanitize(body.description)
    if "important_info" in fields_set:
        event.important_info = organizer_sanitize(body.important_info)

    if fields_set & {"title", "title_en", "title_ru"}:
        event.title_localized = merged_localized(
            event.title_localized, event.title_orig, body, fields_set, "title"
        )
    if fields_set & {"description", "description_en", "description_ru"}:
        event.description_localized = merged_localized(
            event.description_localized,
            event.description_orig,
            body,
            fields_set,
            "description",
            sanitize=organizer_sanitize,
        )
    if fields_set & {"important_info", "important_info_en", "important_info_ru"}:
        event.important_info_localized = merged_localized(
            event.important_info_localized,
            event.important_info,
            body,
            fields_set,
            "important_info",
            sanitize=organizer_sanitize,
        )

    event.needs_review = True

    # event.venue_name is NULL whenever the event is linked to a saved venue
    # (#176) — scan the venue's real name/address instead so a linked venue
    # can't carry unmoderated explicit/non-event text past these checks.
    # linked_venue only covers a venue_id set in *this* request; an event
    # already linked from an earlier one still needs its venue looked up.
    if event.venue_id is not None and linked_venue is None:
        linked_venue = await db.get(Venue, event.venue_id)
    moderated_venue_name = linked_venue.name if linked_venue else event.venue_name

    if apply_moderation_flags(
        event,
        moderated_venue_name,
        linked_venue.name_en if linked_venue else None,
        linked_venue.name_ru if linked_venue else None,
    ) and event.status == EVENT_STATUS_PUBLISHED:
        event.status = EVENT_STATUS_CLASSIFIED

    await db.commit()
    return {"id": event.id, "slug": event.slug, "status": event.status}


@router.delete("/{event_id}")
@limiter.limit(RATE_LIMIT_SUBMIT)
async def delete_own_event(
    event_id: int,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Soft-delete: cancel the event. Events are never hard-deleted
    (docs/backend-ops.md "Data Retention")."""
    event = await _own_event_or_404(db, event_id, current_organizer.id)
    resolved = await cancel_event_and_resolve_reports(
        db, event, EVENT_CANCELLATION_REASON_ORGANIZER_RETRACT, REPORT_AUTO_RESOLVE_NOTE
    )
    await db.commit()
    await send_report_resolution_emails(
        db, event, resolved, REPORT_AUTO_RESOLVE_NOTE
    )
    return {"id": event.id, "status": event.status}


@router.get("")
# Browse rate, not the submit rate (spec #551): the dashboard's numbered
# pager plus edit round-trips are reads, and 10/minute 429'd quick paging.
@limiter.limit(RATE_LIMIT_BROWSE)
async def list_own_events(
    request: Request,
    limit: int = BROWSE_PAGE_SIZE,
    offset: int = 0,
    locale: str | None = Query(None),
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List the organizer's own submitted events, most recent first, with
    the paging envelope (total/limit/offset/has_more) on every page.
    Cancelled (soft-deleted) events stay listed."""
    limit = max(PAGINATION_MIN_LIMIT, min(limit, BROWSE_MAX_PAGE_SIZE))
    offset = max(PAGINATION_MIN_OFFSET, min(offset, PAGINATION_MAX_OFFSET))
    effective_locale = resolve_locale_param(locale, current_organizer.locale)
    own = Event.submitted_by_organizer_id == current_organizer.id

    total = (await db.scalar(select(func.count(Event.id)).where(own))) or 0
    stmt = (
        select_events_with_classification()
        .where(own)
        # id breaks created_at ties so a row never repeats or vanishes
        # between pages.
        .order_by(Event.created_at.desc(), Event.id.desc())
        .limit(limit)
        .offset(offset)
    )
    events = (await db.scalars(stmt)).all()
    return {
        "events": [_serialize_own_event(e, effective_locale) for e in events],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(events) < total,
    }


def _serialize_own_event(event: Event, locale: str) -> dict:
    """serialize_event() is built for public read paths (published-only) and
    never includes status — an organizer's own dashboard/edit form needs to
    tell draft/classified/published/cancelled apart, so layer it on here.
    Shared by the list and single-event reads so their shapes cannot drift."""
    return {
        **serialize_event(event, locale=locale),
        "status": event.status,
        "needs_review": event.needs_review,
        "venue_id": event.venue_id,
        "title_localized": event.title_localized,
        "description_localized": event.description_localized,
        "important_info_localized": event.important_info_localized,
    }


@router.get("/{event_id}")
@limiter.limit(RATE_LIMIT_SUBMIT)
async def get_own_event(
    event_id: int,
    request: Request,
    locale: str | None = Query(None),
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One of the organizer's own submitted events, same shape as a
    ``GET /organizer/events`` row. Feeds the edit form's prefill so any event —
    not just the dashboard list's first page — can be edited. 404 (not 403) on
    another organizer's event, matching PATCH/DELETE."""
    effective_locale = resolve_locale_param(locale, current_organizer.locale)
    event = await db.scalar(
        select_events_with_classification().where(
            Event.id == event_id,
            Event.submitted_by_organizer_id == current_organizer.id,
        )
    )
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_EVENT_NOT_FOUND
        )
    return _serialize_own_event(event, effective_locale)


def _cloudinary_signature(params: dict[str, str | int], api_secret: str) -> str:
    """Cloudinary signed-upload signature: SHA-256 over the sorted
    `key=value&...` param string with the API secret appended — per
    https://cloudinary.com/documentation/authentication_signatures. Only
    params actually sent to the upload API are signed; `file`, `cloud_name`,
    `resource_type`, and `api_key` are excluded per that spec. The digest
    algorithm itself must match what the Cloudinary account accepts (both
    SHA-1 and SHA-256 by default) — `signature_algorithm` is an SDK-side
    config knob only, never a wire param, and must not be signed or sent."""
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.sha256((to_sign + api_secret).encode()).hexdigest()


def _sniff_image_mime(body: bytes) -> str | None:
    """Detect the real image format from its leading bytes rather than
    trusting file.content_type, which is a value the client writes into its
    own multipart headers and this endpoint otherwise never verifies before
    forwarding the bytes to Cloudinary."""
    for magic, mime in IMAGE_MAGIC_BYTES.items():
        if body.startswith(magic):
            return mime
    fourcc_end = WEBP_FOURCC_OFFSET + len(WEBP_FOURCC)
    if body[:4] == WEBP_RIFF_MAGIC and body[WEBP_FOURCC_OFFSET:fourcc_end] == WEBP_FOURCC:
        return MIME_IMAGE_WEBP
    return None


@router.post("/image")
@limiter.limit(RATE_LIMIT_SUBMIT)
async def upload_event_image(
    request: Request,
    file: UploadFile = File(...),
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload an event image to Cloudinary via a signed server-side upload —
    the API secret never reaches the SPA, unlike an unsigned upload preset.
    Returns {url: secure_url} for the organizer to pass as image_url on
    submit/edit. Log-only/501 when Cloudinary is unconfigured, mirroring
    app/email/contact.py's RESEND_API_KEY fallback — dev without keys still
    runs."""
    if file.content_type not in IMAGE_UPLOAD_ALLOWED_MIME:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=ERROR_UNSUPPORTED_IMAGE_TYPE.format(content_type=file.content_type),
        )

    # ORGANIZER_DAILY_SUBMISSION_CAP counts Event.created_at, which can't cover
    # this route — an upload can happen before the organizer ever completes a
    # submission. Same count-then-act soft ceiling (no row lock): concurrent
    # requests from one organizer could overshoot slightly. Protects Cloudinary
    # free-tier quota, not the request itself.
    day_start = datetime.now(TALLINN_TZ).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    uploaded_today = (
        await db.scalar(
            select(func.count())
            .select_from(OrganizerImageUpload)
            .where(
                OrganizerImageUpload.organizer_id == current_organizer.id,
                OrganizerImageUpload.created_at >= day_start,
            )
        )
        or 0
    )
    if uploaded_today >= ORGANIZER_DAILY_IMAGE_UPLOAD_CAP:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=ERROR_DAILY_IMAGE_UPLOAD_LIMIT,
        )

    # Starlette has already spooled the full multipart body by the time this
    # handler runs (this cap only bounds what the handler itself holds, not
    # what was received). app.main.MaxBodySizeMiddleware bounds the earlier,
    # ASGI-server-wide stage (MAX_REQUEST_BODY_BYTES); this narrower check
    # stays as the image-specific limit.
    body = await file.read(IMAGE_UPLOAD_MAX_BYTES + 1)
    if len(body) > IMAGE_UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=ERROR_IMAGE_TOO_LARGE.format(max_bytes=IMAGE_UPLOAD_MAX_BYTES),
        )

    # Authoritative type check: file.content_type is client-asserted and
    # otherwise never verified against the actual bytes before they leave
    # this system for Cloudinary. The earlier content_type check above is
    # only a fast-path rejection of an obviously wrong header.
    sniffed_mime = _sniff_image_mime(body)
    if sniffed_mime is None or sniffed_mime not in IMAGE_UPLOAD_ALLOWED_MIME:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=ERROR_UNSUPPORTED_IMAGE_TYPE.format(content_type=file.content_type),
        )

    if not (
        settings.CLOUDINARY_CLOUD_NAME
        and settings.CLOUDINARY_API_KEY
        and settings.CLOUDINARY_API_SECRET
    ):
        log.warning(
            "Cloudinary not configured — image upload skipped (organizer_id=%d)",
            current_organizer.id,
        )
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=ERROR_IMAGE_UPLOAD_NOT_CONFIGURED,
        )

    timestamp = int(time.time())
    signature = _cloudinary_signature(
        {"timestamp": timestamp},
        settings.CLOUDINARY_API_SECRET,
    )
    upload_url = CLOUDINARY_UPLOAD_URL_TEMPLATE.format(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME
    )
    # Generated rather than file.filename — nothing downstream reads the
    # upload filename, and it is attacker-controlled text otherwise crossing
    # a service boundary unchanged.
    generated_filename = f"{uuid4().hex}.{IMAGE_EXTENSION_BY_MIME[sniffed_mime]}"

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        try:
            resp = await http_post(
                client,
                upload_url,
                data={
                    "api_key": settings.CLOUDINARY_API_KEY,
                    "timestamp": timestamp,
                    "signature": signature,
                },
                files={"file": (generated_filename, body, sniffed_mime)},
            )
        except httpx.HTTPError as exc:
            upstream_status = (
                exc.response.status_code
                if isinstance(exc, httpx.HTTPStatusError)
                else None
            )
            log.exception(
                "Cloudinary upload failed (organizer_id=%d, upstream_status=%s)",
                current_organizer.id,
                upstream_status,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=ERROR_IMAGE_UPLOAD_FAILED,
            ) from None

    try:
        secure_url = resp.json().get("secure_url")
    except ValueError:
        secure_url = None
    if not secure_url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=ERROR_IMAGE_UPLOAD_FAILED,
        )
    db.add(OrganizerImageUpload(organizer_id=current_organizer.id))
    await db.commit()
    return {"url": secure_url}
