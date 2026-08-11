"""Organizer event submission — own-events CRUD + inline classify/publish.

A submitted event is inserted on the adapter-less `user_submission` source
(app/ingestion/registry.py) via the shared insert_normalized_event() helper,
then pushed inline through classify_event()+publish_pending() so it goes live
within the request instead of waiting for the next scheduled pass. It is
flagged needs_review so it still surfaces in the Phase-2 admin review queue
after going live (auto-publish + retractable post-hoc review — see CLAUDE.md).
"""

import hashlib
import logging
import time
from datetime import datetime
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    ALLOWED_IMAGE_HOSTS,
    BROWSE_MAX_PAGE_SIZE,
    BROWSE_PAGE_SIZE,
    CLOUDINARY_UPLOAD_URL_TEMPLATE,
    EVENT_STATUS_CANCELLED,
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
    HTTP_TIMEOUT_SECONDS,
    IMAGE_UPLOAD_ALLOWED_MIME,
    IMAGE_UPLOAD_MAX_BYTES,
    LOCALE_EN,
    LOCALE_ET,
    LOCALE_RU,
    ORGANIZER_DAILY_IMAGE_UPLOAD_CAP,
    ORGANIZER_DAILY_SUBMISSION_CAP,
    ORGANIZER_SUBMISSION_EXTERNAL_ID_PREFIX,
    PAGINATION_MAX_OFFSET,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
    RATE_LIMIT_SUBMIT,
    SOURCE_SLUG_USER_SUBMISSION,
    TALLINN_TZ,
    VALID_CATEGORIES,
)
from app.db import get_db
from app.ingestion.adapter import NormalizedEvent, insert_normalized_event
from app.ingestion.content_filters import is_explicit_text, is_non_event_text
from app.ingestion.http_client import http_post, safe_external_url
from app.ingestion.pricing import normalize_currency
from app.ingestion.sanitize import sanitize_html
from app.llm.classifier import classify_event
from app.models.models import (
    Event,
    EventClassification,
    Organizer,
    OrganizerImageUpload,
    Source,
)
from app.publish import publish_pending
from app.rate_limit import limiter
from app.routers.organizer_auth import get_current_organizer
from app.routers.utils import select_events_with_classification, serialize_event

log = logging.getLogger(__name__)
# Stays under /organizer/* deliberately: ORGANIZER_SESSION_COOKIE_PATH (app/
# constants.py) scopes the organizer_session cookie to Path=/api/organizer —
# a route added outside that prefix would silently never receive the cookie
# and 401 on every call, however correct get_current_organizer's logic is.
router = APIRouter(prefix="/organizer/events", tags=["organizer-events"])


class SubmitEventBody(BaseModel):
    title: str
    title_en: str | None = None
    title_ru: str | None = None
    description: str | None = None
    description_en: str | None = None
    description_ru: str | None = None
    important_info: str | None = None
    important_info_en: str | None = None
    important_info_ru: str | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    venue_name: str | None = None
    venue_address: str | None = None
    url: str | None = None
    image_url: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    currency: str | None = None
    category: str | None = None

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _tz_aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("must be timezone-aware")
        return v

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_CATEGORIES:
            raise ValueError(f"invalid category: {v!r}")
        return v


class PatchEventBody(BaseModel):
    title: str | None = None
    title_en: str | None = None
    title_ru: str | None = None
    description: str | None = None
    description_en: str | None = None
    description_ru: str | None = None
    important_info: str | None = None
    important_info_en: str | None = None
    important_info_ru: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    venue_name: str | None = None
    venue_address: str | None = None
    url: str | None = None
    image_url: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    currency: str | None = None
    category: str | None = None

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _tz_aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("must be timezone-aware")
        return v

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_CATEGORIES:
            raise ValueError(f"invalid category: {v!r}")
        return v


