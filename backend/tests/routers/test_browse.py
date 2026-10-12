"""Tests for GET /explore (app/routers/browse.py)."""
import asyncio
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from app._generated.shared_constants import VALID_CATEGORIES, VALID_VIBES
from tests.routers.conftest import scalars_returning as _scalars_result


def _persona_row(weight, affinity_vector):
    row = MagicMock()
    row.weight = weight
    row.persona = MagicMock()
    row.persona.affinity_vector = affinity_vector
    return row


def _feedback_row(signal, event_id, categories=None, dedup_group_id=None, created_at=None):
    row = MagicMock()
    row.signal = signal
    row.event_id = event_id
    row.created_at = created_at or datetime(2026, 5, 1, tzinfo=timezone.utc)
    row.event = MagicMock()
    row.event.dedup_group_id = dedup_group_id
    if categories is not None:
        row.event.classification = MagicMock()
        row.event.classification.categories = categories
    else:
        row.event.classification = None
    return row


class TestParseSlugList:
    def test_filters_invalid_and_dedupes(self):
        from app.routers.browse import _parse_slug_list

        valid = frozenset({"music", "theater"})
        result = _parse_slug_list("music, theater, music, bogus", valid)
        assert result == ["music", "theater"]

    def test_none_returns_empty(self):
        from app.routers.browse import _parse_slug_list

        assert _parse_slug_list(None, VALID_CATEGORIES) == []

    def test_empty_string_returns_empty(self):
        from app.routers.browse import _parse_slug_list

        assert _parse_slug_list("", VALID_VIBES) == []


class TestKeywordFilter:
    def test_escapes_wildcards_in_pattern(self):
        from app.routers.browse import _keyword_filter

        cond = _keyword_filter("100% off_sale")
        # cond = or_(title ILIKE ..., description ILIKE ...); first clause's
        # bound pattern must have literal wildcard chars backslash-escaped.
        pattern_value = cond.clauses[0].right.value
        assert pattern_value == "%100\\% off\\_sale%"


class TestDateRangeFilter:
    def test_both_none_returns_none(self):
        from app.events.queries import event_date_range_filter as _date_range_filter

        assert _date_range_filter(None, None) is None

    def test_date_to_only_is_exclusive_next_day(self):
        from app.events.queries import event_date_range_filter as _date_range_filter
        from app.constants.core import TALLINN_TZ

        cond = _date_range_filter(None, date(2026, 7, 20))
        compiled = str(cond.compile(compile_kwargs={"literal_binds": True}))
        assert "events.starts_at <" in compiled
        expected_bound = datetime(2026, 7, 21, 0, 0, tzinfo=TALLINN_TZ)
        assert str(expected_bound.year) in compiled

    def test_date_from_only_uses_ends_at_coalesce(self):
        from app.events.queries import event_date_range_filter as _date_range_filter

        cond = _date_range_filter(date(2026, 7, 20), None)
        compiled = str(cond.compile(compile_kwargs={"literal_binds": True}))
        assert "coalesce(events.ends_at, events.starts_at) >=" in compiled.lower()


class TestFreeFilter:
    def test_matches_zero_price_or_free_tier(self):
        from app.routers.browse import _free_filter

        compiled = str(_free_filter().compile(compile_kwargs={"literal_binds": True}))
        assert "events.price_min = 0" in compiled
        assert "events.has_free_tier" in compiled


