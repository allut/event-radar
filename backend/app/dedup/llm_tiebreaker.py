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

Cache-aware loop: before consulting the LLM, all fuzzy-passing pairs are bulk
prefetched against the ``llm_calls`` cache by content hash. Cached decisions are
applied to the union-find regardless of the fresh-call budget, so every run
produces clustering that is complete w.r.t. everything decided so far. Only
cache-miss pairs consume the fresh-call budget; the rest are deferred to the
next pass. Once the cache is warm for the whole candidate set, ``deferred_pairs``
reaches 0 and every run is fully correct.
"""

import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    EVENT_STATUS_CANCELLED,
    LLM_DEDUP_CONFIDENCE_THRESHOLD,
    LLM_DEDUP_HASH_QUERY_CHUNK_SIZE,
    LLM_DEDUP_MAX_FRESH_LLM_CALLS_PER_PASS,
    LLM_DEDUP_PROMPT_TEMPLATE,
    LLM_DEDUP_TITLE_MAX_LEN,
    LLM_DEDUP_VENUE_MAX_LEN,
)
from app.dedup.rules import (
    union,
    build_cluster_assignments,
    candidate_pair_ids_in_window,
    dedup_window_cutoff,
    is_candidate_pair,
    run_dedup_pass,
)
from app.llm.router import LLMError, content_hash, llm_available, llm_json
from app.models.models import Event, LlmCall

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


def _dedup_pair_hash(a: Event, b: Event) -> str:
    """Content hash for the (a, b) dedup prompt.

    Must derive the *identical* hash ``llm_json`` stores in
    ``llm_calls.content_hash`` for this pair, so the bulk prefetch can find
    cached decisions without re-importing a private helper. Couples to
    ``_build_prompt`` / ``LLM_DEDUP_PROMPT_TEMPLATE``: changing either
    invalidates the entire dedup LLM cache (expected one-time re-warm, not a
    bug).
    """
    return content_hash(_build_prompt(a, b))


def _verdict_confirms(result: dict) -> bool:
    """Return True if an LLM dedup response confirms a duplicate pair.

    Shared acceptance criteria for both cached and freshly-fetched responses:
    ``same`` is truthy and ``confidence >= LLM_DEDUP_CONFIDENCE_THRESHOLD``.
    Raises ``TypeError``/``ValueError`` if ``confidence`` is not numeric —
    callers decide how to treat a malformed response.
    """
    same = result.get("same", False)
    confidence = float(result.get("confidence", 0.0))
    return bool(same) and confidence >= LLM_DEDUP_CONFIDENCE_THRESHOLD


async def _llm_confirms_pair(a: Event, b: Event, db: AsyncSession) -> bool:
    """Return True if the LLM says the pair is the same event with sufficient confidence.

    Note: event_id=a.id is stored in llm_calls for audit; the pair identity is
    recoverable from the content_hash (which encodes both titles + dates).
    """
    prompt = _build_prompt(a, b)
    try:
        result, _ = await llm_json("dedup", prompt, db, event_id=a.id)
        confirmed = _verdict_confirms(result)
        log.debug(
            "llm dedup: a=%d b=%d result=%s → %s",
            a.id,
            b.id,
            result,
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


async def _prefetch_cached_decisions(
    db: AsyncSession, hashes: list[str]
) -> dict[str, bool]:
    """Bulk-fetch cached dedup verdicts for the given content hashes.

    One query per chunk (bounded by ``LLM_DEDUP_HASH_QUERY_CHUNK_SIZE``), rows
    read oldest-first so the newest row per hash wins by dict overwrite. A
    malformed cached response is treated as *absent* (popped, not stored as a
    cached reject) so a corrupt old row can't permanently suppress a real
    decision — the pair simply re-fetches, subject to the fresh-call budget.
    """
    cached_decisions: dict[str, bool] = {}
    unique_hashes = list(dict.fromkeys(hashes))
    for i in range(0, len(unique_hashes), LLM_DEDUP_HASH_QUERY_CHUNK_SIZE):
        chunk = unique_hashes[i : i + LLM_DEDUP_HASH_QUERY_CHUNK_SIZE]
        rows = (
            await db.execute(
                select(LlmCall.content_hash, LlmCall.response_json)
                .where(
                    LlmCall.task == "dedup",
                    LlmCall.content_hash.in_(chunk),
                    LlmCall.response_json.is_not(None),
                )
                .order_by(LlmCall.created_at)
            )
        ).all()
        for row_hash, response_json in rows:
            try:
                cached_decisions[row_hash] = _verdict_confirms(response_json)
            except (AttributeError, TypeError, ValueError):
                cached_decisions.pop(row_hash, None)
    return cached_decisions


async def run_dedup_pass_llm(db: AsyncSession) -> dict:
    """Two-stage dedup: rule pre-filter + cache-aware LLM tiebreaker.

    Loads all non-cancelled events in the lookback window, finds candidate pairs
    via the rule filter, then resolves each against the ``llm_calls`` cache
    (bulk-prefetched by content hash) before falling back to a fresh LLM call.
    Cached decisions are applied to the union-find regardless of the fresh-call
    budget — clustering is always complete w.r.t. everything decided so far.

    Caps *fresh* (cache-miss) network calls at
    ``LLM_DEDUP_MAX_FRESH_LLM_CALLS_PER_PASS`` per pass to bound DB session
    lifetime (Cerebras fallback at 1 req/min could otherwise hold the
    connection open indefinitely). Pairs that can't be decided within the
    budget are deferred to the next pass — the backlog drains across
    successive runs and, once the cache is warm, every run is fully correct.

    Falls back gracefully if no LLM providers are configured (returns
    rule-only result).

    Returns a summary dict with ``total``, ``candidate_pairs``,
    ``llm_confirmed``, ``fresh_calls``, ``deferred_pairs``, ``grouped``,
    ``groups``, ``updated`` keys.
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
        summary.setdefault("fresh_calls", 0)
        summary.setdefault("deferred_pairs", 0)
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
            "fresh_calls": 0,
            "deferred_pairs": 0,
            "grouped": 0,
            "groups": 0,
            "updated": 0,
        }

    ids = [e.id for e in events]
    parent: dict[int, int] = {eid: eid for eid in ids}
    events_by_id: dict[int, Event] = {e.id: e for e in events}

    # Stage 1: SQL time pre-filter (shared with the rule-only pass) → Python
    # fuzzy title/venue check. Stage 2: cache-aware LLM tiebreaker on survivors.
    candidate_pair_ids = await candidate_pair_ids_in_window(db, cutoff)

    survivors: list[tuple[Event, Event, str]] = []
    for a_id, b_id in candidate_pair_ids:
        a = events_by_id.get(a_id)
        b = events_by_id.get(b_id)
        if a is None or b is None:
            continue
        if not is_candidate_pair(a, b):
            continue
        survivors.append((a, b, _dedup_pair_hash(a, b)))

    # Bulk prefetch (once, before the loop) — satisfies the no-N+1 batch rule.
    cached_decisions = await _prefetch_cached_decisions(
        db, [pair_hash for _, _, pair_hash in survivors]
    )

    candidate_pairs = 0
    llm_confirmed = 0
    fresh_calls = 0
    deferred_pairs = 0

    for a, b, pair_hash in survivors:
        candidate_pairs += 1
        cached = cached_decisions.get(pair_hash)
        if cached is not None:
            if cached:
                union(parent, a.id, b.id)
                llm_confirmed += 1
            continue
        if fresh_calls >= LLM_DEDUP_MAX_FRESH_LLM_CALLS_PER_PASS:
            deferred_pairs += 1
            continue
        fresh_calls += 1
        if await _llm_confirms_pair(a, b, db):
            union(parent, a.id, b.id)
            llm_confirmed += 1

    if deferred_pairs > 0:
        log.info(
            "dedup-llm: fresh-call budget (%d) reached; %d pair(s) deferred to "
            "next pass (self-healing)",
            LLM_DEDUP_MAX_FRESH_LLM_CALLS_PER_PASS,
            deferred_pairs,
        )

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
        "dedup-llm pass: %d events, %d candidate pairs, %d llm-confirmed "
        "(%d fresh calls, %d deferred) → %d groups, %d updated",
        len(events),
        candidate_pairs,
        llm_confirmed,
        fresh_calls,
        deferred_pairs,
        group_count,
        updated,
    )
    return {
        "total": len(events),
        "candidate_pairs": candidate_pairs,
        "llm_confirmed": llm_confirmed,
        "fresh_calls": fresh_calls,
        "deferred_pairs": deferred_pairs,
        "grouped": len(assignments),
        "groups": group_count,
        "updated": updated,
    }