def _localized(
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


async def _get_user_submission_source(db: AsyncSession) -> Source:
    source = await db.scalar(
        select(Source).where(Source.slug == SOURCE_SLUG_USER_SUBMISSION)
    )
    if source is None:
        # Seeded at startup by seed_sources() — absence means the app never
        # booted with the current registry.py, not a caller error.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Submission source not configured; contact support.",
        )
    return source


async def _apply_organizer_category(
    db: AsyncSession, event_id: int, category: str
) -> None:
    """Prepend an organizer-chosen category onto the event's classification.

    Categories are LLM-derived (Event.classification.categories, an array) —
    there is no dedicated organizer-facing column. An explicit organizer pick
    leads the list (any LLM-derived categories, if present, follow); if no
    classification row exists yet (e.g. classify_event's LLM call failed), a
    bare one is created so the pick isn't silently dropped."""
    classification = await db.scalar(
        select(EventClassification).where(EventClassification.event_id == event_id)
    )
    if classification is None:
        db.add(EventClassification(event_id=event_id, categories=[category]))
        return
    if category not in classification.categories:
        classification.categories = [category, *classification.categories]


def _check_image_host(image_url: str | None) -> None:
    """Reject an organizer-submission image_url whose host isn't the signed
    Cloudinary upload endpoint's delivery domain (see ALLOWED_IMAGE_HOSTS) —
    otherwise an arbitrary https host becomes a tracking pixel once the
    digest embeds it as an <img> (see app/email/digest.py)."""
    if image_url and urlsplit(image_url).hostname not in ALLOWED_IMAGE_HOSTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Image URL must be uploaded via POST /organizer/events/image "
                "(res.cloudinary.com)."
            ),
        )


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
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found."
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
            detail="Daily submission limit reached. Try again tomorrow.",
        )

    source = await _get_user_submission_source(db)
    _check_image_host(body.image_url)

    has_price = body.price_min is not None or body.price_max is not None
    normalized = NormalizedEvent(
        external_id=f"{ORGANIZER_SUBMISSION_EXTERNAL_ID_PREFIX}{current_organizer.id}:{uuid4()}",
        title=body.title,
        starts_at=body.starts_at,
        description=sanitize_html(body.description),
        important_info=sanitize_html(body.important_info),
        ends_at=body.ends_at,
        venue_name=body.venue_name,
        venue_address=body.venue_address,
        lat=None,
        lng=None,
        # insert_normalized_event applies safe_external_url (scheme-only) for
        # a user_submission source, not the host-pinned safe_fetchable_url —
        # this event.url is never fetched server-side (refetch.py excludes
        # organizer submissions), so it's render-only like image_url.
        url=body.url,
        image_url=body.image_url,
        price_min=body.price_min,
        price_max=body.price_max,
        currency=normalize_currency(body.currency, has_price),
        title_localized=_localized(body.title, body.title_en, body.title_ru),
        description_localized=_localized(
            sanitize_html(body.description),
            sanitize_html(body.description_en),
            sanitize_html(body.description_ru),
        ),
        important_info_localized=_localized(
            sanitize_html(body.important_info),
            sanitize_html(body.important_info_en),
            sanitize_html(body.important_info_ru),
        ),
    )

    event = await insert_normalized_event(db, source, normalized)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create event; please try again.",
        )
    # insert_normalized_event silently drops a url/image_url the SSRF/scheme
    # guards reject (host not in ALLOWED_SOURCE_HOSTS, bad scheme) — give the
    # organizer an explicit error instead of a silently-vanished field.
    if body.url and not event.url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event URL is not allowed (unsupported scheme).",
        )
    if body.image_url and not event.image_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image URL is not allowed (unsupported scheme).",
        )

    event.submitted_by_organizer_id = current_organizer.id
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

    if not await classify_event(event, db):
        # LLM outage (every provider failed) — event stays draft, distinct
        # from the normal "not yet reviewed" case; classify_pending's 6h
        # backlog drain will retry it, but this is worth surfacing in ops.
        log.warning("organizer submission event_id=%d classify failed", event.id)
    if body.category:
        await _apply_organizer_category(db, event_id, body.category)
    await publish_pending(db)
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

    fields_set = body.model_fields_set
    if "title" in fields_set and body.title is not None:
        event.title_orig = body.title
    if "starts_at" in fields_set and body.starts_at is not None:
        event.starts_at = body.starts_at
    if "ends_at" in fields_set:
        event.ends_at = body.ends_at
    if "venue_name" in fields_set:
        event.venue_name = body.venue_name
    if "venue_address" in fields_set:
        event.venue_address = body.venue_address
    if "url" in fields_set:
        # Same scheme-only guard insert_normalized_event applies at submit
        # time — this event.url is never fetched server-side (refetch.py
        # excludes organizer submissions), so it needs no host pin.
        safe_url = safe_external_url(body.url, SOURCE_SLUG_USER_SUBMISSION)
        if body.url and not safe_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Event URL is not allowed (unsupported scheme).",
            )
        event.url = safe_url
    if "image_url" in fields_set:
        _check_image_host(body.image_url)
        safe_image_url = safe_external_url(body.image_url, SOURCE_SLUG_USER_SUBMISSION)
        if body.image_url and not safe_image_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Image URL is not allowed (unsupported scheme).",
            )
        event.image_url = safe_image_url
    if "price_min" in fields_set:
        event.price_min = body.price_min
    if "price_max" in fields_set:
        event.price_max = body.price_max
    if fields_set & {"price_min", "price_max", "currency"}:
        # Mirrors the submit path's normalize_currency(body.currency, has_price)
        # (see submit_event above): coerces a raw currency value and fills the
        # default only when the event now carries a price, so a price-only
        # PATCH doesn't leave currency NULL and an un-coerced value never
        # lands straight on the String(3) column.
        has_price = event.price_min is not None or event.price_max is not None
        raw_currency = body.currency if "currency" in fields_set else event.currency
        event.currency = normalize_currency(raw_currency, has_price)
    if "category" in fields_set and body.category is not None:
        await _apply_organizer_category(db, event.id, body.category)
    if "description" in fields_set:
        event.description_orig = sanitize_html(body.description)
    if "important_info" in fields_set:
        event.important_info = sanitize_html(body.important_info)

    if fields_set & {"title", "title_en", "title_ru"}:
        existing = event.title_localized or {}
        event.title_localized = _localized(
            event.title_orig,
            body.title_en if "title_en" in fields_set else existing.get(LOCALE_EN),
            body.title_ru if "title_ru" in fields_set else existing.get(LOCALE_RU),
        )
    if fields_set & {"description", "description_en", "description_ru"}:
        existing = event.description_localized or {}
        event.description_localized = _localized(
            event.description_orig,
            sanitize_html(body.description_en)
            if "description_en" in fields_set
            else existing.get(LOCALE_EN),
            sanitize_html(body.description_ru)
            if "description_ru" in fields_set
            else existing.get(LOCALE_RU),
        )
    if fields_set & {"important_info", "important_info_en", "important_info_ru"}:
        existing = event.important_info_localized or {}
        event.important_info_localized = _localized(
            event.important_info,
            sanitize_html(body.important_info_en)
            if "important_info_en" in fields_set
            else existing.get(LOCALE_EN),
            sanitize_html(body.important_info_ru)
            if "important_info_ru" in fields_set
            else existing.get(LOCALE_RU),
        )

    event.needs_review = True

    if not event.is_explicit and is_explicit_text(
        event.title_orig, event.description_orig, event.venue_name, event.important_info
    ):
        event.is_explicit = True
        if event.status == EVENT_STATUS_PUBLISHED:
            event.status = EVENT_STATUS_CLASSIFIED
    if not event.is_non_event and is_non_event_text(event.title_orig, event.venue_name):
        event.is_non_event = True
        if event.status == EVENT_STATUS_PUBLISHED:
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
    """Soft-delete: cancel the event. Events are never hard-deleted (CLAUDE.md
    Data Retention)."""
    event = await _own_event_or_404(db, event_id, current_organizer.id)
    event.status = EVENT_STATUS_CANCELLED
    await db.commit()
    return {"id": event.id, "status": event.status}


