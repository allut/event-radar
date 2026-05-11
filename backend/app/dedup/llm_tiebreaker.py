"""Two-stage deduplication: rule pre-filter + LLM tiebreaker.

Stage 1: ``is_candidate_pair()`` from rules.py (fuzzy title + time + venue).
Stage 2: LLM tiebreaker on candidate pairs only (1 call per pair, cached).

Merge condition: LLM returns ``{"same": true, "confidence": ≥ 0.7}``.
On confirm: union-find produces clusters → ``dedup_group_id = min(event_id)``.

Run ``run_dedup_pass_llm()`` instead of ``run_dedup_pass()`` to get both stages.
"""
import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    DEDUP_LOOKBACK_DAYS,
    EVENT_STATUS_CANCELLED,
    LLM_DEDUP_CONFIDENCE_THRESHOLD,
    LLM_DEDUP_MAX_CANDIDATE_PAIRS_PER_PASS,
    LLM_DEDUP_PROMPT_TEMPLATE,
    LLM_DEDUP_TITLE_MAX_LEN,
    LLM_DEDUP_VENUE_MAX_LEN,
    TALLINN_TZ,
    TIME_WINDOW_HOURS,
)
from app.dedup.rules import _find, _union, build_cluster_assignments, is_candidate_pair
from app.llm.router import LLMError, llm_json
from app.models.models import Event

log = logging.getLogger(__name__)


def _build_prompt(a: Event, b: Event) -> str:
    return LLM_DEDUP_PROMPT_TEMPLATE.format(
        title_a=a.title_orig[:LLM_DEDUP_TITLE_MAX_LEN],
        date_a=a.starts_at.strftime("%Y-%m-%d %H:%M"),
        venue_a=(a.venue_name or "unknown")[:LLM_DEDUP_VENUE_MAX_LEN],
        title_b=b.title_orig[:LLM_DEDUP_TITLE_MAX_LEN],
        date_b=b.starts_at.strftime("%Y-%m-%d %H:%M"),
        venue_b=(b.venue_name or "unknown")[:LLM_DEDUP_VENUE_MAX_LEN],
    )


async def _llm_confirms_pair(a: Event, b: Event, db: AsyncSession) -> bool:
    """Return True if the LLM says the pair is the same event with sufficient confidence.

    Note: event_id=a.id is stored in llm_calls for audit; the pair identity is
    recoverable from the content_hash (which encodes both titles + dates).
    """
    prompt = _build_prompt(a, b)
    try:
        result, _ = await llm_json("dedup", prompt, db, event_id=a.id)
        same = result.get("same", False)
        confidence = float(result.get("confidence", 0.0))
        confirmed = bool(same) and confidence >= LLM_DEDUP_CONFIDENCE_THRESHOLD
        log.debug(
            "llm dedup: a=%d b=%d same=%s confidence=%.2f → %s",
            a.id, b.id, same, confidence, "MERGE" if confirmed else "skip",
        )
        return confirmed
    except LLMError as exc:
        log.warning("llm dedup failed for pair (%d, %d): %s — treating as distinct", a.id, b.id, exc)
        return False
    except (TypeError, ValueError) as exc:
        log.warning("llm dedup bad response for pair (%d, %d): %s — treating as distinct", a.id, b.id, exc)
        return False


async def run_dedup_pass_llm(db: AsyncSession) -> dict:
    """Two-stage dedup: rule pre-filter + LLM tiebreaker.

    Loads all non-cancelled events in the lookback window, finds candidate pairs
    via the rule filter, confirms each with the LLM, then writes ``dedup_group_id``
    for all confirmed clusters. Falls back gracefully if no LLM providers are
    configured (returns rule-only result).

    Caps LLM calls at ``_MAX_CANDIDATE_PAIRS_PER_PASS`` per pass to bound DB
    session lifetime (Cerebras fallback at 1 req/min could otherwise hold the
    connection open indefinitely).

    Returns a summary dict with ``total``, ``candidate_pairs``, ``llm_confirmed``,
    ``grouped``, ``groups``, ``updated`` keys.
    """
    from datetime import datetime, timedelta

    cutoff = (
        datetime.now(tz=TALLINN_TZ)
        - timedelta(days=DEDUP_LOOKBACK_DAYS)
        - timedelta(hours=TIME_WINDOW_HOURS)
    )
    rows = (
        await db.scalars(
            select(Event)
            .where(Event.status != EVENT_STATUS_CANCELLED)
            .where(Event.starts_at >= cutoff)
            .order_by(Event.id)
        )
    ).all()
    events = list(rows)

    if not events:
        return {"total": 0, "candidate_pairs": 0, "llm_confirmed": 0, "grouped": 0, "groups": 0, "updated": 0}

    n = len(events)
    ids = [e.id for e in events]
    parent: dict[int, int] = {eid: eid for eid in ids}

    candidate_pairs = 0
    llm_confirmed = 0
    capped = False

    for i in range(n):
        if capped:
            break
        for j in range(i + 1, n):
            if not is_candidate_pair(events[i], events[j]):
                continue
            candidate_pairs += 1
            if candidate_pairs > LLM_DEDUP_MAX_CANDIDATE_PAIRS_PER_PASS:
                log.warning(
                    "dedup-llm: hit %d candidate pair cap; remaining pairs skipped this pass",
                    LLM_DEDUP_MAX_CANDIDATE_PAIRS_PER_PASS,
                )
                capped = True
                break
            if await _llm_confirms_pair(events[i], events[j], db):
                _union(parent, events[i].id, events[j].id)
                llm_confirmed += 1

    assignments = build_cluster_assignments(parent, ids)

    updated = 0
    for event in events:
        new_gid = assignments.get(event.id)
        if event.dedup_group_id != new_gid:
            event.dedup_group_id = new_gid
            updated += 1

    # Clear stale group IDs for aged-out events (same logic as rules.run_dedup_pass)
    await db.execute(
        update(Event)
        .where(Event.starts_at < cutoff)
        .where(Event.status != EVENT_STATUS_CANCELLED)
        .where(Event.dedup_group_id.is_not(None))
        .values(dedup_group_id=None),
        execution_options={"synchronize_session": False},
    )

    group_count = len({gid for gid in assignments.values()})
    log.info(
        "dedup-llm pass: %d events, %d candidate pairs, %d llm-confirmed → %d groups, %d updated",
        len(events), candidate_pairs, llm_confirmed, group_count, updated,
    )
    return {
        "total": len(events),
        "candidate_pairs": candidate_pairs,
        "llm_confirmed": llm_confirmed,
        "grouped": len(assignments),
        "groups": group_count,
        "updated": updated,
    }
