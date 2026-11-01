"""
Daily 5 feed build: the nightly job and the onboarding single-user build.

Async and DB-driven. Scoring lives in ``score.py``, pick selection in
``selection.py``.
"""

from __future__ import annotations

import asyncio
from array import array
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import cast

from sqlalchemy import or_, select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.constants.core import TALLINN_TZ
from app.constants.ranking import (
    FEEDBACK_HISTORY_LOOKBACK_DAYS,
    DAILY5_SERIES_COOLDOWN_DAYS,
    DAILY_5_BACKFILL_MAX_PER_CATEGORY,
    DAILY_5_COUNT,
    DAILY_5_LOOKAHEAD_DAYS,
    DAILY_5_MAX_PER_CATEGORY,
    FEED_BUILD_USER_BATCH_SIZE,
    SCORE_INSERT_CHUNK_SIZE,
    SIGNAL_DISLIKE,
    SIGNAL_LIKE,
)
from app.models.events import Event
from app.models.feeds import DailyFeed, UserEventFeedback
from app.models.users import User, UserPersona
from app.events.queries import (
    canonical_event_filter,
    collapse_series_duplicates,
    event_not_ended_filter,
    event_series_key,
    public_event_filter,
    select_events_with_classification,
)
from app.events.venue import resolve_venue_name
from app.promotions.daily5 import prepare_daily5
from app.ranking.score import (
    AffinityCache,
    EventFactors,
    FeedbackContext,
    persona_weight_tuple,
    precompute_event_factors,
    score_event,
)
from app.ranking.selection import select_with_backfill

@dataclass
class _SharedFeedContext:
    """Candidate events + derived series keys — identical for every page of
    users in one build_daily_feeds run. Loaded once, threaded through."""

    event_rows: list[Event]
    candidate_series_key: dict[int, tuple[str, str]]
    event_factors: dict[int, EventFactors]
    # Run-scoped memos, so each 500-user page reuses what earlier pages already
    # resolved (Big-O audit #8): series keys of recently-shown events,
    # persona_id -> its canonical affinity vector (so the id()-keyed
    # affinity_cache below hits across pages — the vectors are held alive here),
    # and the affinity memo itself.
    shown_series_key: dict[int, tuple[str, str]] = field(default_factory=dict)
    persona_vectors: dict[int, dict] = field(default_factory=dict)
    affinity_cache: AffinityCache = field(default_factory=dict)
    # A user with no feedback scores every candidate from their persona mix
    # alone, so users sharing a mix share one score per candidate. Keyed on
    # the ordered (weight, id(vector)) pairs; values align with event_rows.
    # Bounded by the ordered persona picks onboarding allows, not by users.
    persona_only_scores: dict[tuple[tuple[float, int], ...], array] = field(
        default_factory=dict
    )


@dataclass
class _FeedBuildContext:
    """Everything the per-user scoring loop needs, bulk-loaded up front.

    A fixed number of queries independent of user count (the no-N+1 batch rule).
    """

    shared: _SharedFeedContext
    users: list[User]
    personas_by_user: dict[int, list[tuple[float, dict]]]
    fb_by_user: dict[int, list[UserEventFeedback]]
    recent_series_by_user: dict[int, set[tuple[str, str]]]
    # Aliases _SharedFeedContext.affinity_cache (run-scoped) — see
    # AffinityCache; must not outlive the context that holds the vectors.
    affinity_cache: AffinityCache = field(default_factory=dict)

    @property
    def event_rows(self) -> list[Event]:
        return self.shared.event_rows

    @property
    def candidate_series_key(self) -> dict[int, tuple[str, str]]:
        return self.shared.candidate_series_key

    @property
    def event_factors(self) -> dict[int, EventFactors]:
        return self.shared.event_factors