class TestBrowseSqlPath:
    """Path A — for_you=False with sort in {date, price, quality}."""

    @pytest.mark.asyncio
    async def test_paginates_and_reports_has_more(self, mock_db, make_event):
        from app.routers.browse import _browse_sql_path

        mock_db.scalar.return_value = 5
        # has_more is now derived from a limit+1 sentinel row rather than
        # `total` — the query fetches one extra row past `limit`.
        mock_db.scalars.return_value = _scalars_result(
            [make_event(1), make_event(2), make_event(3)]
        )

        result = await _browse_sql_path(mock_db, [], "date", limit=2, offset=0, locale="en", user_id=1)

        assert result["total"] == 5
        assert result["limit"] == 2
        assert result["offset"] == 0
        assert result["has_more"] is True
        assert [e["id"] for e in result["events"]] == [1, 2]

    @pytest.mark.asyncio
    async def test_events_never_carry_listed_by_credit(self, mock_db, make_event):
        """The "Listed by X" credit is public-event-page-only (#419) — Explore
        must never carry it, regardless of claim status."""
        from app.routers.browse import _browse_sql_path

        mock_db.scalar.return_value = 1
        mock_db.scalars.return_value = _scalars_result([make_event(1)])

        result = await _browse_sql_path(
            mock_db, [], "date", limit=2, offset=0, locale="en", user_id=1
        )

        assert "listed_by" not in result["events"][0]

    @pytest.mark.asyncio
    async def test_last_page_has_more_false(self, mock_db, make_event):
        from app.routers.browse import _browse_sql_path

        mock_db.scalar.return_value = 1
        mock_db.scalars.return_value = _scalars_result([make_event(1)])

        result = await _browse_sql_path(
            mock_db, [], "price", limit=24, offset=0, locale="en", user_id=1
        )
        assert result["has_more"] is False

    @pytest.mark.asyncio
    async def test_zero_total_returns_empty(self, mock_db):
        from app.routers.browse import _browse_sql_path

        mock_db.scalar.return_value = 0
        mock_db.scalars.return_value = _scalars_result([])

        result = await _browse_sql_path(
            mock_db, [], "quality", limit=24, offset=0, locale="en", user_id=1
        )
        assert result["events"] == []
        assert result["total"] == 0
        assert result["has_more"] is False


class TestBrowseSqlPathKeyset:
    """Date sort pages on (starts_at, id); other sorts stay on OFFSET."""

    @staticmethod
    def _stmt_sql(mock_db):
        stmt = mock_db.scalars.call_args.args[0]
        return str(stmt.compile(compile_kwargs={"literal_binds": True}))

    @pytest.mark.asyncio
    async def test_date_sort_emits_next_cursor_when_more(self, mock_db, make_event):
        from app.routers.browse import _browse_sql_path
        from app.routers.utils import decode_page_cursor

        events = [make_event(1), make_event(2), make_event(3)]
        mock_db.scalar.return_value = 3
        mock_db.scalars.return_value = _scalars_result(events)

        result = await _browse_sql_path(
            mock_db, [], "date", limit=2, offset=0, locale="en", user_id=None
        )

        assert decode_page_cursor(result["next_cursor"]) == (
            events[1].starts_at,
            events[1].id,
        )

    @pytest.mark.asyncio
    async def test_last_page_has_no_next_cursor(self, mock_db, make_event):
        from app.routers.browse import _browse_sql_path

        mock_db.scalar.return_value = 1
        mock_db.scalars.return_value = _scalars_result([make_event(1)])

        result = await _browse_sql_path(
            mock_db, [], "date", limit=2, offset=0, locale="en", user_id=None
        )
        assert result["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_cursor_page_filters_keyset_skips_offset_and_total(
        self, mock_db, make_event
    ):
        from app.routers.browse import _browse_sql_path

        mock_db.scalars.return_value = _scalars_result([make_event(1)])
        ts = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)

        result = await _browse_sql_path(
            mock_db,
            [],
            "date",
            limit=2,
            offset=40,
            locale="en",
            user_id=None,
            cursor=(ts, 7),
        )

        sql = self._stmt_sql(mock_db)
        assert "(events.starts_at, events.id) >" in sql
        assert "OFFSET" not in sql.upper().replace("OFFSET 0", "")
        assert "ORDER BY events.starts_at ASC, events.id ASC" in sql
        mock_db.scalar.assert_not_called()
        assert result["total"] is None
        assert result["offset"] == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("sort", ["price", "quality"])
    async def test_non_date_sort_stays_offset_and_ignores_cursor(
        self, mock_db, make_event, sort
    ):
        from app.routers.browse import _browse_sql_path

        mock_db.scalar.return_value = 1
        mock_db.scalars.return_value = _scalars_result([make_event(1), make_event(2)])
        ts = datetime(2026, 5, 1, tzinfo=timezone.utc)

        result = await _browse_sql_path(
            mock_db, [], sort, limit=1, offset=0, locale="en", user_id=None, cursor=(ts, 7)
        )

        assert "(events.starts_at, events.id) >" not in self._stmt_sql(mock_db)
        assert "events.id ASC" in self._stmt_sql(mock_db)
        assert result["total"] == 1
        assert result["next_cursor"] is None


