"""Admin event inspector and dedup-group review."""

from collections.abc import Sequence
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_admin
from app._generated.shared_constants import (
    ADMIN_DEDUP_GROUPS_PAGE_SIZE,
    DEFAULT_USER_LOCALE,
    PAGINATION_MAX_OFFSET,
    VALID_LOCALES,
)
from app.constants.admin import (
    ADMIN_DEDUP_GROUPS_MAX_PAGE_SIZE,
    ADMIN_EVENT_INSPECTOR_RAW_EVENTS_LIMIT,
)
from app.constants.core import TALLINN_TZ
from app.constants.events import (
    ERROR_EVENT_NOT_FOUND,
    EVENT_STATUS_CANCELLED,
)
from app.constants.ranking import (
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
)
from app.constants.rate_limits import (
    RATE_LIMIT_ADMIN,
    RATE_LIMIT_BROWSE,
    RATE_LIMIT_SCOPE_ADMIN_READ,
)
from app.db import AsyncSessionLocal
from app.models.models import (
    DailyFeed,
    Event,
    EventReport,
    EventSource,
    RawEvent,
    Source,
)
from app.rate_limit import limiter
from app.events.localize import (
    resolve_description,
    resolve_important_info,
    resolve_title,
)
from app.events.queries import select_events_with_classification
from app.events.venue import (
    resolve_venue_address,
    resolve_venue_coords,
    resolve_venue_name,
)

router = APIRouter(prefix="/admin")


def _dedup_event_summary(e: Event) -> dict:
    """Minimal per-event dict shared by every dedup-group listing:
    /admin/dedup/groups' _serialize_dedup_groups and the event inspector's
    sibling list (issue #157) — one field set kept in sync in one place."""
    return {
        "id": e.id,
        "title": e.title_orig,
        "starts_at": e.starts_at.isoformat(),
        "venue": resolve_venue_name(e, DEFAULT_USER_LOCALE),
        "status": e.status,
        "url": e.url,
        "is_explicit": e.is_explicit,
    }


def _serialize_dedup_groups(rows: Sequence[Event]) -> dict[int, list[dict]]:
    """Group event rows by dedup_group_id into response dicts."""
    groups: dict[int, list[dict]] = {}
    for e in rows:
        if e.dedup_group_id is None:
            continue
        groups.setdefault(e.dedup_group_id, []).append(_dedup_event_summary(e))
    return groups


