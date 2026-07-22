"""Admin endpoints — protected by HTTP Basic auth."""

import logging
import secrets
from collections.abc import Awaitable, Callable, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cleanup import cleanup_stale_data
from app.config import settings
from app.constants import (
    ADMIN_DEDUP_GROUPS_MAX_PAGE_SIZE,
    ADMIN_DEDUP_GROUPS_PAGE_SIZE,
    ADMIN_USERNAME_DEFAULT,
    APP_ENV_DEVELOPMENT,
    EVENT_STATUS_CANCELLED,
    LOG_EVENT_AUTH_FAILED,
    RATE_LIMIT_ADMIN,
)
from app.db import AsyncSessionLocal
from app.email.digest import send_daily_digests
from app.ingestion.jobs import (
    classify_pending_drain_now,
    dedup_pass_drain_now,
    geocode_pending_job,
    ingest_all_enabled,
    ingest_source,
    publish_pending_job,
    refetch_event_details_job,
)
from app.ingestion.organizer_sync import sync_fienta_organizers
from app.ingestion.registry import ADAPTER_REGISTRY
from app.models.models import Event, Source
from app.ranking.score import build_daily_feeds
from app.rate_limit import limiter
from app.routers.utils import (
    canonical_event_filter,
    require_configured_secret,
    run_admin_job,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")
_security = HTTPBasic()


async def _run_in_session(
    func: Callable[[AsyncSession], Awaitable[dict]], *, commit: bool
) -> dict:
    """Run a session-scoped job; commit when asked, roll back on failure."""
    async with AsyncSessionLocal() as db:
        try:
            result = await func(db)
            if commit:
                await db.commit()
            return result
        except Exception:
            await db.rollback()
            raise


def _require_admin(credentials: HTTPBasicCredentials = Depends(_security)) -> None:
    password = settings.ADMIN_PASSWORD
    if not require_configured_secret(
        password,
        feature="Admin endpoints",
        setting_name="ADMIN_PASSWORD",
        app_env=settings.APP_ENV,
    ):
        return
    if (
        settings.ADMIN_USERNAME == ADMIN_USERNAME_DEFAULT
        and settings.APP_ENV != APP_ENV_DEVELOPMENT
    ):
        # Fail closed like the password check: a well-known username halves the
        # credential pair an attacker needs to brute-force.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin endpoints disabled: ADMIN_USERNAME left at its default value",
        )
    username_ok = secrets.compare_digest(
        credentials.username.encode(),
        settings.ADMIN_USERNAME.encode(),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode(),
        password.encode(),
    )
    if not (username_ok and password_ok):
        log.warning(
            "admin auth failed: username=%r",
            credentials.username,
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


@router.get("/ingest", dependencies=[Depends(_require_admin)])
@limiter.limit(RATE_LIMIT_ADMIN)
async def admin_ingest_all(request: Request) -> dict:
    """Trigger ingestion for all enabled sources."""
    results = await ingest_all_enabled()
    return {"results": results}


@router.post("/ingest/{slug}", dependencies=[Depends(_require_admin)])
@limiter.limit(RATE_LIMIT_ADMIN)
async def admin_ingest_source(slug: str, request: Request) -> dict:
    """Trigger ingestion for a single source by slug."""
    if slug not in ADAPTER_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown source: {slug!r}"
        )

    async def _run() -> dict:
        try:
            return await ingest_source(slug)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    return await run_admin_job("Ingestion", _run())


@router.post("/dedup", dependencies=[Depends(_require_admin)])
@limiter.limit(RATE_LIMIT_ADMIN)
async def admin_dedup_run(request: Request) -> dict:
    """Trigger a dedup pass, draining the backlog until it clears or the cap is hit."""
    return await run_admin_job("Dedup", dedup_pass_drain_now())


def _serialize_dedup_groups(rows: Sequence[Event]) -> dict[int, list[dict]]:
    """Group event rows by dedup_group_id into response dicts."""
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
    return groups


