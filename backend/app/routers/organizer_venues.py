"""Organizer-owned reusable venues (#173, #174) — list/create/update/soft-delete.

No submission-form UI wires into this yet (that's a later #173 slice); this
is the CRUD foundation. Editing address fields clears geocode state so the
next geocode_pending pass re-resolves lat/lng from the new address.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app._generated.shared_constants import (
    ORGANIZER_VENUE_ADDRESS_MAX_LEN,
    ORGANIZER_VENUE_NAME_MAX_LEN,
    PAGINATION_MAX_OFFSET,
)
from app.constants.core import TALLINN_TZ
from app.constants.organizer import (
    ERROR_DAILY_VENUE_CREATION_LIMIT,
    ORGANIZER_CURRENCY_MAX_LEN,
    ORGANIZER_DAILY_VENUE_CREATION_CAP,
)
from app.constants.ranking import (
    BROWSE_MAX_PAGE_SIZE,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
)
from app.constants.rate_limits import RATE_LIMIT_SUBMIT
from app.db import get_db
from app.ingestion.pricing import normalize_currency
from app.models.models import Organizer, Venue
from app.rate_limit import limiter
from app.auth.dependencies import get_current_organizer
from app.routers.utils import (
    own_venue_or_404,
    remoderate_venue_linked_events,
    validate_price_ordering,
)

router = APIRouter(prefix="/organizer/venues", tags=["organizer-venues"])


class VenueBody(BaseModel):
    name: str = Field(..., max_length=ORGANIZER_VENUE_NAME_MAX_LEN)
    name_en: str | None = Field(None, max_length=ORGANIZER_VENUE_NAME_MAX_LEN)
    name_ru: str | None = Field(None, max_length=ORGANIZER_VENUE_NAME_MAX_LEN)
    address: str | None = Field(None, max_length=ORGANIZER_VENUE_ADDRESS_MAX_LEN)
    price_min: float | None = Field(None, ge=0)
    price_max: float | None = Field(None, ge=0)
    currency: str | None = Field(None, max_length=ORGANIZER_CURRENCY_MAX_LEN)

    @model_validator(mode="after")
    def _price_ordering(self) -> "VenueBody":
        validate_price_ordering(self.price_min, self.price_max)
        return self


class VenuePatchBody(BaseModel):
    name: str | None = Field(None, max_length=ORGANIZER_VENUE_NAME_MAX_LEN)
    name_en: str | None = Field(None, max_length=ORGANIZER_VENUE_NAME_MAX_LEN)
    name_ru: str | None = Field(None, max_length=ORGANIZER_VENUE_NAME_MAX_LEN)
    address: str | None = Field(None, max_length=ORGANIZER_VENUE_ADDRESS_MAX_LEN)
    price_min: float | None = Field(None, ge=0)
    price_max: float | None = Field(None, ge=0)
    currency: str | None = Field(None, max_length=ORGANIZER_CURRENCY_MAX_LEN)

    @model_validator(mode="after")
    def _price_ordering(self) -> "VenuePatchBody":
        # Both-present check only — a patch touching just one bound can't be
        # validated against the other without a DB round-trip (mirrors
        # organizer_events.py's PatchEventBody._ordering).
        validate_price_ordering(self.price_min, self.price_max)
        return self


def _serialize(venue: Venue) -> dict:
    return {
        "id": venue.id,
        "name": venue.name,
        "name_en": venue.name_en,
        "name_ru": venue.name_ru,
        "address": venue.address,
        "lat": venue.lat,
        "lng": venue.lng,
        "price_min": venue.price_min,
        "price_max": venue.price_max,
        "currency": venue.currency,
        "created_at": venue.created_at,
    }


@router.get("")
@limiter.limit(RATE_LIMIT_SUBMIT)
async def list_own_venues(
    request: Request,
    limit: int = Query(
        BROWSE_MAX_PAGE_SIZE, ge=PAGINATION_MIN_LIMIT, le=BROWSE_MAX_PAGE_SIZE
    ),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Bounded (Big-O audit #5, item 1.4) — VenuePicker fetches this as a
    flat array with no "load more" UI, so limit/offset are added to close the
    no-LIMIT-at-all gap without changing the response shape; default limit is
    the page-size ceiling so today's unbounded-in-practice UX is unaffected
    for any organizer under that many saved venues.
    """
    venues = (
        await db.scalars(
            select(Venue)
            .where(
                Venue.organizer_id == current_organizer.id,
                Venue.deleted_at.is_(None),
            )
            .order_by(Venue.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [_serialize(v) for v in venues]


@router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT_SUBMIT)
async def create_venue(
    body: VenueBody,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Daily venue-creation cap is per-organizer (DB-backed count-then-insert,
    independent of ORGANIZER_DAILY_SUBMISSION_CAP/ORGANIZER_DAILY_IMAGE_UPLOAD_CAP)
    — same best-effort soft ceiling as those, not a hard guarantee under
    concurrent requests."""
    day_start = datetime.now(TALLINN_TZ).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    created_today = (
        await db.scalar(
            select(func.count())
            .select_from(Venue)
            .where(
                Venue.organizer_id == current_organizer.id,
                Venue.created_at >= day_start,
            )
        )
        or 0
    )
    if created_today >= ORGANIZER_DAILY_VENUE_CREATION_CAP:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=ERROR_DAILY_VENUE_CREATION_LIMIT,
        )

    has_price = body.price_min is not None or body.price_max is not None
    venue = Venue(
        organizer_id=current_organizer.id,
        name=body.name,
        name_en=body.name_en,
        name_ru=body.name_ru,
        address=body.address,
        price_min=body.price_min,
        price_max=body.price_max,
        currency=normalize_currency(body.currency, has_price),
    )
    db.add(venue)
    await db.commit()
    await db.refresh(venue)
    return _serialize(venue)


@router.patch("/{venue_id}")
@limiter.limit(RATE_LIMIT_SUBMIT)
async def update_own_venue(
    venue_id: int,
    body: VenuePatchBody,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    venue = await own_venue_or_404(db, venue_id, current_organizer.id)

    fields_set = body.model_fields_set
    names_before = (venue.name, venue.name_en, venue.name_ru)
    if "name" in fields_set and body.name is not None:
        venue.name = body.name
    if "name_en" in fields_set:
        venue.name_en = body.name_en
    if "name_ru" in fields_set:
        venue.name_ru = body.name_ru
    address_fields = fields_set & {"address"}
    address_changed = False
    if "address" in address_fields and body.address != venue.address:
        venue.address = body.address
        address_changed = True
    if address_changed:
        # Address actually changed — the previously geocoded lat/lng no
        # longer match, so clear both the coordinates and the cooldown clock
        # to force re-resolution on the next geocode_pending pass. A PATCH
        # that merely round-trips the same address value leaves geocode
        # state untouched.
        venue.lat = None
        venue.lng = None
        venue.geocode_attempted_at = None
    if "price_min" in fields_set:
        venue.price_min = body.price_min
    if "price_max" in fields_set:
        venue.price_max = body.price_max
    if fields_set & {"price_min", "price_max", "currency"}:
        has_price = venue.price_min is not None or venue.price_max is not None
        raw_currency = body.currency if "currency" in fields_set else venue.currency
        venue.currency = normalize_currency(raw_currency, has_price)

    if (venue.name, venue.name_en, venue.name_ru) != names_before:
        await remoderate_venue_linked_events(db, venue)

    await db.commit()
    await db.refresh(venue)
    return _serialize(venue)


@router.delete("/{venue_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(RATE_LIMIT_SUBMIT)
async def delete_own_venue(
    venue_id: int,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> None:
    venue = await own_venue_or_404(db, venue_id, current_organizer.id)
    venue.deleted_at = datetime.now(TALLINN_TZ)
    await db.commit()