@router.get("/dedup/groups", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_dedup_groups(
    request: Request,
    limit: int = Query(
        ADMIN_DEDUP_GROUPS_PAGE_SIZE,
        ge=PAGINATION_MIN_LIMIT,
        le=ADMIN_DEDUP_GROUPS_MAX_PAGE_SIZE,
    ),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
) -> dict:
    """Return events grouped by dedup_group_id for manual eyeballing.

    Paginated by *group* (not row), so a noisy group with many duplicates does
    not consume the whole page. ``offset`` and ``limit`` apply to the sorted
    list of distinct dedup_group_ids.
    """
    async with AsyncSessionLocal() as db:
        # Exact total on every page (spec #551): the numbered pager derives
        # its last page and past-end clamp from it.
        total = (
            await db.scalar(
                select(func.count(func.distinct(Event.dedup_group_id))).where(
                    Event.dedup_group_id.is_not(None),
                    Event.status != EVENT_STATUS_CANCELLED,
                )
            )
        ) or 0

        page_group_ids = (
            await db.scalars(
                select(Event.dedup_group_id)
                .where(
                    Event.dedup_group_id.is_not(None),
                    Event.status != EVENT_STATUS_CANCELLED,
                )
                .distinct()
                .order_by(Event.dedup_group_id)
                .limit(limit + 1)
                .offset(offset)
            )
        ).all()
        has_more = len(page_group_ids) > limit
        page_group_ids = page_group_ids[:limit]

        if not page_group_ids:
            return {
                "group_count": 0,
                "event_count": 0,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": False,
                "groups": [],
            }

        rows = (
            await db.scalars(
                select(Event)
                .options(selectinload(Event.venue))
                .where(
                    Event.dedup_group_id.in_(page_group_ids),
                    Event.status != EVENT_STATUS_CANCELLED,
                )
                .order_by(Event.dedup_group_id, Event.id)
            )
        ).all()

    groups = _serialize_dedup_groups(rows)

    return {
        "group_count": len(groups),
        "event_count": len(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "groups": [
            {"dedup_group_id": gid, "events": members}
            for gid, members in sorted(groups.items())
        ],
    }


def _serialize_inspector_report(r: EventReport) -> dict:
    return {
        "id": r.id,
        "user_id": r.user_id,
        "reason": r.reason,
        "is_illegal_allegation": r.is_illegal_allegation,
        "detail": r.detail,
        "status": r.status,
        "resolution_note": r.resolution_note,
        "created_at": r.created_at.isoformat(),
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
    }


def _serialize_raw_event(raw: RawEvent, source_slug: str) -> dict:
    """payload is included verbatim — the frontend must render it as
    escaped/pretty-printed text, never parsed as HTML (issue #157). Unlike
    description/important_info (sanitized at ingest), this is the one
    genuinely unsanitized field in the console."""
    return {
        "id": raw.id,
        "source_slug": source_slug,
        "external_id": raw.external_id,
        "payload": raw.payload,
        "fetched_at": raw.fetched_at.isoformat(),
        "processed_at": raw.processed_at.isoformat() if raw.processed_at else None,
    }


def _translation_state(m: dict | None, locale: str) -> bool:
    """True when this locale has its own stored value (not a fallback)."""
    return bool(m and m.get(locale))


def _content_by_locale(event: Event) -> dict:
    """Per-locale resolved content plus, per field, whether the value is a
    real translation or the locale -> en -> original fallback."""
    return {
        loc: {
            "title": resolve_title(event, loc),
            "description": resolve_description(event, loc),
            "important_info": resolve_important_info(event, loc),
            "venue_name": resolve_venue_name(event, loc),
            "translated": {
                "title": _translation_state(event.title_localized, loc),
                "description": _translation_state(event.description_localized, loc),
                "important_info": _translation_state(
                    event.important_info_localized, loc
                ),
            },
        }
        for loc in sorted(VALID_LOCALES)
    }


def _serialize_event_detail(event: Event) -> dict:
    cl = event.classification
    lat, lng = resolve_venue_coords(event)
    return {
        "id": event.id,
        "slug": event.slug,
        "title_orig": event.title_orig,
        "description_orig": event.description_orig,
        "important_info": event.important_info,
        "price_hint": event.price_hint,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat() if event.ends_at else None,
        "venue_name": resolve_venue_name(event, DEFAULT_USER_LOCALE),
        "venue_address": resolve_venue_address(event),
        "lat": lat,
        "lng": lng,
        "url": event.url,
        "image_url": event.image_url,
        "price_min": float(event.price_min) if event.price_min is not None else None,
        "price_max": float(event.price_max) if event.price_max is not None else None,
        "currency": event.currency,
        "status": event.status,
        "is_explicit": event.is_explicit,
        "is_out_of_area": event.is_out_of_area,
        "is_non_event": event.is_non_event,
        "has_free_tier": event.has_free_tier,
        "dedup_group_id": event.dedup_group_id,
        "submitted_by_organizer_id": event.submitted_by_organizer_id,
        "needs_review": event.needs_review,
        "cancellation_reason": event.cancellation_reason,
        "created_at": event.created_at.isoformat(),
        "updated_at": event.updated_at.isoformat(),
        "detail_refetched_at": (
            event.detail_refetched_at.isoformat()
            if event.detail_refetched_at
            else None
        ),
        "geocode_attempted_at": (
            event.geocode_attempted_at.isoformat()
            if event.geocode_attempted_at
            else None
        ),
        "classification": (
            {
                "categories": cl.categories,
                "vibes": cl.vibes,
                "quality_score": cl.quality_score,
                "why_go_bullets": cl.why_go_bullets,
                "language_detected": cl.language_detected,
                "model_used": cl.model_used,
                "classified_at": cl.classified_at.isoformat(),
            }
            if cl
            else None
        ),
        "content_by_locale": _content_by_locale(event),
    }


@router.get("/events/{event_id}", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_get_event(event_id: int, request: Request) -> dict:
    """Full-detail inspector payload for one event, any status (issue #157,
    part of #153). Curated projection, not a raw ORM dump — mirrors
    _serialize_dedup_groups' style. Dedup siblings and reports are fetched
    inline (cheap, already-indexed lookups), not separate round-trips.

    Feed-membership uses the `@>` (array-contains) operator, not `= ANY()` —
    the only one of the two the built-in GIN array_ops opclass can accelerate
    Shipped with no new index initially, per the research behind #153.
    """
    async with AsyncSessionLocal() as db:
        event = await db.scalar(
            select_events_with_classification().where(Event.id == event_id)
        )
        if event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_EVENT_NOT_FOUND
            )

        siblings: Sequence[Event] = []
        if event.dedup_group_id is not None:
            # Deliberately includes cancelled siblings, unlike
            # admin_list_dedup_groups (which excludes them from its listing
            # view) — an admin drilling into one specific event wants to see
            # a cancelled sibling too (e.g. to understand why it was
            # cancelled), matching this endpoint's own "any status" event.
            siblings = (
                await db.scalars(
                    select(Event)
                    .options(selectinload(Event.venue))
                    .where(
                        Event.dedup_group_id == event.dedup_group_id,
                        Event.id != event.id,
                    )
                )
            ).all()

        reports = (
            await db.scalars(
                select(EventReport)
                .where(EventReport.event_id == event.id)
                .order_by(EventReport.created_at.desc())
            )
        ).all()

        raw_rows = (
            await db.execute(
                select(RawEvent, Source.slug)
                .join(Source, Source.id == RawEvent.source_id)
                .join(
                    EventSource,
                    and_(
                        EventSource.source_id == RawEvent.source_id,
                        EventSource.external_id == RawEvent.external_id,
                    ),
                )
                .where(EventSource.event_id == event.id)
                .order_by(RawEvent.fetched_at.desc())
                .limit(ADMIN_EVENT_INSPECTOR_RAW_EVENTS_LIMIT)
            )
        ).all()

        today = datetime.now(TALLINN_TZ).date()
        in_todays_feed = (
            await db.scalar(
                select(DailyFeed.id)
                .where(
                    DailyFeed.feed_date == today,
                    DailyFeed.event_ids.contains([event.id]),
                )
                .limit(1)
            )
        ) is not None

    return {
        "event": _serialize_event_detail(event),
        "dedup_siblings": [_dedup_event_summary(e) for e in siblings],
        "reports": [_serialize_inspector_report(r) for r in reports],
        "raw_events": [_serialize_raw_event(re, slug) for re, slug in raw_rows],
        "in_todays_feed": in_todays_feed,
    }