async def _load_recent_series_by_user(
    db: AsyncSession,
    user_ids: list[int],
    today: date,
    key_cache: dict[int, tuple[str, str]] | None = None,
) -> dict[int, set[tuple[str, str]]]:
    """Series keys each user was shown within the cooldown window.

    Suppresses repeat recommendations of the same recurring series across
    days — a multi-day series (one canonical event per day) would otherwise
    score well and be re-picked night after night. Feed-level filter,
    independent of dedup_group_id (series are intentionally not dedup-grouped).

    ``key_cache`` (event_id -> series key) is the run-scoped memo from
    ``_SharedFeedContext``: events a previous page already resolved are not
    re-queried.
    """
    if key_cache is None:
        key_cache = {}
    recent_series_by_user: dict[int, set[tuple[str, str]]] = {}
    cooldown_start = today - timedelta(days=DAILY5_SERIES_COOLDOWN_DAYS)
    recent_feed_rows = (
        await db.scalars(
            select(DailyFeed).where(
                DailyFeed.user_id.in_(user_ids),
                DailyFeed.feed_date >= cooldown_start,
                DailyFeed.feed_date < today,
            )
        )
    ).all()
    # event_id -> set of user_ids who were shown it within the window
    shown_event_users: dict[int, set[int]] = {}
    for feed_row in recent_feed_rows:
        for eid in feed_row.event_ids or []:
            shown_event_users.setdefault(eid, set()).add(feed_row.user_id)
    if shown_event_users:
        # Bulk SELECT, chunked at SCORE_INSERT_CHUNK_SIZE — shown events may be
        # outside the current lookahead window, so resolve them directly rather
        # than from event_rows. Unchunked this hits Postgres's per-statement
        # bind-param limit past ~32k ids (Big-O audit #5, item 1.6).
        shown_event_ids = [eid for eid in shown_event_users if eid not in key_cache]
        shown_event_rows: list[Event] = []
        for i in range(0, len(shown_event_ids), SCORE_INSERT_CHUNK_SIZE):
            chunk = shown_event_ids[i : i + SCORE_INSERT_CHUNK_SIZE]
            shown_event_rows.extend(
                (
                    await db.scalars(
                        select(Event)
                        .where(Event.id.in_(chunk))
                        .options(
                            load_only(
                                Event.id,
                                Event.title_orig,
                                Event.venue_name,
                                Event.venue_id,
                            ),
                            selectinload(Event.venue),
                        )
                    )
                ).all()
            )
        for shown_ev in shown_event_rows:
            key_cache[shown_ev.id] = event_series_key(
                shown_ev.title_orig, resolve_venue_name(shown_ev)
            )
        for eid, uids in shown_event_users.items():
            key = key_cache.get(eid)
            if key is None:
                continue
            for uid in uids:
                recent_series_by_user.setdefault(uid, set()).add(key)
    return recent_series_by_user


# Event columns the Daily 5 build reads off a candidate row: scoring
# (starts_at, dedup_group_id, venue-resolved lat/lng), series collapse
# (title_orig, venue_name/venue_id), and the pick (id). Adding a read of
# another column downstream needs it listed here — a deferred column
# raises MissingGreenlet on async access.
_CANDIDATE_EVENT_COLUMNS = (
    Event.id,
    Event.starts_at,
    Event.title_orig,
    Event.venue_name,
    Event.venue_id,
    Event.lat,
    Event.lng,
    Event.dedup_group_id,
)


async def _load_candidate_events(
    db: AsyncSession, now: datetime
) -> tuple[list[Event], dict[int, tuple[str, str]], dict[int, EventFactors]]:
    """Bulk-load published, non-excluded, upcoming-within-lookahead candidate
    events. Identical query for every page of users within one
    build_daily_feeds run — see _SharedFeedContext. Collapses same-series
    duplicates (see collapse_series_duplicates) before returning, along with
    each survivor's series key and its precomputed per-event score factors
    (see precompute_event_factors)."""
    cutoff = now + timedelta(days=DAILY_5_LOOKAHEAD_DAYS)
    event_rows = list(
        (
            await db.scalars(
                select_events_with_classification()
                .options(load_only(*_CANDIDATE_EVENT_COLUMNS))
                .where(
                    public_event_filter(),
                    event_not_ended_filter(now),
                    Event.starts_at <= cutoff,
                    canonical_event_filter(),
                )
            )
        ).all()
    )
    collapsed, candidate_series_key = collapse_series_duplicates(event_rows)
    return collapsed, candidate_series_key, precompute_event_factors(collapsed, now)


