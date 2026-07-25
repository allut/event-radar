"""Tests for GET /explore (app/routers/browse.py)."""
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.constants import VALID_CATEGORIES, VALID_VIBES


def _scalars_result(items):
    m = MagicMock()
    m.all.return_value = items
    return m


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
        from app.routers.browse import _date_range_filter

        assert _date_range_filter(None, None) is None

    def test_date_to_only_is_exclusive_next_day(self):
        from app.routers.browse import _date_range_filter
        from app.constants import TALLINN_TZ

        cond = _date_range_filter(None, date(2026, 7, 20))
        compiled = str(cond.compile(compile_kwargs={"literal_binds": True}))
        assert "events.starts_at <" in compiled
        expected_bound = datetime(2026, 7, 21, 0, 0, tzinfo=TALLINN_TZ)
        assert str(expected_bound.year) in compiled

    def test_date_from_only_uses_ends_at_coalesce(self):
        from app.routers.browse import _date_range_filter

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
        mock_db.scalars.return_value = _scalars_result([make_event(1), make_event(2)])

        result = await _browse_sql_path(mock_db, [], "date", limit=2, offset=0, locale="en", user_id=1)

        assert result["total"] == 5
        assert result["limit"] == 2
        assert result["offset"] == 0
        assert result["has_more"] is True
        assert [e["id"] for e in result["events"]] == [1, 2]

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


class TestExploreEventsRouting:
    @pytest.mark.asyncio
    async def test_all_events_date_sort_uses_sql_path(
        self, mock_db, make_user, make_request, monkeypatch
    ):
        from app.routers import browse

        called = {}

        async def fake_sql_path(db, conds, sort, limit, offset, locale, user_id):
            called["path"] = "sql"
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        async def fake_scored_path(db, conds, for_you, sort, limit, offset, current_user, now, locale):
            called["path"] = "scored"
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        monkeypatch.setattr(browse, "_browse_sql_path", fake_sql_path)
        monkeypatch.setattr(browse, "_browse_scored_path", fake_scored_path)

        user = make_user()
        await browse.explore_events(
            request=make_request(method="GET", path="/explore"),
            sort="date",
            for_you=False,
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

        async def fake_sql_path(db, conds, sort, limit, offset, locale, user_id):
            called["path"] = "sql"
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        async def fake_scored_path(db, conds, for_you, sort, limit, offset, current_user, now, locale):
            called["path"] = "scored"
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        monkeypatch.setattr(browse, "_browse_sql_path", fake_sql_path)
        monkeypatch.setattr(browse, "_browse_scored_path", fake_scored_path)

        user = make_user()
        await browse.explore_events(
            request=make_request(method="GET", path="/explore"),
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

        async def fake_sql_path(db, conds, sort, limit, offset, locale, user_id):
            called["path"] = "sql"
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        async def fake_scored_path(db, conds, for_you, sort, limit, offset, current_user, now, locale):
            called["path"] = "scored"
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        monkeypatch.setattr(browse, "_browse_sql_path", fake_sql_path)
        monkeypatch.setattr(browse, "_browse_scored_path", fake_scored_path)

        user = make_user()
        await browse.explore_events(
            request=make_request(method="GET", path="/explore"),
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

        async def fake_scored_path(db, conds, for_you, sort, limit, offset, current_user, now, locale):
            seen_conds["conds"] = conds
            return {"events": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        monkeypatch.setattr(browse, "_browse_scored_path", fake_scored_path)

        user = make_user()
        await browse.explore_events(
            request=make_request(method="GET", path="/explore"),
            category="bogus-category",
            current_user=user,
            db=mock_db,
        )
        # Base conds only (public/not-ended/canonical) — no category overlap
        # clause was added since "bogus-category" isn't in VALID_CATEGORIES.
        assert len(seen_conds["conds"]) == 3
