"""Admin endpoints — protected by HTTP Basic auth."""

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import func, select

from app.config import settings
from app.constants import (
    ADMIN_DEDUP_GROUPS_MAX_PAGE_SIZE,
    ADMIN_DEDUP_GROUPS_PAGE_SIZE,
    APP_ENV_DEVELOPMENT,
    EVENT_STATUS_CANCELLED,
)
from app.db import AsyncSessionLocal
from app.ingestion.jobs import (
    classify_pending_job,
    dedup_pass,
    ingest_all_enabled,
    ingest_source,
)
from app.ingestion.registry import ADAPTER_REGISTRY
from app.models.models import Event, Source

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")
_security = HTTPBasic()


def _require_admin(credentials: HTTPBasicCredentials = Depends(_security)) -> None:
    password = settings.ADMIN_PASSWORD
    if not password:
        if settings.APP_ENV != APP_ENV_DEVELOPMENT:
            # Production with no password set — refuse all access until explicitly configured.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Admin endpoints disabled: ADMIN_PASSWORD not configured",
            )
        # Development with no password — allow any credentials but log a warning so devs know.
        log.warning(
            "ADMIN_PASSWORD not set; admin endpoints are unprotected (development mode)"
        )
        return
    username_ok = secrets.compare_digest(
        credentials.username.encode(),
        settings.ADMIN_USERNAME.encode(),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode(),
        password.encode(),
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


@router.get("/ingest", dependencies=[Depends(_require_admin)])
async def admin_ingest_all() -> dict:
    """Trigger ingestion for all enabled sources."""
    results = await ingest_all_enabled()
    return {"results": results}


@router.post("/ingest/{slug}", dependencies=[Depends(_require_admin)])
async def admin_ingest_source(slug: str) -> dict:
    """Trigger ingestion for a single source by slug."""
    if slug not in ADAPTER_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown source: {slug!r}"
        )
    try:
        result = await ingest_source(slug)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception:
        log.exception("admin ingest failed for slug=%s", slug)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ingestion failed; see server logs",
        )
    return result


@router.post("/dedup", dependencies=[Depends(_require_admin)])
async def admin_dedup_run() -> dict:
    """Trigger a rule-based dedup pass over all non-cancelled events."""
    try:
        summary = await dedup_pass()
    except Exception:
        log.exception("admin dedup pass failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dedup failed; see server logs",
        )
    return summary


@router.get("/dedup/groups", dependencies=[Depends(_require_admin)])
async def admin_dedup_groups(
    limit: int = Query(
        ADMIN_DEDUP_GROUPS_PAGE_SIZE,
        ge=1,
        le=ADMIN_DEDUP_GROUPS_MAX_PAGE_SIZE,
    ),
    offset: int = Query(0, ge=0),
) -> dict:
    """Return events grouped by dedup_group_id for manual eyeballing.

    Paginated by *group* (not row), so a noisy group with many duplicates does
    not consume the whole page. ``offset`` and ``limit`` apply to the sorted
    list of distinct dedup_group_ids.
    """
    async with AsyncSessionLocal() as db:
        total_groups = (
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
                .limit(limit)
                .offset(offset)
            )
        ).all()

        if not page_group_ids:
            return {
                "group_count": 0,
                "event_count": 0,
                "total_groups": total_groups,
                "limit": limit,
                "offset": offset,
                "has_more": False,
                "groups": [],
            }

        rows = (
            await db.scalars(
                select(Event)
                .where(
                    Event.dedup_group_id.in_(page_group_ids),
                    Event.status != EVENT_STATUS_CANCELLED,
                )
                .order_by(Event.dedup_group_id, Event.id)
            )
        ).all()

    groups: dict[int, list[dict]] = {}
    for e in rows:
        groups.setdefault(e.dedup_group_id, []).append(
            {  # type: ignore[arg-type]
                "id": e.id,
                "title": e.title_orig,
                "starts_at": e.starts_at.isoformat(),
                "venue": e.venue_name,
                "status": e.status,
                "url": e.url,
            }
        )

    return {
        "group_count": len(groups),
        "event_count": len(rows),
        "total_groups": total_groups,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(page_group_ids) < total_groups,
        "groups": [
            {"dedup_group_id": gid, "events": members}
            for gid, members in sorted(groups.items())
        ],
    }


@router.post("/classify", dependencies=[Depends(_require_admin)])
async def admin_classify() -> dict:
    """Trigger LLM classification for one batch of unclassified canonical events."""
    try:
        summary = await classify_pending_job()
    except Exception:
        log.exception("admin classify failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Classification failed; see server logs",
        )
    return summary


@router.get("/stats", dependencies=[Depends(_require_admin)])
async def admin_stats() -> dict:
    """Aggregate counts used by checkpoint tests and manual monitoring."""
    async with AsyncSessionLocal() as db:
        total = (
            await db.scalar(
                select(func.count(Event.id)).where(
                    Event.status != EVENT_STATUS_CANCELLED
                )
            )
        ) or 0

        canonical = (
            await db.scalar(
                select(func.count(Event.id)).where(
                    Event.status != EVENT_STATUS_CANCELLED,
                    (Event.dedup_group_id.is_(None))
                    | (Event.dedup_group_id == Event.id),
                )
            )
        ) or 0

        sources_total = (await db.scalar(select(func.count(Source.id)))) or 0
        sources_enabled = (
            await db.scalar(
                select(func.count(Source.id)).where(Source.enabled.is_(True))
            )
        ) or 0

    return {
        "events": {"total": total, "canonical": canonical},
        "sources": {"total": sources_total, "enabled": sources_enabled},
    }