async def _verified_user_ids(db: AsyncSession) -> list[int]:
    """Verified user ids, paged by build_daily_feeds — see FEED_BUILD_USER_BATCH_SIZE.
    Filters on email_verified, not on persona/onboarding state — see the reverted
    _eligible_user_ids attempt in git history for why a persona-based filter is
    wrong (NEUTRAL_SCORE means a zero-persona user can still get a real feed).
    email_verified is different: a session token can only be issued from inside
    verify_magic_link, so an unverified row is provably one nobody has ever been
    able to log into — no feed or digest is reachable for it, so skipping it here
    wastes no legitimate value and closes the unverified-signup digest-spam gap."""
    return list(
        (await db.scalars(select(User.id).where(User.email_verified == true()))).all()
    )


async def _load_feed_build_context(
    db: AsyncSession,
    now: datetime,
    today: date,
    only_user_ids: list[int] | None = None,
    shared: _SharedFeedContext | None = None,
) -> _FeedBuildContext | None:
    """Bulk-load candidates plus all per-user data. None when there are no users.

    `only_user_ids` scopes the user query to a single user (or a small set) —
    used by `build_daily_feed_for_user` at onboarding completion. Every
    downstream lookup already filters by the loaded `user_ids`, so no other
    change is needed to build a feed for a subset of users.

    `shared` lets a paged caller (build_daily_feeds) pass in the candidate
    events + series keys once instead of re-running the identical query per
    page; when None (the default), it's loaded here exactly as before."""
    if shared is None:
        event_rows, candidate_series_key, event_factors = await _load_candidate_events(
            db, now
        )
        shared = _SharedFeedContext(
            event_rows=event_rows,
            candidate_series_key=candidate_series_key,
            event_factors=event_factors,
        )
    event_rows = shared.event_rows

    users_query = select(User)
    if only_user_ids is not None:
        users_query = users_query.where(User.id.in_(only_user_ids))
    users = list((await db.scalars(users_query)).all())
    user_ids = [u.id for u in users]
    if not users:
        return None

    personas_by_user: dict[int, list[tuple[float, dict]]] = {uid: [] for uid in user_ids}
    up_rows = (
        await db.scalars(
            select(UserPersona)
            .where(UserPersona.user_id.in_(user_ids))
            .options(selectinload(UserPersona.persona))
        )
    ).all()
    for up_row in up_rows:
        weight, vec = persona_weight_tuple(up_row)
        # Intern the vector per persona so every page (and user) shares one
        # object — the affinity memo is keyed on id(vec).
        vec = shared.persona_vectors.setdefault(up_row.persona_id, vec)
        personas_by_user.setdefault(up_row.user_id, []).append((weight, vec))

    fb_by_user: dict[int, list[UserEventFeedback]] = {uid: [] for uid in user_ids}
    fb_rows = (
        await db.scalars(
            select(UserEventFeedback)
            .where(
                UserEventFeedback.user_id.in_(user_ids),
                UserEventFeedback.signal.in_((SIGNAL_LIKE, SIGNAL_DISLIKE)),
                # Likes older than the lookback are numerically negligible
                # (0.9^days decay) — same bound as browse.py's
                # _load_feedback_context. Dislikes are kept regardless: a
                # dislike is a hard exclude, not a decayed weight (Big-O
                # audit M2).
                or_(
                    UserEventFeedback.created_at
                    >= now - timedelta(days=FEEDBACK_HISTORY_LOOKBACK_DAYS),
                    UserEventFeedback.signal == SIGNAL_DISLIKE,
                ),
            )
            .options(
                selectinload(UserEventFeedback.event)
                .load_only(Event.id, Event.dedup_group_id)
                .selectinload(Event.classification)
            )
        )
    ).all()
    for fb_row in fb_rows:
        fb_by_user.setdefault(fb_row.user_id, []).append(fb_row)

    recent_series_by_user = await _load_recent_series_by_user(
        db, user_ids, today, shared.shown_series_key
    )

    return _FeedBuildContext(
        shared=shared,
        users=users,
        personas_by_user=personas_by_user,
        fb_by_user=fb_by_user,
        recent_series_by_user=recent_series_by_user,
        affinity_cache=shared.affinity_cache,
    )


