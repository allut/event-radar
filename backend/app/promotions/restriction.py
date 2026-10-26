"""Promotion restriction (#612): clearance, newly-flagged notices, the stand-alone
assessment and the launch backfill.

`events.promotion_restriction` is set by the classifier (`None` unassessed,
`none` clear, else one of `PROMOTION_RESTRICTIONS`). It never feeds the publish
gate or organic listing; only the fill gate reads it (`fill.py` clause 6). A
Restriction clearance on a Promotion covers only the restriction it names.
"""

import asyncio
import logging
from collections.abc import Sequence
from typing import Any
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.events import EVENT_STATUS_CANCELLED
from app.constants.llm import (
    LLM_BATCH_FANOUT_CONCURRENCY,
    LLM_CLASSIFY_DESC_FALLBACK,
    LLM_CLASSIFY_VENUE_FALLBACK,
    LLM_MAX_PROMPT_CHARS,
    LLM_TASK_PROMOTION_RESTRICTION,
)
from app.constants.promotions import (
    PROMOTION_EMAIL_SEND_CONCURRENCY,
    PROMOTION_ERROR_CLEARANCE_NOT_NEEDED,
    PROMOTION_ERROR_CLEARANCE_NOTE_REQUIRED,
    PROMOTION_ERROR_CLEARANCE_REQUIRED,
    PROMOTION_ERROR_NOT_EDITABLE,
    PROMOTION_GRANTED_BY_ADMIN,
    PROMOTION_HOLDING_STATUSES,
    PROMOTION_RESTRICTION_NONE,
    VALID_PROMOTION_RESTRICTION_VALUES,
)
from app.email.promotion_admin import send_restriction_flagged_notice
from app.email.resend import resend_http_client
from app.events.queries import event_not_ended_filter
from app.events.venue import resolve_venue_name
from app.ingestion.sanitize import html_to_text
from app.llm.prompts import LLM_PROMOTION_RESTRICTION_PROMPT_TEMPLATE, escape_prompt_delimiters
from app.llm.router import llm_http_client, llm_json_or_none
from app.models.models import Event, Promotion
from app.promotions.owners import resolve_owner_ids
from app.promotions.windows import RuleViolation, tallinn_today

log = logging.getLogger(__name__)

# Events assessed per backfill query page.
RESTRICTION_BACKFILL_PAGE_SIZE = 200


def parse_promotion_restriction(value: Any) -> str | None:
    """A valid `promotion_restriction` value, else None (unassessed). Unlike
    the fail-safe content flags, a missing or malformed answer leaves the
    event unassessed, which keeps it out of the Sponsored slot."""
    if isinstance(value, str) and value.strip().lower() in VALID_PROMOTION_RESTRICTION_VALUES:
        return value.strip().lower()
    return None


def is_restricted(value: str | None) -> bool:
    return value is not None and value != PROMOTION_RESTRICTION_NONE


def clearance_violations(event: Event, confirmed: bool, note: str | None) -> list[RuleViolation]:
    """What a grant of this event still needs: nothing for a clear or
    unassessed event, the checkbox and a note for a restricted one."""
    if not is_restricted(event.promotion_restriction):
        return []
    found: list[RuleViolation] = []
    if not confirmed:
        found.append(RuleViolation(PROMOTION_ERROR_CLEARANCE_REQUIRED))
    if not (note or "").strip():
        found.append(RuleViolation(PROMOTION_ERROR_CLEARANCE_NOTE_REQUIRED))
    return found


def record_clearance(promotion: Promotion, event: Event, note: str, now: datetime) -> None:
    promotion.restriction_cleared = event.promotion_restriction
    promotion.restriction_clearance_by = PROMOTION_GRANTED_BY_ADMIN
    promotion.restriction_clearance_note = note.strip()
    promotion.restriction_cleared_at = now


def clear_existing(
    promotion: Promotion, event: Event, note: str | None, now: datetime
) -> list[RuleViolation]:
    """Clear the event's current restriction on an existing Promotion (the
    newly-flagged path). Returns violations; writes nothing when any."""
    if promotion.status not in PROMOTION_HOLDING_STATUSES:
        return [RuleViolation(PROMOTION_ERROR_NOT_EDITABLE)]
    if not is_restricted(event.promotion_restriction):
        return [RuleViolation(PROMOTION_ERROR_CLEARANCE_NOT_NEEDED)]
    if not (note or "").strip():
        return [RuleViolation(PROMOTION_ERROR_CLEARANCE_NOTE_REQUIRED)]
    record_clearance(promotion, event, note or "", now)
    return []


