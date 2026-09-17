"""Two-stage deduplication: rule pre-filter + LLM tiebreaker.

Stage 1: ``is_candidate_pair()`` from rules.py (fuzzy title + time + venue).
Stage 2: LLM tiebreaker on candidate pairs only (1 call per pair, cached).

Merge condition: LLM returns ``{"same": true, "confidence": ≥ 0.7}``.
On confirm: union-find produces clusters → ``dedup_group_id`` is the cluster's
best representative (publish-status pin, then data quality, then ``min(event_id)``
tie-break; see ``rules.build_cluster_assignments``).

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

import asyncio
import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    LLM_BACKLOG_MAX_DRAIN_PASSES,
    LLM_BACKLOG_RETRY_SECONDS,
    LLM_BATCH_FANOUT_CONCURRENCY,
    LLM_CLASSIFY_VENUE_FALLBACK,
    LLM_DEDUP_CONFIDENCE_THRESHOLD,
    LLM_DEDUP_HASH_QUERY_CHUNK_SIZE,
    LLM_DEDUP_MAX_FRESH_LLM_CALLS_PER_PASS,
    LLM_DEDUP_TITLE_MAX_LEN,
    LLM_DEDUP_VENUE_MAX_LEN,
    LLM_TASK_DEDUP,
)
from app.llm.prompts import LLM_DEDUP_PROMPT_TEMPLATE, escape_prompt_delimiters
from app.dedup.rules import (
    union,
    apply_same_day_title_unions,
    build_cluster_assignments,
    bulk_assign_dedup_groups,
    candidate_pair_ids_in_window,
    clear_stale_dedup_groups,
    dedup_window_cutoff,
    is_candidate_pair,
    load_dedup_candidate_events,
    load_description_lengths,
    run_dedup_pass,
    same_group,
)
from app.llm.router import content_hash, llm_available, llm_http_client, llm_json_or_none
from app.models.models import Event, LlmCall

log = logging.getLogger(__name__)


_EventFragment = tuple[str, str, str]


def _event_fragment(
    event: Event, fragment_cache: dict[int, _EventFragment]
) -> _EventFragment:
    """Escaped/truncated (title, date, venue) prompt fragment for one event,
    memoized per event id in ``fragment_cache``.

    These fragments are invariant per event but rebuilt by ``_build_prompt``
    on every pair — up to DEDUP_CANDIDATE_PAIR_MAX pairs, most of them sharing
    an event with several other pairs — so without this memo the same
    strftime/escape/truncate/slice work runs once per *pair* instead of once
    per *event* (Big-O audit #5, item 2.6).
    """
    cached = fragment_cache.get(event.id)
    if cached is not None:
        return cached
    fragment: _EventFragment = (
        escape_prompt_delimiters(event.title_orig[:LLM_DEDUP_TITLE_MAX_LEN]),
        event.starts_at.strftime("%Y-%m-%d %H:%M"),
        escape_prompt_delimiters(
            (event.venue_name or LLM_CLASSIFY_VENUE_FALLBACK)[:LLM_DEDUP_VENUE_MAX_LEN]
        ),
    )
    fragment_cache[event.id] = fragment
    return fragment


def _build_prompt(
    a: Event, b: Event, fragment_cache: dict[int, _EventFragment] | None = None
) -> str:
    cache = fragment_cache if fragment_cache is not None else {}
    title_a, date_a, venue_a = _event_fragment(a, cache)
    title_b, date_b, venue_b = _event_fragment(b, cache)
    return LLM_DEDUP_PROMPT_TEMPLATE.format(
        title_a=title_a,
        date_a=date_a,
        venue_a=venue_a,
        title_b=title_b,
        date_b=date_b,
        venue_b=venue_b,
    )


def _dedup_pair_hash(
    a: Event, b: Event, fragment_cache: dict[int, _EventFragment] | None = None
) -> str:
    """Content hash for the (a, b) dedup prompt.

    Must derive the *identical* hash ``llm_json`` stores in
    ``llm_calls.content_hash`` for this pair, so the bulk prefetch can find
    cached decisions without re-importing a private helper. Couples to
    ``_build_prompt`` / ``LLM_DEDUP_PROMPT_TEMPLATE``: changing either
    invalidates the entire dedup LLM cache (expected one-time re-warm, not a
    bug).
    """
    return content_hash(_build_prompt(a, b, fragment_cache))


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


async def _llm_confirms_pair(
    a: Event,
    b: Event,
    db: AsyncSession,
    http_client: httpx.AsyncClient | None = None,
    fragment_cache: dict[int, _EventFragment] | None = None,
) -> bool:
    """Return True if the LLM says the pair is the same event with sufficient confidence.

    Note: event_id=a.id is stored in llm_calls for audit; the pair identity is
    recoverable from the content_hash (which encodes both titles + dates).

    Only called on a ``cached_decisions`` miss, so the bulk prefetch has
    already established there is no cached row — pass an empty
    ``prefetched_cache`` to make ``llm_json`` skip its own per-call SELECT.
    """
    prompt = _build_prompt(a, b, fragment_cache)
    response = await llm_json_or_none(
        LLM_TASK_DEDUP,
        prompt,
        db,
        event_id=a.id,
        context=f"llm dedup failed for pair ({a.id}, {b.id}) — treating as distinct",
        http_client=http_client,
        prefetched_cache={},
    )
    if response is None:
        return False
    result, _ = response
    try:
        confirmed = _verdict_confirms(result)
    except (TypeError, ValueError) as exc:
        log.warning(
            "llm dedup bad response for pair (%d, %d): %s — treating as distinct",
            a.id,
            b.id,
            exc,
        )
        return False
    log.debug(
        "llm dedup: a=%d b=%d result=%s → %s",
        a.id,
        b.id,
        result,
        "MERGE" if confirmed else "skip",
    )
    return confirmed


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
                    LlmCall.task == LLM_TASK_DEDUP,
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


async def _find_llm_survivor_pairs(
    db: AsyncSession,
    cutoff: datetime,
    events_by_id: dict[int, Event],
    parent: dict[int, int],
    fragment_cache: dict[int, _EventFragment] | None = None,
) -> list[tuple[Event, Event, str]]:
    """Stage 1: SQL time pre-filter (shared with the rule-only pass) → Python
    fuzzy title/venue check. Pairs already collapsed by the same-day union are
    skipped (no LLM call needed). Returns (a, b, content_hash) triples."""
    candidate_pair_ids = await candidate_pair_ids_in_window(db, cutoff)
    survivors: list[tuple[Event, Event, str]] = []
    for a_id, b_id in candidate_pair_ids:
        a = events_by_id.get(a_id)
        b = events_by_id.get(b_id)
        if a is None or b is None:
            continue
        if same_group(parent, a_id, b_id):
            continue
        if not is_candidate_pair(
            a,
            b,
            bypass_venue_on_near_exact_title=True,
            bypass_title_on_exact_time_and_venue=True,
        ):
            continue
        survivors.append((a, b, _dedup_pair_hash(a, b, fragment_cache)))
    return survivors


async def _resolve_survivor_pairs(
    db: AsyncSession,
    survivors: list[tuple[Event, Event, str]],
    cached_decisions: dict[str, bool],
    parent: dict[int, int],
    http_client: httpx.AsyncClient,
    *,
    max_fresh_calls: int = LLM_DEDUP_MAX_FRESH_LLM_CALLS_PER_PASS,
    fragment_cache: dict[int, _EventFragment] | None = None,
) -> tuple[int, int, int]:
    """Stage 2: resolve each survivor via the cache, else a fresh LLM call
    (bounded by ``max_fresh_calls``). Unions confirmed pairs into ``parent``
    and records every freshly-decided verdict (confirmed or not) into
    ``cached_decisions`` in place, so a caller looping this function across
    sub-passes over the same survivor list never re-asks the LLM about a pair
    it already resolved this run. Returns (llm_confirmed, fresh_calls, deferred).

    Fresh calls fan out concurrently (bounded by ``LLM_BATCH_FANOUT_CONCURRENCY``)
    in vertex-disjoint waves: within one wave no two pairs share an event id, so
    a wave's calls can't make each other redundant mid-flight — union-find's
    early-exit (skip a pair already merged by an earlier decision) still fires
    exactly as it would sequentially, just re-checked once per wave instead of
    once per pair. Pairs that share an event id with one already in the current
    wave wait for the next wave, by which point the earlier wave's unions are
    applied and same_group may now skip them for free.
    """
    llm_confirmed = 0
    fresh_calls = 0
    deferred_pairs = 0

    # Filter pass: apply cached decisions immediately (cheap, sequential), and
    # collect only cache-miss pairs — up to max_fresh_calls, in survivor order,
    # matching the pre-concurrency budget semantics — for the wave fan-out below.
    pending: list[tuple[Event, Event, str]] = []
    for a, b, pair_hash in survivors:
        if same_group(parent, a.id, b.id):
            continue
        cached = cached_decisions.get(pair_hash)
        if cached is not None:
            if cached:
                union(parent, a.id, b.id)
                llm_confirmed += 1
            continue
        pending.append((a, b, pair_hash))

    to_call = pending[:max_fresh_calls]
    deferred_pairs = len(pending) - len(to_call)

    semaphore = asyncio.Semaphore(LLM_BATCH_FANOUT_CONCURRENCY)

    async def _confirm_one(a: Event, b: Event) -> bool:
        async with semaphore:
            return await _llm_confirms_pair(a, b, db, http_client, fragment_cache)

    remaining = to_call
    while remaining:
        wave: list[tuple[Event, Event, str]] = []
        wave_ids: set[int] = set()
        still_remaining: list[tuple[Event, Event, str]] = []
        for a, b, pair_hash in remaining:
            if same_group(parent, a.id, b.id):
                # Resolved for free by an earlier wave's union — no call needed.
                continue
            if a.id in wave_ids or b.id in wave_ids:
                still_remaining.append((a, b, pair_hash))
                continue
            wave.append((a, b, pair_hash))
            wave_ids.add(a.id)
            wave_ids.add(b.id)

        if not wave:
            break

        results = await asyncio.gather(
            *(_confirm_one(a, b) for a, b, _ in wave), return_exceptions=True
        )
        fresh_calls += len(wave)

        for (a, b, pair_hash), result in zip(wave, results):
            if isinstance(result, BaseException):
                log.error(
                    "dedup-llm: pair (%d, %d) raised during LLM confirm: %s",
                    a.id,
                    b.id,
                    result,
                )
                confirmed = False
            else:
                confirmed = result
            cached_decisions[pair_hash] = confirmed
            if confirmed:
                union(parent, a.id, b.id)
                llm_confirmed += 1

        remaining = still_remaining

    if deferred_pairs > 0:
        log.info(
            "dedup-llm: fresh-call budget (%d) reached; %d pair(s) deferred to "
            "next pass (self-healing)",
            max_fresh_calls,
            deferred_pairs,
        )
    return llm_confirmed, fresh_calls, deferred_pairs


async def run_dedup_pass_llm(
    db: AsyncSession, *, retry_seconds: int = LLM_BACKLOG_RETRY_SECONDS
) -> dict:
    """Two-stage dedup: rule pre-filter + cache-aware LLM tiebreaker.

    Loads all non-cancelled events in the lookback window, finds candidate pairs
    via the rule filter, then resolves each against the ``llm_calls`` cache
    (bulk-prefetched by content hash) before falling back to a fresh LLM call.
    Cached decisions are applied to the union-find regardless of the fresh-call
    budget — clustering is always complete w.r.t. everything decided so far.

    Caps *fresh* (cache-miss) network calls at
    ``LLM_DEDUP_MAX_FRESH_LLM_CALLS_PER_PASS`` per internal sub-pass to bound
    each burst against the LLM provider (a slow or rate-limited fallback could
    otherwise hold the connection open indefinitely).

    ``retry_seconds`` never sleeps *inside* this call — this function's whole
    body runs inside one caller-opened DB session (``run_in_session`` in
    jobs.py) plus one ``llm_http_client()``, and a sleep here would hold both
    open for the duration, which is worse than the problem it would be trying
    to solve. Instead ``retry_seconds`` only decides whether it's safe to loop
    multiple sub-passes over the same already-loaded survivors (no reload) at
    all: ``retry_seconds=0`` (the admin-triggered ``dedup_pass_drain_now``,
    which already accepts a full unpaced burst in one blocking request) loops
    up to ``LLM_BACKLOG_MAX_DRAIN_PASSES`` sub-passes back-to-back, since no
    pacing is wanted anyway. Any non-zero ``retry_seconds`` (the scheduled
    ``dedup_pass_drained`` default) runs exactly one sub-pass and returns
    immediately with whatever remains deferred — pacing between attempts is
    then jobs.py's external ``_drain_backlog`` sleeping *between* fresh,
    closed-and-reopened sessions, exactly as it did before this function had
    an internal loop at all.

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
    events = await load_dedup_candidate_events(db, cutoff)

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

    # Deterministic same-day session collapse (no LLM) before the tiebreaker, so
    # already-collapsed pairs are skipped below instead of spending the fresh-call
    # budget — this removes the timed-entry / session storm from the LLM path.
    apply_same_day_title_unions(parent, events)

    # Per-event prompt-fragment memo, shared across the whole pass (Big-O
    # audit #5, item 2.6) — see _event_fragment.
    fragment_cache: dict[int, _EventFragment] = {}
    survivors = await _find_llm_survivor_pairs(
        db, cutoff, events_by_id, parent, fragment_cache
    )

    # Bulk prefetch (once, before the loop) — satisfies the no-N+1 batch rule.
    cached_decisions = await _prefetch_cached_decisions(
        db, [pair_hash for _, _, pair_hash in survivors]
    )

    # Loop the (cheap, in-memory) resolve step over the same already-loaded
    # survivors/cache instead of re-running the expensive load + SQL self-join
    # + Python fuzzy scan per sub-pass — but only when retry_seconds==0 (no
    # pacing wanted, see docstring). Otherwise a single sub-pass, matching the
    # pre-H4 behavior exactly: jobs.py's external _drain_backlog is what re-runs
    # this whole function (fresh session, fresh reload) after its own sleep.
    max_sub_passes = LLM_BACKLOG_MAX_DRAIN_PASSES if retry_seconds == 0 else 1
    llm_confirmed = fresh_calls = 0
    deferred_pairs = len(survivors)
    async with llm_http_client() as http_client:
        for _ in range(max_sub_passes):
            sub_confirmed, sub_fresh, deferred_pairs = await _resolve_survivor_pairs(
                db,
                survivors,
                cached_decisions,
                parent,
                http_client,
                max_fresh_calls=LLM_DEDUP_MAX_FRESH_LLM_CALLS_PER_PASS,
                fragment_cache=fragment_cache,
            )
            llm_confirmed += sub_confirmed
            fresh_calls += sub_fresh
            if deferred_pairs == 0:
                break

    desc_len_by_id = await load_description_lengths(db, ids)
    assignments = build_cluster_assignments(parent, ids, events_by_id, desc_len_by_id)

    updated = await bulk_assign_dedup_groups(db, events, assignments)

    await clear_stale_dedup_groups(db, cutoff)

    group_count = len({gid for gid in assignments.values()})
    log.info(
        "dedup-llm pass: %d events, %d candidate pairs, %d llm-confirmed "
        "(%d fresh calls, %d deferred) → %d groups, %d updated",
        len(events),
        len(survivors),
        llm_confirmed,
        fresh_calls,
        deferred_pairs,
        group_count,
        updated,
    )
    return {
        "total": len(events),
        "candidate_pairs": len(survivors),
        "llm_confirmed": llm_confirmed,
        "fresh_calls": fresh_calls,
        "deferred_pairs": deferred_pairs,
        "grouped": len(assignments),
        "groups": group_count,
        "updated": updated,
    }