class TestBrowseScoredPath:
    """Path B — for_you=True or sort=relevance (Python scoring)."""

    @pytest.mark.asyncio
    async def test_for_you_drops_disliked_category(self, mock_db, make_event):
        from app.routers.browse import _browse_scored_path

        event_music = make_event(1)  # categories=["music"] (fixture default)
        event_theater = make_event(2)
        event_theater.classification.categories = ["theater"]
        event_theater.classification.vibes = ["mainstream"]

        persona_row = _persona_row(
            1.0, {"categories": {"music": 1.0, "theater": 1.0}, "vibes": {}}
        )
        dislike_row = _feedback_row("dislike", 99, categories=["theater"])

        mock_db.scalars.side_effect = [
            _scalars_result([event_music, event_theater]),  # candidates
            _scalars_result([persona_row]),  # personas
            _scalars_result([dislike_row]),  # feedback
            _scalars_result([event_music]),  # full-row refetch of survivors
        ]

        user = MagicMock()
        user.id = 1
        user.locale = "en"
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)

        result = await _browse_scored_path(
            mock_db, [], for_you=True, sort="relevance", limit=24, offset=0,
            current_user=user, now=now, locale="en",
        )

        assert [e["id"] for e in result["events"]] == [1]
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_hydration_query_reapplies_public_event_filter(self, mock_db, make_event):
        """OWASP audit G-3: the scored id list is cached for
        BROWSE_SCORE_CACHE_TTL_SECONDS, so the full-row hydration query must
        re-apply public_event_filter() itself — otherwise an id that went
        non-public (e.g. a takedown) in the meantime keeps hydrating for
        every caller sharing that cache entry until the cache expires."""
        from app.routers.browse import _browse_scored_path

        event_music = make_event(1)

        mock_db.scalars.side_effect = [
            _scalars_result([event_music]),  # candidates
            _scalars_result([]),  # personas
            _scalars_result([]),  # feedback
            _scalars_result([event_music]),  # full-row refetch of survivors
        ]

        user = MagicMock()
        user.id = 1
        user.locale = "en"
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)

        await _browse_scored_path(
            mock_db, [], for_you=False, sort="relevance", limit=24, offset=0,
            current_user=user, now=now, locale="en",
        )

        hydration_stmt = mock_db.scalars.call_args_list[-1].args[0]
        compiled = str(hydration_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "'published'" in compiled
        assert "is_explicit" in compiled
        assert "is_non_event" in compiled

    @pytest.mark.asyncio
    async def test_for_you_drops_below_affinity_threshold(self, mock_db, make_event):
        from app.routers.browse import _browse_scored_path

        event_match = make_event(1)  # categories=["music"]
        event_no_match = make_event(2)
        event_no_match.classification.categories = ["sports"]
        event_no_match.classification.vibes = ["mainstream"]

        # Persona vector only rewards "music" — "sports" gets no weight at all,
        # so its affinity falls below BROWSE_FORYOU_MIN_AFFINITY.
        persona_row = _persona_row(1.0, {"categories": {"music": 1.0}, "vibes": {}})

        mock_db.scalars.side_effect = [
            _scalars_result([event_match, event_no_match]),  # candidates
            _scalars_result([persona_row]),  # personas
            _scalars_result([]),  # feedback
            _scalars_result([event_match]),  # full-row refetch
        ]

        user = MagicMock()
        user.id = 1
        user.locale = "en"
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)

        result = await _browse_scored_path(
            mock_db, [], for_you=True, sort="relevance", limit=24, offset=0,
            current_user=user, now=now, locale="en",
        )

        assert [e["id"] for e in result["events"]] == [1]

    @pytest.mark.asyncio
    async def test_all_events_keeps_hard_excluded_ranked_last(self, mock_db, make_event):
        from app.routers.browse import _browse_scored_path

        event_disliked_group = make_event(3)
        event_disliked_group.dedup_group_id = 3
        event_normal = make_event(4)

        dislike_row = _feedback_row("dislike", 3, dedup_group_id=3)

        mock_db.scalars.side_effect = [
            _scalars_result([event_disliked_group, event_normal]),  # candidates
            _scalars_result([]),  # personas (none -> neutral affinity)
            _scalars_result([dislike_row]),  # feedback
            _scalars_result([event_disliked_group, event_normal]),  # full-row refetch
        ]

        user = MagicMock()
        user.id = 1
        user.locale = "en"
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)

        result = await _browse_scored_path(
            mock_db, [], for_you=False, sort="relevance", limit=24, offset=0,
            current_user=user, now=now, locale="en",
        )

        ids = [e["id"] for e in result["events"]]
        assert ids == [4, 3]  # hard-excluded event ranked last, not dropped
        assert result["total"] == 2

    @pytest.mark.asyncio
    async def test_date_sort_orders_by_starts_at(self, mock_db, make_event):
        from app.routers.browse import _browse_scored_path

        later = make_event(1, starts_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
        sooner = make_event(2, starts_at=datetime(2026, 5, 20, tzinfo=timezone.utc))

        mock_db.scalars.side_effect = [
            _scalars_result([later, sooner]),  # candidates
            _scalars_result([]),  # personas
            _scalars_result([]),  # feedback
            _scalars_result([sooner, later]),  # full-row refetch
        ]

        user = MagicMock()
        user.id = 1
        user.locale = "en"
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)

        result = await _browse_scored_path(
            mock_db, [], for_you=False, sort="date", limit=24, offset=0,
            current_user=user, now=now, locale="en",
        )

        assert [e["id"] for e in result["events"]] == [2, 1]

    @pytest.mark.asyncio
    async def test_pagination_offset_limit(self, mock_db, make_event):
        from app.routers.browse import _browse_scored_path

        events = [make_event(i, starts_at=datetime(2026, 5, i, tzinfo=timezone.utc)) for i in range(1, 6)]

        mock_db.scalars.side_effect = [
            _scalars_result(events),  # candidates
            _scalars_result([]),  # personas
            _scalars_result([]),  # feedback
            _scalars_result(events[2:4]),  # full-row refetch of page [3, 4]
        ]

        user = MagicMock()
        user.id = 1
        user.locale = "en"
        now = datetime(2026, 4, 1, tzinfo=timezone.utc)

        result = await _browse_scored_path(
            mock_db, [], for_you=False, sort="date", limit=2, offset=2,
            current_user=user, now=now, locale="en",
        )

        assert result["total"] == 5
        assert result["offset"] == 2
        assert result["has_more"] is True
        assert [e["id"] for e in result["events"]] == [3, 4]