@router.get("/dedup/groups", dependencies=[Depends(_require_admin)])
@limiter.limit(RATE_LIMIT_ADMIN)
async def admin_dedup_groups(
    request: Request,
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

    groups = _serialize_dedup_groups(rows)

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
@limiter.limit(RATE_LIMIT_ADMIN)
async def admin_classify(request: Request) -> dict:
    """Trigger LLM classification, draining the backlog until it clears or the cap is hit."""
    return await run_admin_job("Classification", classify_pending_drain_now())


@router.post("/publish", dependencies=[Depends(_require_admin)])
@limiter.limit(RATE_LIMIT_ADMIN)
async def admin_publish(request: Request) -> dict:
    """Promote qualifying classified events to published (one bulk UPDATE)."""
    return await run_admin_job("Publish", publish_pending_job())


@router.post("/geocode", dependencies=[Depends(_require_admin)])
@limiter.limit(RATE_LIMIT_ADMIN)
async def admin_geocode(request: Request) -> dict:
    """Backfill lat/lng for events with a venue_address but no coordinates (one batch)."""
    return await run_admin_job("Geocoding", geocode_pending_job())


@router.post("/refetch", dependencies=[Depends(_require_admin)])
@limiter.limit(RATE_LIMIT_ADMIN)
async def admin_refetch(request: Request) -> dict:
    """Re-fetch detail pages for all future events and reconcile stored fields (one batch).

    Standalone, like /admin/geocode — not part of /admin/pipeline/run. Run it
    before a manual geocode if you want coords NULLed by an address change
    re-resolved in the same operation.
    """
    return await run_admin_job("Refetch", refetch_event_details_job())


@router.post("/sync-organizers", dependencies=[Depends(_require_admin)])
@limiter.limit(RATE_LIMIT_ADMIN)
async def admin_sync_organizers(request: Request) -> dict:
    """Trigger Fienta organizer sync (discover new organizers, flag stale ones)."""
    return await run_admin_job(
        "Organizer sync", _run_in_session(sync_fienta_organizers, commit=True)
    )


@router.post("/cleanup", dependencies=[Depends(_require_admin)])
@limiter.limit(RATE_LIMIT_ADMIN)
async def admin_cleanup(
    request: Request,
    dry_run: bool = Query(
        True,
        description="When true (default), counts candidate rows but deletes nothing",
    ),
) -> dict:
    """Trigger data retention cleanup (prunes satellite tables; never events).

    Defaults to dry-run, matching every other destructive admin/maintenance
    tool in this codebase (reset_events.py, /admin/pipeline/run) — pass
    ?dry_run=false to actually delete.

    See app.cleanup.cleanup_stale_data for the per-table retention windows.
    """
    return await run_admin_job(
        "Cleanup",
        _run_in_session(
            lambda db: cleanup_stale_data(db, dry_run=dry_run), commit=not dry_run
        ),
    )


@router.post("/build-feeds", dependencies=[Depends(_require_admin)])
@limiter.limit(RATE_LIMIT_ADMIN)
async def admin_build_feeds(request: Request) -> dict:
    """Trigger daily feed builder for all active users (writes to daily_feeds)."""
    # build_daily_feeds commits internally (score.py); no second commit needed.
    return await run_admin_job(
        "Feed build", _run_in_session(build_daily_feeds, commit=False)
    )


@router.post("/send-digests", dependencies=[Depends(_require_admin)])
@limiter.limit(RATE_LIMIT_ADMIN)
async def admin_send_digests(
    request: Request,
    dry_run: bool = Query(True, description="When true (default), counts would-send but skips actual email delivery"),
) -> dict:
    """Trigger daily digest send. Defaults to dry-run — pass ?dry_run=false to actually send."""
    return await run_admin_job(
        "Digest send",
        _run_in_session(lambda db: send_daily_digests(db, dry_run=dry_run), commit=False),
    )


@router.post("/pipeline/run", dependencies=[Depends(_require_admin)])
@limiter.limit(RATE_LIMIT_ADMIN)
async def admin_pipeline_run(
    request: Request,
    dry_run: bool = Query(True, description="When true (default), digest stage counts would-send but skips actual email delivery"),
) -> dict:
    """Run all seven pipeline stages in dependency order.

    Stops at the first failure — later stages depend on earlier output.
    Returns {ok, stages} where stages is an ordered dict of per-stage results.
    """
    stage_runners: list[tuple[str, Callable[[], Awaitable[object]]]] = [
        (
            "sync_organizers",
            lambda: _run_in_session(sync_fienta_organizers, commit=True),
        ),
        ("ingest", ingest_all_enabled),
        ("dedup", dedup_pass_drain_now),
        ("classify", classify_pending_drain_now),
        ("publish", publish_pending_job),
        # build_daily_feeds commits internally (score.py)
        ("build_feeds", lambda: _run_in_session(build_daily_feeds, commit=False)),
        (
            "send_digests",
            lambda: _run_in_session(
                lambda db: send_daily_digests(db, dry_run=dry_run), commit=False
            ),
        ),
    ]

    stages: dict[str, object] = {}
    for stage_name, runner in stage_runners:
        try:
            stages[stage_name] = await runner()
        except Exception as exc:
            log.exception("pipeline: %s failed", stage_name)
            stages[stage_name] = {"error": str(exc)}
            return {"ok": False, "stages": stages}

    return {"ok": True, "stages": stages}


@router.get("/stats", dependencies=[Depends(_require_admin)])
@limiter.limit(RATE_LIMIT_ADMIN)
async def admin_stats(request: Request) -> dict:
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
                    canonical_event_filter(),
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
