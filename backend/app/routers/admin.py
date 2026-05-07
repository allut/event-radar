"""Admin endpoints — protected by HTTP Basic auth."""
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select

from app.config import settings
from app.db import AsyncSessionLocal
from app.ingestion.jobs import classify_pending_job, dedup_pass, ingest_all_enabled, ingest_source
from app.ingestion.registry import ADAPTER_REGISTRY
from app.models.models import Event

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")
_security = HTTPBasic()


def _require_admin(credentials: HTTPBasicCredentials = Depends(_security)) -> None:
    password = settings.ADMIN_PASSWORD
    if not password:
        if settings.APP_ENV != "development":
            # Production with no password set — refuse all access until explicitly configured.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Admin endpoints disabled: ADMIN_PASSWORD not configured",
            )
        # Development with no password — allow any credentials but log a warning so devs know.
        log.warning("ADMIN_PASSWORD not set; admin endpoints are unprotected (development mode)")
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
async def admin_ingest_all():
    """Trigger ingestion for all enabled sources."""
    results = await ingest_all_enabled()
    return {"results": results}


@router.post("/ingest/{slug}", dependencies=[Depends(_require_admin)])
async def admin_ingest_source(slug: str):
    """Trigger ingestion for a single source by slug."""
    if slug not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown source: {slug!r}")
    try:
        result = await ingest_source(slug)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception:
        log.exception("admin ingest failed for slug=%s", slug)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ingestion failed; see server logs")
    return result


@router.post("/dedup", dependencies=[Depends(_require_admin)])
async def admin_dedup_run():
    """Trigger a rule-based dedup pass over all non-cancelled events."""
    try:
        summary = await dedup_pass()
    except Exception:
        log.exception("admin dedup pass failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Dedup failed; see server logs")
    return summary


@router.get("/dedup/groups", dependencies=[Depends(_require_admin)])
async def admin_dedup_groups():
    """Return events grouped by dedup_group_id for manual eyeballing.

    Only returns events that are part of a dedup group (dedup_group_id IS NOT NULL).
    Sorted by group ID then event ID so each cluster appears together.
    """
    from app.constants import EVENT_STATUS_CANCELLED

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(Event)
                .where(
                    Event.dedup_group_id.is_not(None),
                    Event.status != EVENT_STATUS_CANCELLED,
                )
                .order_by(Event.dedup_group_id, Event.id)
            )
        ).all()

    groups: dict[int, list[dict]] = {}
    for e in rows:
        groups.setdefault(e.dedup_group_id, []).append({
            "id": e.id,
            "title": e.title_orig,
            "starts_at": e.starts_at.isoformat(),
            "venue": e.venue_name,
            "status": e.status,
            "url": e.url,
        })

    return {
        "group_count": len(groups),
        "event_count": len(rows),
        "groups": [
            {"dedup_group_id": gid, "events": members}
            for gid, members in sorted(groups.items())
        ],
    }


@router.post("/classify", dependencies=[Depends(_require_admin)])
async def admin_classify():
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
async def admin_stats():
    """Aggregate counts used by checkpoint tests and manual monitoring."""
    from sqlalchemy import func
    from app.constants import EVENT_STATUS_CANCELLED
    from app.models.models import Source

    async with AsyncSessionLocal() as db:
        total = (await db.scalar(
            select(func.count(Event.id)).where(Event.status != EVENT_STATUS_CANCELLED)
        )) or 0

        canonical = (await db.scalar(
            select(func.count(Event.id)).where(
                Event.status != EVENT_STATUS_CANCELLED,
                (Event.dedup_group_id.is_(None)) | (Event.dedup_group_id == Event.id),
            )
        )) or 0

        sources_total = (await db.scalar(select(func.count(Source.id)))) or 0
        sources_enabled = (await db.scalar(
            select(func.count(Source.id)).where(Source.enabled.is_(True))
        )) or 0

    return {
        "events": {"total": total, "canonical": canonical},
        "sources": {"total": sources_total, "enabled": sources_enabled},
    }
