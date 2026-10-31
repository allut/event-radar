"""Tests for the Daily 5 feed build (``app.ranking.daily_feed``)."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.events import Event
from app.ranking.score import FeedbackContext
from tests.ranking.conftest import fixed_now, make_ctx, make_event


@pytest.fixture(autouse=True)
def _no_daily5_slot(monkeypatch):
    """These tests drive build_daily_feeds against a mocked session; the
    Sponsored-slot pick (#607) has its own real-Postgres tests."""
    from app.promotions.daily5 import Daily5Run

    run = Daily5Run(today=date(2026, 5, 10), now=fixed_now(), eligible=[])
    monkeypatch.setattr(run, "finish", AsyncMock())
    monkeypatch.setattr("app.ranking.daily_feed.prepare_daily5", AsyncMock(return_value=run))


class TestLoadCandidateEventsColumns:
    async def test_candidate_query_loads_only_audited_columns(self, mock_db):
        from app.ranking.daily_feed import _load_candidate_events

        mock_db.scalars.return_value = _scalar_result([])

        await _load_candidate_events(mock_db, fixed_now())

        stmt = mock_db.scalars.call_args_list[0].args[0]
        compiled = str(stmt.compile())
        select_clause = compiled.split("FROM")[0]
        for col in ("id", "starts_at", "title_orig", "venue_name", "venue_id",
                    "lat", "lng", "dedup_group_id"):
            assert f"events.{col}" in select_clause
        # heavy text columns must stay deferred
        assert "events.description" not in select_clause
        assert "events.title_localized" not in select_clause


class TestRecentSeriesKeyCache:
    async def test_events_resolved_by_an_earlier_page_are_not_requeried(self, mock_db):
        from datetime import date
        from unittest.mock import MagicMock

        from app.ranking.daily_feed import _load_recent_series_by_user

        key = ("jazz night", "kuku klubi")
        feed_row = MagicMock(user_id=7, event_ids=[11])
        mock_db.scalars.side_effect = [_scalar_result([feed_row])]

        recent = await _load_recent_series_by_user(
            mock_db, [7], date(2026, 6, 10), {11: key}
        )

        assert recent == {7: {key}}
        assert mock_db.scalars.call_count == 1  # feeds only; no event re-query


class TestBuildDailyFeedsExplicitFilter:
    async def test_event_query_excludes_explicit_events(self, mock_db):
        from app.ranking.daily_feed import build_daily_feeds

        mock_db.scalars.side_effect = [
            _scalar_result([1]),  # user ids (all registered)
            _scalar_result([]),  # candidate events
            _scalar_result([]),  # users (page query) — none found, build_ctx None
        ]

        result = await build_daily_feeds(mock_db)

        assert result["total_users"] == 0
        stmt = mock_db.scalars.call_args_list[1].args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "is_explicit" in compiled
        assert "is_non_event" in compiled
        assert "false" in compiled.lower()

    async def test_event_query_keeps_ongoing_events_via_ends_at(self, mock_db):
        # Candidate window must use event_not_ended_filter, not a bare
        # starts_at >= now check, so an ongoing offer (past starts_at, future
        # ends_at) still reaches the Daily 5 pool.
        from app.ranking.daily_feed import build_daily_feeds

        mock_db.scalars.side_effect = [
            _scalar_result([1]),  # user ids (all registered)
            _scalar_result([]),  # candidate events
            _scalar_result([]),  # users (page query)
        ]

        await build_daily_feeds(mock_db)

        stmt = mock_db.scalars.call_args_list[1].args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "coalesce(events.ends_at, events.starts_at) >=" in compiled

    async def test_verified_user_ids_query_filters_on_email_verified(self, mock_db):
        # Filters on email_verified (a user with zero UserPersona rows can
        # still get a non-empty feed, so no persona-based pre-filter — see
        # _verified_user_ids' docstring for why the two are different).
        from app.ranking.daily_feed import _verified_user_ids

        mock_db.scalars.return_value = _scalar_result([])

        await _verified_user_ids(mock_db)

        stmt = mock_db.scalars.call_args_list[0].args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "user_personas" not in compiled
        assert "email_verified" in compiled
        assert "SELECT users.id" in compiled


def _scalar_result(items: list) -> MagicMock:
    r = MagicMock()
    r.all.return_value = items
    return r


def _feed_event(eid: int, title: str, venue: str, categories: list[str] | None = None) -> Event:
    e = make_event(event_id=eid, categories=categories)
    e.title_orig = title
    e.venue_name = venue
    return e


def _user(uid: int) -> MagicMock:
    u = MagicMock()
    u.id = uid
    return u


def _dislike_row(event_id: int, user_id: int = 1) -> MagicMock:
    row = MagicMock()
    row.user_id = user_id
    row.event_id = event_id
    row.signal = "dislike"
    row.created_at = fixed_now()
    row.event = MagicMock()
    row.event.dedup_group_id = None
    row.event.classification = None
    return row


class TestBuildDailyFeedsSeriesCooldown:
    async def test_recent_series_excluded_from_pool(self, mock_db):
        # User 1 was shown event 150 (series "van gogh"/"vaba lava") within the
        # cooldown window. Today's candidate 100 shares that series key, so it is
        # skipped; candidate 200 (a different series) is kept. Fresh filler
        # candidates (distinct categories) fill the pool to 5 on their own, so
        # backfill never kicks in — this isolates pure cooldown exclusion.
        from app.ranking.daily_feed import build_daily_feeds

        ev100 = _feed_event(100, "Van Gogh", "Vaba Lava")
        ev200 = _feed_event(200, "Concert X", "Hall", ["music"])
        ev201 = _feed_event(201, "Play", "Theater", ["theater"])
        ev202 = _feed_event(202, "Film", "Cinema", ["cinema"])
        ev203 = _feed_event(203, "Match", "Stadium", ["sports"])
        ev204 = _feed_event(204, "Workshop", "Studio", ["workshops"])
        ev150 = _feed_event(150, "Van Gogh", "Vaba Lava")  # yesterday's instance
        df = MagicMock()
        df.user_id = 1
        df.event_ids = [150]

        mock_db.scalars.side_effect = [
            _scalar_result([1]),               # user ids (all registered)
            _scalar_result([ev100, ev200, ev201, ev202, ev203, ev204]),  # candidate events
            _scalar_result([_user(1)]),        # users
            _scalar_result([]),                # personas
            _scalar_result([]),                # feedback
            _scalar_result([df]),              # cooldown-window feeds
            _scalar_result([ev150]),           # shown events resolved
        ]

        await build_daily_feeds(mock_db)

        upsert_stmt = mock_db.execute.call_args.args[0]
        compiled = str(upsert_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "(1, " in compiled
        assert "ARRAY[200, 201, 202, 203, 204]" in compiled  # 100 cooled down, never backfilled

    async def test_no_recent_history_keeps_series(self, mock_db):
        # Empty cooldown window (e.g. the series last appeared outside it) → the
        # shown-events query is skipped and the candidate is kept.
        from app.ranking.daily_feed import build_daily_feeds

        ev100 = _feed_event(100, "Van Gogh", "Vaba Lava")

        mock_db.scalars.side_effect = [
            _scalar_result([1]),       # user ids (all registered)
            _scalar_result([ev100]),   # candidate events
            _scalar_result([_user(1)]),
            _scalar_result([]),        # personas
            _scalar_result([]),        # feedback
            _scalar_result([]),        # cooldown-window feeds (empty → no shown-events query)
        ]

        await build_daily_feeds(mock_db)

        upsert_stmt = mock_db.execute.call_args.args[0]
        compiled = str(upsert_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "ARRAY[100]" in compiled

    async def test_other_users_history_does_not_affect_this_user(self, mock_db):
        # Only user 2 was shown the series; user 1's feed must still include it.
        # 5 fresh filler candidates (distinct categories) ensure each user's
        # own fresh pool can fill 5 without backfill — isolating per-user
        # cooldown exclusion from the backfill mechanism.
        from app.ranking.daily_feed import build_daily_feeds

        ev100 = _feed_event(100, "Van Gogh", "Vaba Lava")
        ev201 = _feed_event(201, "Play", "Theater", ["theater"])
        ev202 = _feed_event(202, "Film", "Cinema", ["cinema"])
        ev203 = _feed_event(203, "Match", "Stadium", ["sports"])
        ev204 = _feed_event(204, "Workshop", "Studio", ["workshops"])
        ev205 = _feed_event(205, "Gig", "Club", ["nightlife"])
        ev150 = _feed_event(150, "Van Gogh", "Vaba Lava")
        df = MagicMock()
        df.user_id = 2  # belongs to a different user
        df.event_ids = [150]

        mock_db.scalars.side_effect = [
            _scalar_result([1, 2]),                  # user ids (all registered)
            _scalar_result([ev100, ev201, ev202, ev203, ev204, ev205]),  # candidate events
            _scalar_result([_user(1), _user(2)]),    # users
            _scalar_result([]),                      # personas
            _scalar_result([]),                      # feedback
            _scalar_result([df]),                    # cooldown-window feeds (user 2)
            _scalar_result([ev150]),                 # shown events resolved
        ]

        await build_daily_feeds(mock_db)

        # Both users' rows are batched into one upsert statement.
        upsert_stmt = mock_db.execute.call_args.args[0]
        compiled = str(upsert_stmt.compile(compile_kwargs={"literal_binds": True}))
        # user 1 unaffected by user 2's history — keeps 100 among its top 5
        assert "(1, " in compiled and "ARRAY[100, 201, 202, 203, 204]" in compiled
        # user 2 cooled down on 100, but its own fresh pool fills 5 → no backfill needed
        assert "(2, " in compiled and "ARRAY[201, 202, 203, 204, 205]" in compiled

    async def test_cooldown_query_restricts_to_recent_date_window(self, mock_db):
        # The cooldown feed query (5th scalars call) must bound feed_date to
        # [today - DAILY5_SERIES_COOLDOWN_DAYS, today).
        from app.ranking.daily_feed import build_daily_feeds

        ev100 = _feed_event(100, "Van Gogh", "Vaba Lava")
        mock_db.scalars.side_effect = [
            _scalar_result([1]),       # user ids (all registered)
            _scalar_result([ev100]),   # candidate events
            _scalar_result([_user(1)]),
            _scalar_result([]),        # personas
            _scalar_result([]),        # feedback
            _scalar_result([]),        # cooldown-window feeds
        ]

        await build_daily_feeds(mock_db)

        cooldown_stmt = mock_db.scalars.call_args_list[5].args[0]
        compiled = str(cooldown_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "daily_feeds.feed_date >=" in compiled
        assert "daily_feeds.feed_date <" in compiled

    async def test_cooled_series_backfilled_when_fresh_pool_short(self, mock_db):
        # 4 fresh candidates (distinct categories, no cap collision) can't reach
        # DAILY_5_COUNT=5 on their own. The 5th candidate shares a series with
        # yesterday's feed (cooldown) but gets backfilled in to complete the 5.
        from app.ranking.daily_feed import build_daily_feeds

        ev1 = _feed_event(1, "Concert", "Hall", ["music"])
        ev2 = _feed_event(2, "Play", "Theater", ["theater"])
        ev3 = _feed_event(3, "Film", "Cinema", ["cinema"])
        ev4 = _feed_event(4, "Match", "Stadium", ["sports"])
        ev5 = _feed_event(5, "Workshop", "Studio", ["workshops"])
        ev150 = _feed_event(150, "Workshop", "Studio", ["workshops"])  # yesterday's instance
        df = MagicMock()
        df.user_id = 1
        df.event_ids = [150]

        mock_db.scalars.side_effect = [
            _scalar_result([1]),                        # user ids (all registered)
            _scalar_result([ev1, ev2, ev3, ev4, ev5]),  # candidate events
            _scalar_result([_user(1)]),                 # users
            _scalar_result([]),                          # personas
            _scalar_result([]),                          # feedback
            _scalar_result([df]),                        # cooldown-window feeds
            _scalar_result([ev150]),                      # shown events resolved
        ]

        await build_daily_feeds(mock_db)

        upsert_stmt = mock_db.execute.call_args.args[0]
        compiled = str(upsert_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "ARRAY[1, 2, 3, 4, 5]" in compiled  # ev5 backfilled in despite cooldown

    async def test_disliked_cooled_event_not_backfilled(self, mock_db):
        # Same shortfall as above, but the cooled candidate is directly
        # disliked — scoring must exclude it from the backfill pool entirely
        # (no fabrication).
        from app.ranking.daily_feed import build_daily_feeds

        ev1 = _feed_event(1, "Concert", "Hall", ["music"])
        ev2 = _feed_event(2, "Play", "Theater", ["theater"])
        ev3 = _feed_event(3, "Film", "Cinema", ["cinema"])
        ev5 = _feed_event(5, "Workshop", "Studio", ["workshops"])
        ev150 = _feed_event(150, "Workshop", "Studio", ["workshops"])
        df = MagicMock()
        df.user_id = 1
        df.event_ids = [150]

        mock_db.scalars.side_effect = [
            _scalar_result([1]),                     # user ids (all registered)
            _scalar_result([ev1, ev2, ev3, ev5]),   # candidate events
            _scalar_result([_user(1)]),              # users
            _scalar_result([]),                       # personas
            _scalar_result([_dislike_row(5)]),         # feedback: direct dislike of ev5
            _scalar_result([df]),                     # cooldown-window feeds
            _scalar_result([ev150]),                   # shown events resolved
        ]
        await build_daily_feeds(mock_db)

        upsert_stmt = mock_db.execute.call_args.args[0]
        compiled = str(upsert_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "ARRAY[1, 2, 3]" in compiled  # ev5 excluded, feed stays short — no fabrication


class TestCollapseSeriesDuplicates:
    def test_keeps_earliest_starts_at_per_series(self):
        from app.events.queries import collapse_series_duplicates

        later = _feed_event(1, "Workshop", "Studio")
        later.starts_at = fixed_now() + timedelta(days=5)
        earlier = _feed_event(2, "Workshop", "Studio")
        earlier.starts_at = fixed_now() + timedelta(days=1)
        middle = _feed_event(3, "Workshop", "Studio")
        middle.starts_at = fixed_now() + timedelta(days=3)

        collapsed, series_key_by_event_id = collapse_series_duplicates(
            [later, earlier, middle]
        )

        assert [e.id for e in collapsed] == [2]
        assert set(series_key_by_event_id) == {2}

    def test_ties_on_starts_at_break_deterministically_by_event_id(self):
        # Two instances sharing an exact starts_at (e.g. duplicate showtimes)
        # must resolve to the same survivor every call, independent of input
        # order or DB row order (the underlying query has no ORDER BY).
        from app.events.queries import collapse_series_duplicates

        same_time = fixed_now() + timedelta(days=2)
        ev5 = _feed_event(5, "Workshop", "Studio")
        ev5.starts_at = same_time
        ev2 = _feed_event(2, "Workshop", "Studio")
        ev2.starts_at = same_time

        collapsed_a, _ = collapse_series_duplicates([ev5, ev2])
        collapsed_b, _ = collapse_series_duplicates([ev2, ev5])

        assert [e.id for e in collapsed_a] == [2]
        assert [e.id for e in collapsed_b] == [2]

    def test_distinct_series_all_kept(self):
        from app.events.queries import collapse_series_duplicates

        ev1 = _feed_event(1, "Concert", "Hall")
        ev2 = _feed_event(2, "Play", "Theater")

        collapsed, series_key_by_event_id = collapse_series_duplicates([ev1, ev2])

        assert {e.id for e in collapsed} == {1, 2}
        assert set(series_key_by_event_id) == {1, 2}


class TestBuildDailyFeedsSeriesDuplicateCollapse:
    async def test_only_nearest_date_instance_reaches_candidate_pool(self, mock_db):
        # A workshop running Tue/Thu/Sat ingests as 3 distinct Event rows
        # sharing an event_series_key. Only the soonest-starting one (event 2)
        # should ever reach scoring/selection — the feed must never contain
        # more than one instance of the same series.
        from app.ranking.daily_feed import build_daily_feeds

        ev1 = _feed_event(1, "Workshop", "Studio", ["workshops"])
        ev1.starts_at = fixed_now() + timedelta(days=5)
        ev2 = _feed_event(2, "Workshop", "Studio", ["workshops"])
        ev2.starts_at = fixed_now() + timedelta(days=1)
        ev3 = _feed_event(3, "Workshop", "Studio", ["workshops"])
        ev3.starts_at = fixed_now() + timedelta(days=3)

        mock_db.scalars.side_effect = [
            _scalar_result([1]),                # user ids (all registered)
            _scalar_result([ev1, ev2, ev3]),    # candidate events (same series)
            _scalar_result([_user(1)]),          # users
            _scalar_result([]),                  # personas
            _scalar_result([]),                  # feedback
            _scalar_result([]),                  # cooldown-window feeds
        ]

        result = await build_daily_feeds(mock_db)

        assert result["candidate_events"] == 1
        upsert_stmt = mock_db.execute.call_args.args[0]
        compiled = str(upsert_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "ARRAY[2]" in compiled  # only the nearest-date instance survives


class TestBuildDailyFeedForUser:
    # build_daily_feed_for_user calls _load_feed_build_context with shared=None
    # (the default), so it still loads candidate events itself in one query —
    # no eligibility query, no _SharedFeedContext reuse. Call sequence unchanged.
    async def test_builds_feed_for_single_user_only(self, mock_db):
        # Onboarding-completion build: scopes the user query to one id and
        # writes exactly one DailyFeed row, reusing the same candidate
        # loading / scoring / cooldown / caching pipeline as build_daily_feeds.
        from app.ranking.daily_feed import build_daily_feed_for_user

        ev1 = _feed_event(1, "Concert", "Hall", ["music"])
        ev2 = _feed_event(2, "Play", "Theater", ["theater"])

        mock_db.scalars.side_effect = [
            _scalar_result([ev1, ev2]),  # candidate events
            _scalar_result([_user(7)]),  # users (scoped to user_id=7)
            _scalar_result([]),  # personas
            _scalar_result([]),  # feedback
            _scalar_result([]),  # cooldown-window feeds
        ]

        result = await build_daily_feed_for_user(mock_db, 7)

        upsert_stmt = mock_db.execute.call_args.args[0]
        compiled = str(upsert_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "(7, " in compiled
        assert "ARRAY[1, 2]" in compiled
        assert result["total_users"] == 1
        assert result["built"] == 1
        mock_db.commit.assert_awaited_once()

        # The users query must scope to the requested id, not select all users.
        users_stmt = mock_db.scalars.call_args_list[1].args[0]
        compiled = str(users_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "users.id IN (7)" in compiled

    async def test_no_user_found_returns_empty_summary(self, mock_db):
        from app.ranking.daily_feed import build_daily_feed_for_user

        mock_db.scalars.side_effect = [
            _scalar_result([]),  # candidate events
            _scalar_result([]),  # users — none found (e.g. deleted mid-request)
        ]

        result = await build_daily_feed_for_user(mock_db, 999)

        assert result == {
            "built": 0,
            "empty": 0,
            "total_users": 0,
            "candidate_events": 0,
        }
        mock_db.execute.assert_not_awaited()
        mock_db.commit.assert_not_awaited()


class TestBuildDailyFeedsBatching:
    """FEED_BUILD_USER_BATCH_SIZE pages the user loop — candidate events must
    still be loaded exactly once (the RAM-savings claim), each page commits
    independently, and the aggregate summary must match a hand-computed
    single-pass expectation over the same users/events."""

    async def test_pages_users_reusing_shared_candidates(self, mock_db, monkeypatch):
        import app.ranking.daily_feed as daily_feed_module

        monkeypatch.setattr(daily_feed_module, "FEED_BUILD_USER_BATCH_SIZE", 2)

        ev1 = _feed_event(1, "Concert", "Hall", ["music"])
        ev2 = _feed_event(2, "Play", "Theater", ["theater"])

        # 5 registered users, batch size 2 → pages of [1,2], [3,4], [5].
        # Each page: users, personas, feedback, cooldown-window feeds (4 scalars
        # calls/page — the cached-score load is a db.execute — and no
        # shown-events query, since cooldown windows are empty). all-user-ids + candidate-events precede all pages.
        mock_db.scalars.side_effect = [
            _scalar_result([1, 2, 3, 4, 5]),  # user ids (all registered)
            _scalar_result([ev1, ev2]),  # candidate events (loaded once)
            _scalar_result([_user(1), _user(2)]),
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result([_user(3), _user(4)]),
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result([_user(5)]),
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result([]),
        ]

        result = await daily_feed_module.build_daily_feeds(mock_db)

        assert mock_db.commit.await_count == 4  # one per page, plus the final Daily 5 slot commit

        # Candidate-events query ran exactly once regardless of page count —
        # the core RAM-savings claim (identified by its is_explicit marker).
        event_query_calls = [
            call
            for call in mock_db.scalars.call_args_list
            if "is_explicit"
            in str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        ]
        assert len(event_query_calls) == 1

        # Hand-computed single-pass expectation: 5 users, each scored against
        # the same 2 candidates with no feedback/cooldown — every user
        # gets a 2-event feed (built), no empties.
        assert result == {
            "built": 5,
            "empty": 0,
            "total_users": 5,
            "candidate_events": 2,
        }


class TestPersonaOnlyScoreMemo:
    """Users without feedback share one score per candidate per persona mix."""

    def _build_ctx(self, users, personas_by_user, recent_series_by_user, fb_by_user=None):
        from app.ranking.daily_feed import _FeedBuildContext, _SharedFeedContext
        from app.ranking.score import precompute_event_factors

        events = [
            make_event(event_id=1, categories=["music"], vibes=["chill"], quality=0.9),
            make_event(event_id=2, categories=["theater"], vibes=["social"], quality=0.4),
            make_event(event_id=3, categories=["music", "nightlife"], vibes=["underground"]),
        ]
        series = {e.id: (f"title-{e.id}", "venue") for e in events}
        shared = _SharedFeedContext(
            event_rows=events,
            candidate_series_key=series,
            event_factors=precompute_event_factors(events, fixed_now()),
        )
        return _FeedBuildContext(
            shared=shared,
            users=users,
            personas_by_user=personas_by_user,
            fb_by_user=fb_by_user or {},
            recent_series_by_user=recent_series_by_user,
            affinity_cache=shared.affinity_cache,
        ), events

    def test_second_user_with_same_mix_reuses_scores(self, monkeypatch):
        from app.ranking import daily_feed as daily_feed_mod

        vec = {"categories": {"music": 1.0, "theater": -0.5}, "vibes": {"chill": 0.5}}
        u1, u2 = _user(1), _user(2)
        build_ctx, events = self._build_ctx(
            [u1, u2],
            {1: [(1.0, vec)], 2: [(1.0, vec)]},
            {2: {("title-2", "venue")}},
        )
        calls = []
        real = daily_feed_mod.score_event
        monkeypatch.setattr(
            daily_feed_mod, "score_event", lambda *a, **k: calls.append(1) or real(*a, **k)
        )

        first = daily_feed_mod._score_user_candidates(u1, build_ctx, FeedbackContext(), fixed_now())
        second = daily_feed_mod._score_user_candidates(u2, build_ctx, FeedbackContext(), fixed_now())

        assert len(calls) == len(events)
        expected = {
            e.id: real([(1.0, vec)], FeedbackContext(), e, fixed_now()) for e in events
        }
        assert {e.id: s for s, e in first[0]} == pytest.approx(expected)
        assert [e.id for _, e in second[0]] == [1, 3]
        assert [e.id for _, e in second[1]] == [2]  # series cooldown still per user
        assert {e.id: s for s, e in second[0] + second[1]} == pytest.approx(expected)

    def test_user_with_feedback_is_scored_individually(self):
        from app.ranking import daily_feed as daily_feed_mod

        vec = {"categories": {"music": 1.0}}
        u1 = _user(1)
        build_ctx, _ = self._build_ctx([u1], {1: [(1.0, vec)]}, {})
        fb_ctx = make_ctx(("dislike", 1, ["music"], None, fixed_now()))

        scored, _ = daily_feed_mod._score_user_candidates(u1, build_ctx, fb_ctx, fixed_now())

        assert [e.id for _, e in scored] == [2, 3]
        assert build_ctx.shared.persona_only_scores == {}