async def notify_newly_restricted(
    db: AsyncSession,
    changes: Sequence[tuple[Event, str | None]],
    now: datetime,
) -> list[int]:
    """Email the admin for every scheduled or live Promotion whose event just
    became restricted (previous value is `changes[i][1]`) and whose clearance
    doesn't cover it. One query and one Resend client whatever the row count;
    best-effort sends behind a bounded gather. The fill gate pauses these on
    its own. Returns the notified Promotion ids."""
    flagged = {
        event.id: event
        for event, previous in changes
        if is_restricted(event.promotion_restriction) and event.promotion_restriction != previous
    }
    if not flagged:
        return []
    today = tallinn_today(now)
    promotions = (
        await db.scalars(
            select(Promotion)
            .where(
                Promotion.event_id.in_(sorted(flagged)),
                Promotion.status.in_(PROMOTION_HOLDING_STATUSES),
                Promotion.end_date >= today,
            )
            .order_by(Promotion.id)
        )
    ).all()
    pending = [
        promotion
        for promotion in promotions
        if promotion.restriction_cleared != flagged[promotion.event_id].promotion_restriction
    ]
    if not pending:
        return []
    semaphore = asyncio.Semaphore(PROMOTION_EMAIL_SEND_CONCURRENCY)

    async def _notify(promotion: Promotion, http_client: httpx.AsyncClient) -> bool:
        event = flagged[promotion.event_id]
        async with semaphore:
            try:
                await send_restriction_flagged_notice(
                    promotion, event, event.promotion_restriction or "", http_client=http_client
                )
            except Exception:
                log.exception("restriction notice failed for promotion_id=%s", promotion.id)
                return False
        return True

    async with resend_http_client() as http_client:
        results = await asyncio.gather(
            *(_notify(promotion, http_client) for promotion in pending),
            return_exceptions=True,
        )
    return [promotion.id for promotion, sent in zip(pending, results) if sent is True]


def _assess_prompt(event: Event) -> str:
    desc = (html_to_text(event.description_orig) or "").strip()[:LLM_MAX_PROMPT_CHARS]
    return LLM_PROMOTION_RESTRICTION_PROMPT_TEMPLATE.format(
        title=escape_prompt_delimiters(event.title_orig),
        venue=escape_prompt_delimiters(resolve_venue_name(event) or LLM_CLASSIFY_VENUE_FALLBACK),
        description=escape_prompt_delimiters(desc or LLM_CLASSIFY_DESC_FALLBACK),
    )


async def assess_events(db: AsyncSession, events: Sequence[Event]) -> int:
    """Run the stand-alone restriction prompt for `events` (bounded fan-out) and
    set `promotion_restriction` where the answer is valid. Used by organizer
    edits and the backfill. Returns how many events were assessed. Caller commits."""
    if not events:
        return 0
    semaphore = asyncio.Semaphore(LLM_BATCH_FANOUT_CONCURRENCY)

    async def _one(event: Event) -> str | None:
        async with semaphore:
            response = await llm_json_or_none(
                LLM_TASK_PROMOTION_RESTRICTION,
                _assess_prompt(event),
                db,
                event_id=event.id,
                context=f"restriction assess failed for event_id={event.id}",
                http_client=http_client,
            )
        if response is None:
            return None
        return parse_promotion_restriction(response[0].get("promotion_restriction"))

    async with llm_http_client() as http_client:
        results = await asyncio.gather(*(_one(e) for e in events), return_exceptions=True)
    assessed = 0
    for event, result in zip(events, results):
        if isinstance(result, str):
            event.promotion_restriction = result
            assessed += 1
        elif isinstance(result, BaseException):
            log.error("restriction assess raised for event_id=%d: %s", event.id, result)
    return assessed


async def reassess_after_edit(db: AsyncSession, event: Event, now: datetime) -> None:
    """Best-effort restriction pass for one edited event, then the
    newly-flagged notice. An LLM outage leaves the previous value."""
    previous = event.promotion_restriction
    try:
        await assess_events(db, [event])
    except Exception:
        log.exception("restriction reassess failed for event_id=%s", event.id)
        return
    await db.flush()
    await notify_newly_restricted(db, [(event, previous)], now)


async def backfill_restrictions(db: AsyncSession, now: datetime) -> dict[str, int]:
    """Assess every owned, not-ended, unassessed event once. Idempotent: an
    assessed event (`promotion_restriction` not null) is skipped, and an event
    the LLM could not answer stays unassessed for the next run. Pages by id;
    owners resolve in bulk per page. Caller commits."""
    summary = {"candidates": 0, "owned": 0, "assessed": 0}
    last_id = 0
    while True:
        page = (
            await db.scalars(
                select(Event)
                .where(
                    Event.id > last_id,
                    Event.promotion_restriction.is_(None),
                    Event.status != EVENT_STATUS_CANCELLED,
                    event_not_ended_filter(now),
                )
                .order_by(Event.id)
                .limit(RESTRICTION_BACKFILL_PAGE_SIZE)
            )
        ).all()
        if not page:
            break
        last_id = page[-1].id
        owners = await resolve_owner_ids(db, page)
        owned = [e for e in page if e.id in owners]
        summary["candidates"] += len(page)
        summary["owned"] += len(owned)
        summary["assessed"] += await assess_events(db, owned)
        await db.flush()
    return summary