@router.get("")
@limiter.limit(RATE_LIMIT_SUBMIT)
async def list_own_events(
    request: Request,
    limit: int = BROWSE_PAGE_SIZE,
    offset: int = 0,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List the organizer's own submitted events, most recent first."""
    limit = max(PAGINATION_MIN_LIMIT, min(limit, BROWSE_MAX_PAGE_SIZE))
    offset = max(PAGINATION_MIN_OFFSET, min(offset, PAGINATION_MAX_OFFSET))

    stmt = (
        select_events_with_classification()
        .where(Event.submitted_by_organizer_id == current_organizer.id)
        .order_by(Event.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    events = (await db.scalars(stmt)).all()
    # serialize_event() is built for public read paths (published-only) and
    # never includes status — an organizer's own dashboard needs to tell
    # draft/classified/published/cancelled apart, so layer it on here.
    return {
        "events": [
            {
                **serialize_event(e, locale=current_organizer.locale),
                "status": e.status,
                "needs_review": e.needs_review,
                "title_localized": e.title_localized,
                "description_localized": e.description_localized,
                "important_info_localized": e.important_info_localized,
            }
            for e in events
        ],
        "limit": limit,
        "offset": offset,
    }


def _cloudinary_signature(params: dict[str, str | int], api_secret: str) -> str:
    """Cloudinary signed-upload signature: SHA-1 over the sorted
    `key=value&...` param string with the API secret appended — per
    https://cloudinary.com/documentation/authentication_signatures. Only
    params actually sent to the upload API are signed; `file`, `cloud_name`,
    and `api_key` are excluded per that spec."""
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.sha1((to_sign + api_secret).encode()).hexdigest()


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
            detail=f"Unsupported image type: {file.content_type!r}",
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
            detail="Daily image upload limit reached. Try again tomorrow.",
        )

    # Starlette has already spooled the full multipart body by the time this
    # handler runs (this cap only bounds what the handler itself holds, not
    # what was received). app.main.MaxBodySizeMiddleware bounds the earlier,
    # ASGI-server-wide stage (MAX_REQUEST_BODY_BYTES); this narrower check
    # stays as the image-specific limit.
    body = await file.read(IMAGE_UPLOAD_MAX_BYTES + 1)
    if len(body) > IMAGE_UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image exceeds {IMAGE_UPLOAD_MAX_BYTES} bytes.",
        )

    if not settings.CLOUDINARY_CLOUD_NAME:
        log.warning(
            "CLOUDINARY_CLOUD_NAME not set — image upload skipped (organizer_id=%d)",
            current_organizer.id,
        )
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Image upload is not configured.",
        )

    timestamp = int(time.time())
    signature = _cloudinary_signature(
        {"timestamp": timestamp}, settings.CLOUDINARY_API_SECRET
    )
    upload_url = CLOUDINARY_UPLOAD_URL_TEMPLATE.format(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME
    )

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
                files={"file": (file.filename, body, file.content_type)},
            )
        except httpx.HTTPError:
            log.exception(
                "Cloudinary upload failed (organizer_id=%d)", current_organizer.id
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Image upload failed; please try again.",
            ) from None

    try:
        secure_url = resp.json().get("secure_url")
    except ValueError:
        secure_url = None
    if not secure_url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Image upload failed; please try again.",
        )
    db.add(OrganizerImageUpload(organizer_id=current_organizer.id))
    await db.commit()
    return {"url": secure_url}
