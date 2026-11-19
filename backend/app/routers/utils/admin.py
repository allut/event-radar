"""Admin-console helpers: job locks, NDJSON streaming, audit logging, resolution bodies."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.admin import ERROR_ADMIN_JOB_ALREADY_RUNNING, ERROR_ADMIN_JOB_FAILED
from app.constants.events import (
    ERROR_EVENT_NOT_FOUND,
)
from app.constants.log_events import (
    LOG_EVENT_ADMIN_ACTION,
)
from app.constants.reports import (
    ADMIN_RESOLUTION_NOTE_MAX_CHARS,
    ERROR_RESOLUTION_NOTE_REQUIRED,
)
from app.models.events import Event
from app.models.audit import AdminAction
from app.models.organizers import OrganizerIdentity as OrganizerIdentity

log = logging.getLogger(__name__)


_RUNNING_ADMIN_JOBS: set[str] = set()


def acquire_admin_job_lock(key: str) -> None:
    """Single-flight guard for the expensive/destructive triggers (issue
    #160): pipeline/run, cleanup, full ingest, send_digests, classify. Raises
    409 if *key* is already running instead of letting a retry click start a
    second concurrent run. In-memory only — fine given this app's
    single-process topology."""
    if key in _RUNNING_ADMIN_JOBS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ERROR_ADMIN_JOB_ALREADY_RUNNING.format(name=key),
        )
    _RUNNING_ADMIN_JOBS.add(key)


def release_admin_job_lock(key: str) -> None:
    _RUNNING_ADMIN_JOBS.discard(key)


async def run_admin_job(name: str, coro: Awaitable[dict]) -> dict:
    """Await an admin-triggered job, converting any failure into a generic 500.

    Shared by every /admin/* trigger endpoint: the full traceback goes to the
    server log; the response detail stays generic so internals never leak.
    """
    try:
        return await coro
    except HTTPException:
        raise
    except Exception:
        log.exception("admin %s failed", name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_ADMIN_JOB_FAILED.format(name=name),
        )


def ndjson_line(stage: str, status_: str, result: Any, error: str | None) -> bytes:
    """One line of the shared streamed-job envelope (issue #159) — every
    /admin/* job trigger streams this shape, one line per stage."""
    return (
        json.dumps({"stage": stage, "status": status_, "result": result, "error": error})
        + "\n"
    ).encode()


async def stream_admin_job(
    name: str,
    stage: str,
    action: str,
    target: int | str,
    coro: Awaitable[dict],
    lock_key: str | None = None,
) -> AsyncIterator[bytes]:
    """Streaming sibling of run_admin_job: runs *coro* and yields a single
    NDJSON envelope line instead of returning a dict. A failure becomes a
    status="error" line rather than an HTTP 500 — once the stream has
    started, headers are already sent, so the generic-failure behavior
    (server log gets the traceback, client gets a generic message, no
    internals leak) has to travel inside the body instead of the status
    code.

    *coro* runs as an independent task, not a direct `await` in this
    generator's own frame. A client disconnect makes Starlette cancel this
    generator (StreamingResponse races `listen_for_disconnect` against the
    body on uvicorn's pinned ASGI spec_version "2.3", cancelling whichever
    task is streaming — issue #159); a direct `await coro` would let
    that cancellation propagate straight into the job and cut it off
    mid-write. Awaiting `queue.get()` instead means the generator's own
    cancellation never touches the task, so the job always runs to
    completion regardless of whether anyone is still listening."""
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def _runner() -> None:
        try:
            result = await coro
            log_admin_action(None, action, target, result)()
            await queue.put(ndjson_line(stage, "ok", result, None))
        except HTTPException as exc:
            detail = str(exc.detail)
            log_admin_action(None, action, target, {"error": detail})()
            await queue.put(ndjson_line(stage, "error", None, detail))
        except Exception:
            log.exception("admin %s failed", name)
            detail = ERROR_ADMIN_JOB_FAILED.format(name=name)
            log_admin_action(None, action, target, {"error": detail})()
            await queue.put(ndjson_line(stage, "error", None, detail))
        finally:
            if lock_key is not None:
                release_admin_job_lock(lock_key)
            await queue.put(None)

    asyncio.ensure_future(_runner())
    while True:
        line = await queue.get()
        if line is None:
            return
        yield line


def log_admin_action(
    db: AsyncSession | None, action: str, target: int | str, result: dict
) -> Callable[[], None]:
    """Adds a durable AdminAction row to *db* (when given) and returns a
    zero-arg closure that emits the structured Axiom log line — the caller
    must invoke that closure only after its own `await db.commit()`
    succeeds, so the Axiom line never claims a mutation that a rolled-back
    transaction actually discarded. The row rides the caller's own open
    transaction (added, not committed here) so it lands atomically with the
    mutation it records, and survives an outage of the LOG_SHIP_URL log
    drain. Call from inside the same `_run()` closure as the mutation, pass
    *db* (and call the returned closure right after `await db.commit()`)
    for the takedown/retract/approve/resolve/pipeline-run actions the
    report feature's legal obligations bear on (see the admin-console
    spec's Audit logging section) — pass None for every other admin job
    (no transaction to ride), which keeps the pre-existing log-only
    behavior; those callers may invoke the closure immediately."""

    def _emit() -> None:
        log.info(
            "admin action: %s",
            action,
            extra={
                "event": LOG_EVENT_ADMIN_ACTION,
                "action": action,
                "target": target,
                "result": result,
            },
        )

    if db is not None:
        db.add(AdminAction(action=action, target=str(target), result=result))
    return _emit


class ResolutionBody(BaseModel):
    resolution_note: str = Field(max_length=ADMIN_RESOLUTION_NOTE_MAX_CHARS)


def validated_resolution_note(body: ResolutionBody) -> str:
    note = body.resolution_note.strip()
    if not note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_RESOLUTION_NOTE_REQUIRED,
        )
    return note


async def event_or_404(db: AsyncSession, event_id: int) -> Event:
    event = await db.get(Event, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_EVENT_NOT_FOUND
        )
    return event