class TestScoreCache:
    """_score_cache_get/_score_cache_set (TTL + LRU eviction), and that
    _browse_scored_path actually consults them when given a cache_key."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from app.routers.browse import _score_cache

        _score_cache.clear()
        yield
        _score_cache.clear()

    def test_miss_then_hit(self, monkeypatch):
        from app.routers import browse

        monkeypatch.setattr(browse.time, "monotonic", lambda: 100.0)
        key = (1, True, "relevance", (), (), False, None, None, None)

        assert browse._score_cache_get(key) is None
        browse._score_cache_set(key, [3, 1, 2])
        assert browse._score_cache_get(key) == [3, 1, 2]

    def test_expires_after_ttl(self, monkeypatch):
        from app.routers import browse

        key = (1, True, "relevance", (), (), False, None, None, None)
        monkeypatch.setattr(browse.time, "monotonic", lambda: 0.0)
        browse._score_cache_set(key, [1])

        monkeypatch.setattr(
            browse.time, "monotonic", lambda: browse.BROWSE_SCORE_CACHE_TTL_SECONDS + 1.0
        )
        assert browse._score_cache_get(key) is None
        assert key not in browse._score_cache

    def test_evicts_oldest_past_max_entries(self, monkeypatch):
        from app.routers import browse

        monkeypatch.setattr(browse, "BROWSE_SCORE_CACHE_MAX_ENTRIES", 2)
        monkeypatch.setattr(browse.time, "monotonic", lambda: 0.0)

        browse._score_cache_set(("k1",), [1])
        browse._score_cache_set(("k2",), [2])
        browse._score_cache_set(("k3",), [3])

        assert len(browse._score_cache) == 2
        assert ("k1",) not in browse._score_cache
        assert browse._score_cache_get(("k3",)) == [3]

    @pytest.mark.asyncio
    async def test_browse_scored_path_hit_skips_rescoring(self, mock_db, make_event):
        from app.routers.browse import _browse_scored_path

        events = [make_event(1), make_event(2)]
        # First call needs candidates/personas/feedback/full-row-refetch (4
        # scalars). A cache hit on the second call must only pay for the
        # full-row refetch of the (already-ranked) page — one more scalars
        # call, not another four.
        mock_db.scalars.side_effect = [
            _scalars_result(events),
            _scalars_result([]),
            _scalars_result([]),
            _scalars_result(events),
            _scalars_result(events),
        ]

        user = MagicMock()
        user.id = 1
        user.locale = "en"
        now = datetime(2026, 4, 1, tzinfo=timezone.utc)
        cache_key = (1, False, "date", (), (), False, None, None, None)

        first = await _browse_scored_path(
            mock_db, [], for_you=False, sort="date", limit=24, offset=0,
            current_user=user, now=now, locale="en", cache_key=cache_key,
        )
        second = await _browse_scored_path(
            mock_db, [], for_you=False, sort="date", limit=24, offset=0,
            current_user=user, now=now, locale="en", cache_key=cache_key,
        )

        assert [e["id"] for e in first["events"]] == [1, 2]
        assert [e["id"] for e in second["events"]] == [1, 2]
        # Exactly 5 scalars calls total (4 + 1) — proves the second call
        # skipped candidate load + scoring and only refetched full rows.
        assert mock_db.scalars.call_count == 5


class TestExploreEventsRouting:
    @pytest.mark.asyncio
    async def test_all_events_date_sort_uses_sql_path(
        self, mock_db, make_user, make_request, monkeypatch
    ):
        from app.routers import browse

        called = {}

        async def fake_sql_path(db, conds, sort, limit, offset, locale, user_id, cursor=None):
            called["path"] = "sql"
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        async def fake_scored_path(db, conds, for_you, sort, limit, offset, current_user, now, locale, cache_key=None):
            called["path"] = "scored"
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        monkeypatch.setattr(browse, "_browse_sql_path", fake_sql_path)
        monkeypatch.setattr(browse, "_browse_scored_path", fake_scored_path)

        user = make_user()
        await browse.explore_events(
            request=make_request(method="GET", path="/explore"),
            q=None,
            sort="date",
            for_you=False,
            cursor=None,
            current_user=user,
            db=mock_db,
        )
        assert called["path"] == "sql"

    @pytest.mark.asyncio
    async def test_relevance_sort_uses_scored_path_even_for_all_events(
        self, mock_db, make_user, make_request, monkeypatch
    ):
        from app.routers import browse

        called = {}

        async def fake_sql_path(db, conds, sort, limit, offset, locale, user_id, cursor=None):
            called["path"] = "sql"
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        async def fake_scored_path(db, conds, for_you, sort, limit, offset, current_user, now, locale, cache_key=None):
            called["path"] = "scored"
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        monkeypatch.setattr(browse, "_browse_sql_path", fake_sql_path)
        monkeypatch.setattr(browse, "_browse_scored_path", fake_scored_path)

        user = make_user()
        await browse.explore_events(
            request=make_request(method="GET", path="/explore"),
            q=None,
            sort="relevance",
            for_you=False,
            current_user=user,
            db=mock_db,
        )
        assert called["path"] == "scored"

    @pytest.mark.asyncio
    async def test_for_you_uses_scored_path(
        self, mock_db, make_user, make_request, monkeypatch
    ):
        from app.routers import browse

        called = {}

        async def fake_sql_path(db, conds, sort, limit, offset, locale, user_id, cursor=None):
            called["path"] = "sql"
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        async def fake_scored_path(db, conds, for_you, sort, limit, offset, current_user, now, locale, cache_key=None):
            called["path"] = "scored"
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        monkeypatch.setattr(browse, "_browse_sql_path", fake_sql_path)
        monkeypatch.setattr(browse, "_browse_scored_path", fake_scored_path)

        user = make_user()
        await browse.explore_events(
            request=make_request(method="GET", path="/explore"),
            q=None,
            sort="date",
            for_you=True,
            current_user=user,
            db=mock_db,
        )
        assert called["path"] == "scored"

    @pytest.mark.asyncio
    async def test_invalid_sort_raises_400(self, mock_db, make_user, make_request):
        from fastapi import HTTPException
        from app.routers.browse import explore_events

        user = make_user()
        with pytest.raises(HTTPException) as exc_info:
            await explore_events(
                request=make_request(method="GET", path="/explore"),
                q=None,
                sort="bogus",
                current_user=user,
                db=mock_db,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_category_is_dropped_not_rejected(
        self, mock_db, make_user, make_request, monkeypatch
    ):
        from app.routers import browse

        seen_conds = {}

        async def fake_scored_path(db, conds, for_you, sort, limit, offset, current_user, now, locale, cache_key=None):
            seen_conds["conds"] = conds
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        monkeypatch.setattr(browse, "_browse_scored_path", fake_scored_path)

        user = make_user()
        await browse.explore_events(
            request=make_request(method="GET", path="/explore"),
            q=None,
            category="bogus-category",
            current_user=user,
            db=mock_db,
        )
        # Base conds only (public/not-ended/canonical) — no category overlap
        # clause was added since "bogus-category" isn't in VALID_CATEGORIES.
        assert len(seen_conds["conds"]) == 3


class TestAnonymousExplore:
    """#234 — GET /explore for current_user=None (anonymous, no session)."""

    @pytest.mark.asyncio
    async def test_score_and_rank_uses_anonymous_formula_no_persona_or_feedback_query(
        self, mock_db, make_event
    ):
        from app.routers.browse import _score_and_rank_candidates

        events = [make_event(1), make_event(2)]
        # Only one scalars call expected (candidates) — no persona/feedback
        # loads for an anonymous caller.
        mock_db.scalars.side_effect = [_scalars_result(events)]
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)

        ids = await _score_and_rank_candidates(
            mock_db, [], for_you=False, sort="relevance", current_user=None, now=now
        )

        assert set(ids) == {1, 2}
        assert mock_db.scalars.call_count == 1

    @pytest.mark.asyncio
    async def test_score_and_rank_never_hard_excludes(self, mock_db, make_event):
        from app.routers.browse import _score_and_rank_candidates

        event = make_event(1)
        event.dedup_group_id = 5
        mock_db.scalars.side_effect = [_scalars_result([event])]
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)

        # for_you=True still keeps the event — no feedback context exists to
        # hard-exclude it, and persona_affinity([], ...) == NEUTRAL_SCORE
        # passes BROWSE_FORYOU_MIN_AFFINITY.
        ids = await _score_and_rank_candidates(
            mock_db, [], for_you=True, sort="relevance", current_user=None, now=now
        )
        assert ids == [1]

    @pytest.mark.asyncio
    async def test_browse_scored_path_anonymous_returns_no_signals(
        self, mock_db, make_event
    ):
        from app.routers.browse import _browse_scored_path

        events = [make_event(1)]
        mock_db.scalars.side_effect = [
            _scalars_result(events),  # candidates
            _scalars_result(events),  # full-row refetch (no persona/feedback calls)
        ]
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)

        result = await _browse_scored_path(
            mock_db, [], for_you=False, sort="relevance", limit=24, offset=0,
            current_user=None, now=now, locale="en",
        )
        assert [e["id"] for e in result["events"]] == [1]
        assert mock_db.scalars.call_count == 2

    @pytest.mark.asyncio
    async def test_browse_sql_path_anonymous_user_id_none_returns_no_signals(
        self, mock_db, make_event
    ):
        from app.routers.browse import _browse_sql_path

        mock_db.scalar.return_value = 1
        mock_db.scalars.return_value = _scalars_result([make_event(1)])

        result = await _browse_sql_path(
            mock_db, [], "date", limit=24, offset=0, locale="en", user_id=None
        )
        assert [e["id"] for e in result["events"]] == [1]

    @pytest.mark.asyncio
    async def test_explore_events_anonymous_sql_path_passes_user_id_none(
        self, mock_db, make_request, monkeypatch
    ):
        from app.routers import browse

        called = {}

        async def fake_sql_path(db, conds, sort, limit, offset, locale, user_id, cursor=None):
            called["user_id"] = user_id
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        monkeypatch.setattr(browse, "_browse_sql_path", fake_sql_path)

        await browse.explore_events(
            request=make_request(method="GET", path="/explore"),
            q=None,
            sort="date",
            for_you=False,
            cursor=None,
            current_user=None,
            db=mock_db,
        )
        assert called["user_id"] is None

    @pytest.mark.asyncio
    async def test_explore_events_anonymous_uses_sentinel_cache_key(
        self, mock_db, make_request, monkeypatch
    ):
        from app.routers import browse

        seen = {}

        async def fake_scored_path(db, conds, for_you, sort, limit, offset, current_user, now, locale, cache_key=None):
            seen["cache_key"] = cache_key
            seen["current_user"] = current_user
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        monkeypatch.setattr(browse, "_browse_scored_path", fake_scored_path)

        await browse.explore_events(
            request=make_request(method="GET", path="/explore"),
            q=None,
            sort="relevance",
            current_user=None,
            db=mock_db,
        )
        assert seen["current_user"] is None
        assert seen["cache_key"][0] == browse.BROWSE_ANON_CACHE_SENTINEL

    @pytest.mark.asyncio
    async def test_concurrent_misses_on_same_key_coalesce_to_one_recompute(
        self, mock_db, make_event
    ):
        """Locked requirement (#234): concurrent misses on the same cache key
        must not each recompute — the first miss computes, the rest await the
        same lock then read the now-populated cache."""
        from app.routers.browse import _score_cache, _score_cache_locks, _browse_scored_path

        _score_cache.clear()
        _score_cache_locks.clear()

        events = [make_event(1)]
        call_count = {"n": 0}

        async def slow_scan(*args, **kwargs):
            call_count["n"] += 1
            await asyncio.sleep(0.01)
            return [1]

        with pytest.MonkeyPatch.context() as mp:
            from app.routers import browse

            mp.setattr(browse, "_score_and_rank_candidates", slow_scan)
            mock_db.scalars.return_value = _scalars_result(events)

            now = datetime(2026, 5, 10, tzinfo=timezone.utc)
            cache_key = (browse.BROWSE_ANON_CACHE_SENTINEL, False, "relevance", (), (), False, None, None, None)

            results = await asyncio.gather(
                *[
                    _browse_scored_path(
                        mock_db, [], for_you=False, sort="relevance", limit=24, offset=0,
                        current_user=None, now=now, locale="en", cache_key=cache_key,
                    )
                    for _ in range(5)
                ]
            )

        assert call_count["n"] == 1
        for result in results:
            assert [e["id"] for e in result["events"]] == [1]

        _score_cache.clear()
        _score_cache_locks.clear()
