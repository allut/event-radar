"""Two-stage deduplication: rule pre-filter + LLM tiebreaker.

Stage 1: ``is_candidate_pair()`` from rules.py (fuzzy title + time + venue).
Stage 2: LLM tiebreaker on candidate pairs only (1 call per pair, cached).

Merge condition: LLM returns ``{"same": true, "confidence": ≥ 0.7}``.
On confirm: union-find produces clusters → ``dedup_group_id = min(event_id)``.

STATUS: WIRED — the scheduled dedup job (main.py → jobs.dedup_pass) calls
``run_dedup_pass_llm()``. Stage 1's *time* pre-filter is the shared SQL
self-join in ``rules.candidate_pair_ids_in_window``; the fuzzy title/venue check
(``rules.is_candidate_pair``) then runs in Python on those pairs; stage 2 (this
module) confirms each surviving candidate with the LLM. When no LLM provider is
configured, the pass degrades to the rule-only ``rules.run_dedup_pass``.
"""

import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    EVENT_STATUS_CANCELLED,
    LLM_DEDUP_CONFIDENCE_THRESHOLD,
    LLM_DEDUP_MAX_CANDIDATE_PAIRS_PER_PASS,
    LLM_DEDUP_PROMPT_TEMPLATE,
    LLM_DEDUP_TITLE_MAX_LEN,
    LLM_DEDUP_VENUE_MAX_LEN,
)
from app.dedup.rules import (
    _union,
    build_cluster_assignments,
    candidate_pair_ids_in_window,
    dedup_window_cutoff,
    is_candidate_pair,
    run_dedup_pass,
)
from app.llm.router import LLMError, llm_available, llm_json
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
            a.id,
            b.id,
            same,
            confidence,
            "MERGE" if confirmed else "skip",
        )
        return confirmed
    except LLMError as exc:
        log.warning(
            "llm dedup failed for pair (%d, %d): %s — treating as distinct",
            a.id,
            b.id,
            exc,
        )
        return False
    except (TypeError, ValueError) as exc:
        log.warning(
            "llm dedup bad response for pair (%d, %d): %s — treating as distinct",
            a.id,
            b.id,
            exc,
        )
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
    # Graceful degradation: with no LLM provider configured (local dev, lapsed
    # keys), every LLM call would fail and merge nothing. Fall back to the
    # rule-only stage-1 pass instead so dedup still groups obvious duplicates.
    if not llm_available():
        log.info("dedup-llm: no LLM provider configured — falling back to rule-only pass")
        summary = await run_dedup_pass(db)
        # Keep the documented stage-2 summary shape stable regardless of which
        # path ran, so admin/monitoring consumers see the same keys either way.
        summary.setdefault("candidate_pairs", 0)
        summary.setdefault("llm_confirmed", 0)
        return summary

    cutoff = dedup_window_cutoff()
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
        return {
            "total": 0,
            "candidate_pairs": 0,
            "llm_confirmed": 0,
            "grouped": 0,
            "groups": 0,
            "updated": 0,
        }

    ids = [e.id for e in events]
    parent: dict[int, int] = {eid: eid for eid in ids}
    events_by_id: dict[int, Event] = {e.id: e for e in events}

    # Stage 1: SQL time pre-filter (shared with the rule-only pass) → Python
    # fuzzy title/venue check. Stage 2: LLM tiebreaker on surviving candidates.
    candidate_pair_ids = await candidate_pair_ids_in_window(db, cutoff)

    candidate_pairs = 0
    llm_confirmed = 0

    for a_id, b_id in candidate_pair_ids:
        a = events_by_id.get(a_id)
        b = events_by_id.get(b_id)
        if a is None or b is None:
            continue
        if not is_candidate_pair(a, b):
            continue
        if candidate_pairs >= LLM_DEDUP_MAX_CANDIDATE_PAIRS_PER_PASS:
            log.warning(
                "dedup-llm: hit %d candidate pair cap; remaining pairs skipped this pass",
                LLM_DEDUP_MAX_CANDIDATE_PAIRS_PER_PASS,
            )
            break
        candidate_pairs += 1
        if await _llm_confirms_pair(a, b, db):
            _union(parent, a_id, b_id)
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
        len(events),
        candidate_pairs,
        llm_confirmed,
        group_count,
        updated,
    )
    return {
        "total": len(events),
        "candidate_pairs": candidate_pairs,
        "llm_confirmed": llm_confirmed,
        "grouped": len(assignments),
        "groups": group_count,
        "updated": updated,
    }
