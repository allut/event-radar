"""Admin pipeline job triggers — manual runs of the scheduled jobs, streamed as NDJSON."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.auth.dependencies import get_current_admin
from app.cleanup import cleanup_stale_data
from app.constants.admin import (
    ADMIN_ACTION_BUILD_FEEDS,
    ADMIN_ACTION_CLEANUP,
    ADMIN_ACTION_CLASSIFY,
    ADMIN_ACTION_DEDUP,
    ADMIN_ACTION_GEOCODE,
    ADMIN_ACTION_INGEST,
    ADMIN_ACTION_INGEST_SOURCE,
    ADMIN_ACTION_PIPELINE_RUN,
    ADMIN_ACTION_PUBLISH,
    ADMIN_ACTION_REFETCH,
    ADMIN_ACTION_SEND_DIGESTS,
    ADMIN_ACTION_SYNC_ORGANIZERS,
)
from app.constants.http import MIME_APPLICATION_NDJSON
from app.constants.ingestion import ERROR_UNKNOWN_SOURCE
from app.constants.jobs import PIPELINE_RUN_OVERLAPPING_LOCK_KEYS
from app.constants.rate_limits import (
    RATE_LIMIT_ADMIN,
)
from app.constants.security import SECURITY_HEADERS
from app.db import AsyncSessionLocal, run_in_session
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
from app.ranking.daily_feed import build_daily_feeds
from app.rate_limit import limiter
from app.routers.utils import (
    acquire_admin_job_lock,
    log_admin_action,
    ndjson_line,
    release_admin_job_lock,
    stream_admin_job,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")


def _ndjson_response(gen: AsyncIterator[bytes]) -> StreamingResponse:
    """Shared streamed-envelope response wrapper (issue #159) — every job
    trigger endpoint streams NDJSON with caching disabled unconditionally."""
    return StreamingResponse(
        gen,
        media_type=MIME_APPLICATION_NDJSON,
        headers={"Cache-Control": SECURITY_HEADERS["Cache-Control"]},
    )


@router.post("/ingest", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_ingest_all(request: Request) -> StreamingResponse:
    """Trigger ingestion for all enabled sources."""
    acquire_admin_job_lock(ADMIN_ACTION_INGEST)

    async def _run() -> dict:
        return {"results": await ingest_all_enabled()}

    return _ndjson_response(
        stream_admin_job(
            "Ingestion",
            "ingest",
            ADMIN_ACTION_INGEST,
            "all",
            _run(),
            lock_key=ADMIN_ACTION_INGEST,
        )
    )


@router.post("/ingest/{slug}", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_ingest_source(slug: str, request: Request) -> StreamingResponse:
    """Trigger ingestion for a single source by slug."""
    if slug not in ADAPTER_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_UNKNOWN_SOURCE.format(slug=slug),
        )

    async def _run() -> dict:
        try:
            return await ingest_source(slug)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    return _ndjson_response(
        stream_admin_job(
            "Ingestion", "ingest", ADMIN_ACTION_INGEST_SOURCE, slug, _run()
        )
    )


@router.post("/dedup", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_dedup_run(request: Request) -> StreamingResponse:
    """Trigger a dedup pass, draining the backlog until it clears or the cap is hit."""
    return _ndjson_response(
        stream_admin_job(
            "Dedup", "dedup", ADMIN_ACTION_DEDUP, "dedup", dedup_pass_drain_now()
        )
    )


@router.post("/classify", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_classify(request: Request) -> StreamingResponse:
    """Trigger LLM classification, draining the backlog until it clears or the cap is hit."""
    acquire_admin_job_lock(ADMIN_ACTION_CLASSIFY)
    return _ndjson_response(
        stream_admin_job(
            "Classification",
            "classify",
            ADMIN_ACTION_CLASSIFY,
            "classify",
            classify_pending_drain_now(),
            lock_key=ADMIN_ACTION_CLASSIFY,
        )
    )


@router.post("/publish", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_publish(request: Request) -> StreamingResponse:
    """Promote qualifying classified events to published (one bulk UPDATE)."""
    return _ndjson_response(
        stream_admin_job(
            "Publish", "publish", ADMIN_ACTION_PUBLISH, "publish", publish_pending_job()
        )
    )


@router.post("/geocode", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_geocode(request: Request) -> StreamingResponse:
    """Backfill lat/lng for events with a venue_address but no coordinates (one batch)."""
    return _ndjson_response(
        stream_admin_job(
            "Geocoding",
            "geocode",
            ADMIN_ACTION_GEOCODE,
            "geocode",
            geocode_pending_job(),
        )
    )


@router.post("/refetch", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_refetch(request: Request) -> StreamingResponse:
    """Re-fetch detail pages for all future events and reconcile stored fields (one batch).

    Standalone, like /admin/geocode — not part of /admin/pipeline/run. Run it
    before a manual geocode if you want coords NULLed by an address change
    re-resolved in the same operation.
    """
    return _ndjson_response(
        stream_admin_job(
            "Refetch",
            "refetch",
            ADMIN_ACTION_REFETCH,
            "refetch",
            refetch_event_details_job(),
        )
    )


@router.post("/sync-organizers", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_sync_organizers(request: Request) -> StreamingResponse:
    """Trigger Fienta organizer sync (discover new organizers, flag stale ones)."""
    return _ndjson_response(
        stream_admin_job(
            "Organizer sync",
            "sync_organizers",
            ADMIN_ACTION_SYNC_ORGANIZERS,
            "sync_organizers",
            run_in_session(sync_fienta_organizers, commit=True),
        )
    )


@router.post("/cleanup", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_cleanup(
    request: Request,
    dry_run: bool = Query(
        True,
        description="When true (default), counts candidate rows but deletes nothing",
    ),
) -> StreamingResponse:
    """Trigger data retention cleanup (prunes satellite tables; never events).

    Defaults to dry-run, matching every other destructive admin/maintenance
    tool in this codebase (reset_events.py, /admin/pipeline/run) — pass
    ?dry_run=false to actually delete.

    See app.cleanup.cleanup_stale_data for the per-table retention windows.
    """
    acquire_admin_job_lock(ADMIN_ACTION_CLEANUP)
    return _ndjson_response(
        stream_admin_job(
            "Cleanup",
            "cleanup",
            ADMIN_ACTION_CLEANUP,
            "cleanup",
            run_in_session(
                lambda db: cleanup_stale_data(db, dry_run=dry_run), commit=not dry_run
            ),
            lock_key=ADMIN_ACTION_CLEANUP,
        )
    )


@router.post("/build-feeds", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_build_feeds(request: Request) -> StreamingResponse:
    """Trigger daily feed builder for all active users (writes to daily_feeds)."""
    # build_daily_feeds commits internally (daily_feed.py); no second commit needed.
    return _ndjson_response(
        stream_admin_job(
            "Feed build",
            "build_feeds",
            ADMIN_ACTION_BUILD_FEEDS,
            "build_feeds",
            run_in_session(build_daily_feeds, commit=False),
        )
    )


@router.post("/send-digests", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_send_digests(
    request: Request,
    dry_run: bool = Query(True, description="When true (default), counts would-send but skips actual email delivery"),
) -> StreamingResponse:
    """Trigger daily digest send. Defaults to dry-run — pass ?dry_run=false to actually send."""
    acquire_admin_job_lock(ADMIN_ACTION_SEND_DIGESTS)
    return _ndjson_response(
        stream_admin_job(
            "Digest send",
            "send_digests",
            ADMIN_ACTION_SEND_DIGESTS,
            "send_digests",
            run_in_session(lambda db: send_daily_digests(db, dry_run=dry_run), commit=False),
            lock_key=ADMIN_ACTION_SEND_DIGESTS,
        )
    )


def _acquire_pipeline_run_locks() -> None:
    acquired: list[str] = []
    try:
        for key in (ADMIN_ACTION_PIPELINE_RUN, *PIPELINE_RUN_OVERLAPPING_LOCK_KEYS):
            acquire_admin_job_lock(key)
            acquired.append(key)
    except HTTPException:
        for key in acquired:
            release_admin_job_lock(key)
        raise


def _release_pipeline_run_locks() -> None:
    for key in (ADMIN_ACTION_PIPELINE_RUN, *PIPELINE_RUN_OVERLAPPING_LOCK_KEYS):
        release_admin_job_lock(key)


async def _run_pipeline_stages(dry_run: bool, queue: asyncio.Queue[bytes | None]) -> None:
    """Run all seven pipeline stages in dependency order, pushing one NDJSON
    envelope line per completed stage onto *queue*. Stops at the first
    failure — later stages depend on earlier output — so a failed run
    pushes fewer than seven lines. Runs as its own task (see
    _stream_pipeline_run) so a client disconnect can't cut a stage off
    mid-run."""
    stage_runners: list[tuple[str, Callable[[], Awaitable[object]]]] = [
        (
            "sync_organizers",
            lambda: run_in_session(sync_fienta_organizers, commit=True),
        ),
        ("ingest", ingest_all_enabled),
        ("dedup", dedup_pass_drain_now),
        ("classify", classify_pending_drain_now),
        ("publish", publish_pending_job),
        # build_daily_feeds commits internally (daily_feed.py)
        ("build_feeds", lambda: run_in_session(build_daily_feeds, commit=False)),
        (
            "send_digests",
            lambda: run_in_session(
                lambda db: send_daily_digests(db, dry_run=dry_run), commit=False
            ),
        ),
    ]

    stages: dict[str, object] = {}
    ok = True
    try:
        for stage_name, runner in stage_runners:
            try:
                result = await runner()
                stages[stage_name] = result
                await queue.put(ndjson_line(stage_name, "ok", result, None))
            except Exception:
                log.exception("pipeline: %s failed", stage_name)
                error = f"{stage_name} failed; see server logs"
                stages[stage_name] = {"error": error}
                ok = False
                await queue.put(ndjson_line(stage_name, "error", None, error))
                break

        # No single db session spans every stage above (each manages its own
        # commit), so this row can't ride the same transaction as any one
        # mutation — it gets its own short-lived session instead, still more
        # durable than the log line alone.
        async with AsyncSessionLocal() as audit_db:
            emit_admin_log = log_admin_action(
                audit_db, ADMIN_ACTION_PIPELINE_RUN, "pipeline", {"ok": ok, "stages": stages}
            )
            await audit_db.commit()
        emit_admin_log()
    finally:
        _release_pipeline_run_locks()
        await queue.put(None)


async def _stream_pipeline_run(dry_run: bool) -> AsyncIterator[bytes]:
    """Streams _run_pipeline_stages' output. Runs the stages as an
    independent task rather than a direct `await` in this generator's own
    frame — a client disconnect cancels this generator (Starlette's
    StreamingResponse races `listen_for_disconnect` against the body on
    uvicorn's pinned ASGI spec_version "2.3" — issue #159), and a direct
    `await` would let that cancellation reach into the stage loop and cut a
    stage off mid-run. Awaiting `queue.get()` instead means the run always
    finishes regardless of whether anyone is still listening."""
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    asyncio.ensure_future(_run_pipeline_stages(dry_run, queue))
    while True:
        line = await queue.get()
        if line is None:
            return
        yield line


@router.post("/pipeline/run", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_pipeline_run(
    request: Request,
    dry_run: bool = Query(True, description="When true (default), digest stage counts would-send but skips actual email delivery"),
) -> StreamingResponse:
    """Run all seven pipeline stages in dependency order, streamed as NDJSON
    (one line per completed stage — issue #159)."""
    _acquire_pipeline_run_locks()
    return _ndjson_response(_stream_pipeline_run(dry_run))