def _score_user_candidates(
    user: User,
    build_ctx: _FeedBuildContext,
    fb_ctx: FeedbackContext,
    now: datetime,
) -> tuple[list[tuple[float, Event]], list[tuple[float, Event]]]:
    """Score every candidate for one user, splitting series-cooled events into
    the backfill-only pool. Returns (scored, cooled_scored)."""
    user_persona_weights = build_ctx.personas_by_user.get(user.id, [])
    recent_series = build_ctx.recent_series_by_user.get(user.id, set())
    scored: list[tuple[float, Event]] = []
    cooled_scored: list[tuple[float, Event]] = []
    if not fb_ctx.rows:
        # No feedback: no exclusions, and the score depends on the persona
        # mix alone — reuse the first such user's scores (Big-O audit P2).
        memo = build_ctx.shared.persona_only_scores
        key = tuple((w, id(vec)) for w, vec in user_persona_weights)
        scores = memo.get(key)
        if scores is None:
            scores = array(
                "d",
                (
                    cast(
                        float,
                        score_event(
                            user_persona_weights,
                            fb_ctx,
                            event,
                            now,
                            precomputed=build_ctx.event_factors.get(event.id),
                            affinity_cache=build_ctx.affinity_cache,
                        ),
                    )
                    for event in build_ctx.event_rows
                ),
            )
            memo[key] = scores
        for event, s in zip(build_ctx.event_rows, scores):
            if build_ctx.candidate_series_key[event.id] in recent_series:
                cooled_scored.append((s, event))
            else:
                scored.append((s, event))
        return scored, cooled_scored
    for event in build_ctx.event_rows:
        # A dislike is a hard exclude (direct or via its dedup group) — not
        # just the -1 feedback term score_event would fold in for an
        # ungrouped event.
        if event.id in fb_ctx.disliked_event_ids or (
            event.dedup_group_id is not None
            and event.dedup_group_id in fb_ctx.disliked_groups
        ):
            continue
        s = score_event(
            user_persona_weights,
            fb_ctx,
            event,
            now,
            precomputed=build_ctx.event_factors.get(event.id),
            affinity_cache=build_ctx.affinity_cache,
        )
        if s is None:
            continue
        # Series cooldown: a candidate whose recurring series this user was
        # already shown within the window goes to the backfill-only pool —
        # still scored, only consumed if the fresh pool can't reach n.
        if build_ctx.candidate_series_key[event.id] in recent_series:
            cooled_scored.append((s, event))
        else:
            scored.append((s, event))
    return scored, cooled_scored


async def _persist_daily_feeds(db: AsyncSession, daily_feed_rows: list[dict]) -> None:
    """Bulk upsert DailyFeed rows keyed on (user_id, feed_date).

    An ON CONFLICT DO UPDATE — rather than a pre-loaded existing-row lookup
    plus a plain INSERT — so the synchronous onboarding-completion build
    (`build_daily_feed_for_user`) racing the scheduled `build_daily_feeds`
    job for the same user resolves atomically at the DB level instead of
    raising a unique-violation on the `(user_id, feed_date)` constraint that
    would roll back the whole batch's single commit.

    Chunked at SCORE_INSERT_CHUNK_SIZE rows/statement so a large user page
    can't exceed the Postgres wire protocol's ~32767 bind-parameter cap."""
    for i in range(0, len(daily_feed_rows), SCORE_INSERT_CHUNK_SIZE):
        chunk = daily_feed_rows[i : i + SCORE_INSERT_CHUNK_SIZE]
        stmt = pg_insert(DailyFeed).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "feed_date"],
            set_={
                "event_ids": stmt.excluded.event_ids,
                "built_at": stmt.excluded.built_at,
            },
        )
        await db.execute(stmt)


def _build_one_user_feed(
    user: User,
    build_ctx: _FeedBuildContext,
    now: datetime,
) -> list[int]:
    """Score and select one user's Daily 5 candidates.

    Returns the chosen event ids. Persisting the resulting DailyFeed
    row is the caller's job (see `_persist_daily_feeds`) so callers can batch
    every user's row into a single upsert statement."""
    fb_ctx = FeedbackContext.from_orm_rows(list(build_ctx.fb_by_user.get(user.id, [])))
    scored, cooled_scored = _score_user_candidates(user, build_ctx, fb_ctx, now)

    top_events = select_with_backfill(
        scored,
        cooled_scored,
        n=DAILY_5_COUNT,
        max_per_category=DAILY_5_MAX_PER_CATEGORY,
        backfill_max_per_category=DAILY_5_BACKFILL_MAX_PER_CATEGORY,
    )
    return [e.id for e in top_events]


