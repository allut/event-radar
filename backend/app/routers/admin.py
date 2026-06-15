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
from app.email.digest import send_daily_digests
from app.ingestion.jobs import (
    classify_pending_drain_now,
    dedup_pass_drain_now,
    ingest_all_enabled,
    ingest_source,
)
from app.ingestion.organizer_sync import sync_fienta_organizers
from app.ingestion.registry import ADAPTER_REGISTRY
from app.models.models import Event, Source
from app.ranking.score import build_daily_feeds

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
    """Trigger a dedup pass, draining the backlog until it clears or the cap is hit."""
    try:
        summary = await dedup_pass_drain_now()
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
        if e.dedup_group_id is None:
            continue
        groups.setdefault(e.dedup_group_id, []).append(
            {
                "id": e.id,
                "title": e.title_orig,
                "starts_at": e.starts_at.isoformat(),
                "venue": e.venue_name,
                "status": e.status,
                "url": e.url,
                "is_explicit": e.is_explicit,
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
    """Trigger LLM classification, draining the backlog until it clears or the cap is hit."""
    try:
        summary = await classify_pending_drain_now()
    except Exception:
        log.exception("admin classify failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Classification failed; see server logs",
        )
    return summary


@router.post("/sync-organizers", dependencies=[Depends(_require_admin)])
async def admin_sync_organizers() -> dict:
    """Trigger Fienta organizer sync (discover new organizers, flag stale ones)."""
    async with AsyncSessionLocal() as db:
        try:
            result = await sync_fienta_organizers(db)
            await db.commit()
        except Exception:
            await db.rollback()
            log.exception("admin sync-organizers failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Organizer sync failed; see server logs",
            )
    return result


@router.post("/build-feeds", dependencies=[Depends(_require_admin)])
async def admin_build_feeds() -> dict:
    """Trigger daily feed builder for all active users (writes to daily_feeds)."""
    async with AsyncSessionLocal() as db:
        try:
            summary = await build_daily_feeds(db)
            # build_daily_feeds commits internally (score.py); no second commit needed.
        except Exception:
            await db.rollback()
            log.exception("admin build-feeds failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Feed build failed; see server logs",
            )
    return summary


@router.post("/send-digests", dependencies=[Depends(_require_admin)])
async def admin_send_digests(
    dry_run: bool = Query(True, description="When true (default), counts would-send but skips actual email delivery"),
) -> dict:
    """Trigger daily digest send. Defaults to dry-run — pass ?dry_run=false to actually send."""
    async with AsyncSessionLocal() as db:
        try:
            summary = await send_daily_digests(db, dry_run=dry_run)
        except Exception:
            log.exception("admin send-digests failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Digest send failed; see server logs",
            )
    return summary


@router.post("/pipeline/run", dependencies=[Depends(_require_admin)])
async def admin_pipeline_run(
    dry_run: bool = Query(True, description="When true (default), digest stage counts would-send but skips actual email delivery"),
) -> dict:
    """Run all six pipeline stages in dependency order.

    Stops at the first failure — later stages depend on earlier output.
    Returns {ok, stages} where stages is an ordered dict of per-stage results.
    """
    stages: dict[str, object] = {}

    # Stage 1: organizer sync
    async with AsyncSessionLocal() as db:
        try:
            sync_result = await sync_fienta_organizers(db)
            await db.commit()
            stages["sync_organizers"] = sync_result
        except Exception as exc:
            await db.rollback()
            log.exception("pipeline: sync_organizers failed")
            stages["sync_organizers"] = {"error": str(exc)}
            return {"ok": False, "stages": stages}

    # Stage 2: ingest
    try:
        ingest_result = await ingest_all_enabled()
        stages["ingest"] = ingest_result
    except Exception as exc:
        log.exception("pipeline: ingest failed")
        stages["ingest"] = {"error": str(exc)}
        return {"ok": False, "stages": stages}

    # Stage 3: dedup
    try:
        dedup_result = await dedup_pass_drain_now()
        stages["dedup"] = dedup_result
    except Exception as exc:
        log.exception("pipeline: dedup failed")
        stages["dedup"] = {"error": str(exc)}
        return {"ok": False, "stages": stages}

    # Stage 4: classify
    try:
        classify_result = await classify_pending_drain_now()
        stages["classify"] = classify_result
    except Exception as exc:
        log.exception("pipeline: classify failed")
        stages["classify"] = {"error": str(exc)}
        return {"ok": False, "stages": stages}

    # Stage 5: build feeds (build_daily_feeds commits internally)
    async with AsyncSessionLocal() as db:
        try:
            build_feeds_result = await build_daily_feeds(db)
            stages["build_feeds"] = build_feeds_result
        except Exception as exc:
            await db.rollback()
            log.exception("pipeline: build_feeds failed")
            stages["build_feeds"] = {"error": str(exc)}
            return {"ok": False, "stages": stages}

    # Stage 6: send digests
    async with AsyncSessionLocal() as db:
        try:
            send_digests_result = await send_daily_digests(db, dry_run=dry_run)
            stages["send_digests"] = send_digests_result
        except Exception as exc:
            log.exception("pipeline: send_digests failed")
            stages["send_digests"] = {"error": str(exc)}
            return {"ok": False, "stages": stages}

    return {"ok": True, "stages": stages}


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