async def build_daily_feeds(db: AsyncSession) -> dict:
    """
    Build personalized Daily 5 feeds for all active users.
    Runs daily at FEED_BUILD_HOUR via APScheduler.

    Pages the full user loop at FEED_BUILD_USER_BATCH_SIZE so memory is
    bounded by a batch size instead of total registered users — candidate
    events + series keys are loaded once (_SharedFeedContext) and reused
    across every page; only personas/feedback are reloaded
    per page. Filtered to verified users only (see _verified_user_ids); no
    persona-based pre-filtering beyond that — a user with zero personas can
    still get a non-empty feed and is opted into the digest by default.
    Scores are recomputed every build (no per-(user, event) score cache —
    the per-event factors are precomputed once and the affinity memo makes a
    user x event pass cheap). Returns summary dict for logging.
    """
    now = datetime.now(TALLINN_TZ)
    today = now.date()

    # Sponsored slot (#607): gate outcome rows for today, then one pick per
    # user with a full five. The five itself is never touched.
    daily5 = await prepare_daily5(db, now)

    user_ids = await _verified_user_ids(db)
    if not user_ids:
        await daily5.finish(db)
        await db.commit()
        return {
            "built": 0,
            "empty": 0,
            "total_users": 0,
            "candidate_events": 0,
        }

    event_rows, candidate_series_key, event_factors = await _load_candidate_events(db, now)
    shared = _SharedFeedContext(
        event_rows=event_rows,
        candidate_series_key=candidate_series_key,
        event_factors=event_factors,
    )

    built = empty = total_users = 0

    for i in range(0, len(user_ids), FEED_BUILD_USER_BATCH_SIZE):
        page_ids = user_ids[i : i + FEED_BUILD_USER_BATCH_SIZE]
        build_ctx = await _load_feed_build_context(
            db, now, today, only_user_ids=page_ids, shared=shared
        )
        if build_ctx is None:
            continue
        daily_feed_rows: list[dict] = []
        for user in build_ctx.users:
            # Scoring is pure CPU; yield between users so one page doesn't
            # hold the single process's event loop for seconds.
            await asyncio.sleep(0)
            event_ids = _build_one_user_feed(user, build_ctx, now)
            daily_feed_rows.append(
                {
                    "user_id": user.id,
                    "feed_date": today,
                    "event_ids": event_ids,
                    "built_at": now,
                }
            )
            if event_ids:
                built += 1
            else:
                empty += 1
        await _persist_daily_feeds(db, daily_feed_rows)
        await daily5.assign(db, {row["user_id"]: row["event_ids"] for row in daily_feed_rows})
        await db.commit()
        total_users += len(build_ctx.users)

    await daily5.finish(db)
    await db.commit()
    return {
        "built": built,
        "empty": empty,
        "total_users": total_users,
        "candidate_events": len(event_rows),
    }


async def build_daily_feed_for_user(db: AsyncSession, user_id: int) -> dict:
    """Build (or rebuild) today's Daily 5 for one user.

    Called synchronously at onboarding completion so a new user sees a
    populated feed immediately instead of waiting for the FEED_BUILD_HOUR job.
    Reuses the same candidate loading, scoring, series-cooldown, and scoring
    logic as `build_daily_feeds` — no duplicated ranking logic. The upsert in
    `_persist_daily_feeds` means this can safely race the scheduled job for
    the same user without either write failing."""
    now = datetime.now(TALLINN_TZ)
    today = now.date()

    build_ctx = await _load_feed_build_context(db, now, today, only_user_ids=[user_id])
    if build_ctx is None:
        return {"built": 0, "empty": 0, "total_users": 0, "candidate_events": 0}

    user = build_ctx.users[0]
    event_ids = _build_one_user_feed(user, build_ctx, now)

    await _persist_daily_feeds(
        db, [{"user_id": user.id, "feed_date": today, "event_ids": event_ids, "built_at": now}]
    )
    await db.commit()
    return {
        "built": 1 if event_ids else 0,
        "empty": 0 if event_ids else 1,
        "total_users": 1,
        "candidate_events": len(build_ctx.event_rows),
    }
