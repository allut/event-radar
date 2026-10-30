"""Tests for GET /public/showcase, GET /public/counts (app/routers/public.py)."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.routers.conftest import scalars_returning as _scalars_result


def _agg_row(
    upcoming_count=1008,
    venue_count=205,
    furthest_date=datetime(2027, 1, 15, tzinfo=timezone.utc),
    cheapest_price=1.0,
):
    row = MagicMock()
    row.upcoming_count = upcoming_count
    row.venue_count = venue_count
    row.furthest_date = furthest_date
    row.cheapest_price = cheapest_price
    return row


def _showcase_db(mock_db, events):
    """Serve `events` to both showcase queries: the slim window rows, then
    the hydration of the winners."""
    mock_db.execute.return_value.all.return_value = [
        SimpleNamespace(
            id=e.id,
            title_orig=e.title_orig,
            starts_at=e.starts_at,
            quality_score=e.classification.quality_score,
            venue_name=e.venue_name,
            linked_name=None,
            linked_name_en=None,
            linked_name_ru=None,
        )
        for e in events
    ]
    mock_db.scalars.return_value = _scalars_result(events)


class TestShowcase:
    @pytest.mark.asyncio
    async def test_one_query_warms_every_locale(self, mock_db, make_event, make_request):
        from app.routers.public import showcase

        _showcase_db(mock_db, [make_event(1, title="One")])

        await showcase(request=make_request(), locale="en", db=mock_db)
        await showcase(request=make_request(), locale="ru", db=mock_db)
        await showcase(request=make_request(), locale="et", db=mock_db)

        assert mock_db.execute.call_count == 1
        assert mock_db.scalars.call_count == 1

    @pytest.mark.asyncio
    async def test_returns_serialized_events(self, mock_db, make_event, make_request):
        from app.routers.public import showcase

        _showcase_db(
            mock_db,
            [make_event(1, title="Event One"), make_event(2, title="Event Two")]
        )

        result = await showcase(request=make_request(), locale="en", db=mock_db)

        assert [e["id"] for e in result["events"]] == [1, 2]

    @pytest.mark.asyncio
    async def test_no_user_signals_hydrated(self, mock_db, make_event, make_request):
        from app.routers.public import showcase

        _showcase_db(mock_db, [make_event(1)])

        result = await showcase(request=make_request(), locale="en", db=mock_db)

        # Anonymous endpoint — serialize_event called without feedback context.
        assert result["events"][0]["my_signal"] is None

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, mock_db, make_request):
        from app.routers.public import showcase

        _showcase_db(mock_db, [])

        result = await showcase(request=make_request(), locale="en", db=mock_db)

        assert result["events"] == []
        mock_db.scalars.assert_not_awaited()  # nothing to hydrate

    @pytest.mark.asyncio
    async def test_invalid_locale_falls_back(self, mock_db, make_event, make_request):
        from app.routers.public import showcase

        _showcase_db(mock_db, [make_event(1)])

        # A bogus locale must not raise — it degrades to the default locale.
        result = await showcase(request=make_request(), locale="zz", db=mock_db)

        assert [e["id"] for e in result["events"]] == [1]

    @pytest.mark.asyncio
    async def test_thin_pool_is_single_query(
        self, mock_db, make_event, make_request
    ):
        """A thin pool (fewer than SHOWCASE_EVENT_COUNT candidates even across the
        full fallback window) no longer triggers a second query — one query over
        the wider window, ordered/limited by the DB, replaces the old two-query
        narrow-then-fallback shape."""
        from app.routers.public import showcase

        _showcase_db(
            mock_db,
            [make_event(1, title="Event One"), make_event(2, title="Event Two")]
        )

        result = await showcase(request=make_request(), locale="en", db=mock_db)

        assert len(result["events"]) == 2
        assert mock_db.execute.await_count == 1
        assert mock_db.scalars.await_count == 1

    @pytest.mark.asyncio
    async def test_full_week_is_single_query(
        self, mock_db, make_event, make_request
    ):
        from app.constants.events import SHOWCASE_EVENT_COUNT
        from app.routers.public import showcase

        _showcase_db(
            mock_db,
            [
                make_event(i, title=f"Event {i}")
                for i in range(1, SHOWCASE_EVENT_COUNT + 1)
            ]
        )

        result = await showcase(request=make_request(), locale="en", db=mock_db)

        assert len(result["events"]) == SHOWCASE_EVENT_COUNT
        assert mock_db.execute.await_count == 1
        assert mock_db.scalars.await_count == 1

    @pytest.mark.asyncio
    async def test_recurring_series_collapses_to_one_instance(
        self, mock_db, make_event, make_request
    ):
        """A multi-date listing (e.g. a workshop running Tue/Thu/Sat) ingests as
        several rows sharing an event_series_key but distinct dedup_group_ids —
        recurring series are intentionally not dedup-grouped across days — so
        without the showcase's own collapse, each date-instance could
        independently qualify for the grid and the same title would appear
        more than once (see collapse_series_duplicates)."""
        from app.routers.public import showcase

        earlier = make_event(
            1,
            title="I Didn't Leave Ukraine",
            venue_name="Kanuti Gildi SAAL",
            starts_at=datetime(2026, 9, 5, 19, 0, 0, tzinfo=timezone.utc),
        )
        later = make_event(
            2,
            title="I Didn't Leave Ukraine",
            venue_name="Kanuti Gildi SAAL",
            starts_at=datetime(2026, 9, 10, 19, 0, 0, tzinfo=timezone.utc),
        )
        _showcase_db(mock_db, [earlier, later])

        result = await showcase(request=make_request(), locale="en", db=mock_db)

        assert [e["id"] for e in result["events"]] == [1]

    def test_query_prefers_narrow_window_but_bounds_wide(self):
        from datetime import datetime, timezone

        from app.routers.public import _showcase_stmt

        now = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)
        sql = str(_showcase_stmt(now).compile(compile_kwargs={"literal_binds": True}))

        # Bounded on both sides at the wide (fallback) window — a single query,
        # not two.
        assert "starts_at <" in sql
        assert "starts_at >=" in sql
        # A CASE expression orders "this week" candidates ahead of wider-window
        # ones, so narrowing only changes results when the narrow week can't
        # fill the grid on its own (see _showcase_stmt docstring).
        assert "CASE" in sql.upper()


class TestPrerenderEvents:
    @pytest.mark.asyncio
    async def test_returns_id_and_updated_at(self, mock_db, make_request):
        from datetime import datetime, timezone

        from app.routers.public import prerender_events

        rows = [
            (1, datetime(2026, 8, 1, tzinfo=timezone.utc)),
            (2, datetime(2026, 8, 2, tzinfo=timezone.utc)),
        ]
        execute_result = MagicMock()
        execute_result.all.return_value = rows
        mock_db.execute.return_value = execute_result

        result = await prerender_events(request=make_request(), db=mock_db)

        assert result == {
            "events": [
                {"id": 1, "updated_at": "2026-08-01T00:00:00+00:00"},
                {"id": 2, "updated_at": "2026-08-02T00:00:00+00:00"},
            ]
        }

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, mock_db, make_request):
        from app.routers.public import prerender_events

        execute_result = MagicMock()
        execute_result.all.return_value = []
        mock_db.execute.return_value = execute_result

        result = await prerender_events(request=make_request(), db=mock_db)

        assert result == {"events": []}

    def test_query_filters_published_canonical_not_ended(self):
        from datetime import datetime, timezone

        from app.routers.public import _prerender_event_ids_stmt

        now = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)
        sql = str(
            _prerender_event_ids_stmt(now).compile(compile_kwargs={"literal_binds": True})
        )

        assert "status" in sql
        assert "is_explicit" in sql
        assert "is_non_event" in sql
        assert "dedup_group_id" in sql
        assert "ends_at" in sql or "starts_at" in sql


class TestAggregatesStmtVenueCount:
    """#176: a venue-linked event leaves Event.venue_name NULL, so the
    distinct-venue count must coalesce over the linked Venue's name or a
    Postgres COUNT(DISTINCT ...) silently drops every organizer saved venue
    (NULLs are excluded from DISTINCT)."""

    def test_counts_over_coalesced_venue_name(self):
        from app.routers.public import _aggregates_stmt

        now = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)
        sql = str(_aggregates_stmt(now).compile(compile_kwargs={"literal_binds": True}))

        assert "coalesce" in sql.lower()
        assert "venues" in sql.lower()
        assert "JOIN venues" in sql or "LEFT OUTER JOIN venues" in sql


class TestTodayCountStmt:
    """#508: the pulse chip counts exactly what /explore?date=today lands on —
    same filters plus the shared overlap predicate, so an ongoing exhibition
    counts and an ended/duplicate/unpublished event does not."""

    def _sql(self):
        from app.routers.public import _today_count_stmt

        now = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)
        return str(_today_count_stmt(now).compile(compile_kwargs={"literal_binds": True}))

    def test_uses_overlap_predicate_so_ongoing_exhibitions_count(self):
        sql = self._sql().lower()
        assert "events.starts_at <" in sql
        assert "coalesce(events.ends_at, events.starts_at) >=" in sql
        # Not the aggregates' starts_at >= now bound, which drops ongoing runs.
        assert "events.starts_at >=" not in sql

    def test_excludes_ended_duplicates_and_unpublished(self):
        sql = self._sql()
        assert "events.status" in sql
        assert "is_explicit" in sql
        assert "is_non_event" in sql
        assert "dedup_group_id" in sql
        assert "coalesce(events.ends_at, events.starts_at) >=" in sql.lower()

    def test_is_an_exact_count_not_capped(self):
        sql = self._sql().lower()
        assert "count(events.id)" in sql
        assert "limit" not in sql


class TestSharedDateRangeFilter:
    def test_browse_and_public_share_the_queries_module_predicate(self):
        import app.routers.browse as browse
        import app.routers.public as public
        from app.events.queries import event_date_range_filter, facet_conditions

        # Browse builds its date predicate through the moved facet builder.
        assert browse.facet_conditions is facet_conditions
        assert public.event_date_range_filter is event_date_range_filter


class TestCounts:
    @pytest.mark.asyncio
    async def test_today_count_in_payload_and_tonight_unchanged(self, mock_db, make_event, make_request):
        import app.routers.public as public_module
        from app.routers.public import counts

        public_module._counts_cache.clear()
        mock_db.execute.return_value.one.return_value = _agg_row()
        mock_db.scalar.return_value = 37
        mock_db.scalars.return_value = _scalars_result([make_event(1, title="Tonight Show")])

        result = await counts(request=make_request(), locale="en", db=mock_db)

        assert result["today_count"] == 37
        assert result["tonight_is_fallback"] is False
        assert [e["title"] for e in result["tonight_events"]] == ["Tonight Show"]

    @pytest.mark.asyncio
    async def test_today_count_is_exact_above_tonight_cap(self, mock_db, make_event, make_request):
        import app.routers.public as public_module
        from app.routers.public import counts

        public_module._counts_cache.clear()
        mock_db.execute.return_value.one.return_value = _agg_row()
        mock_db.scalar.return_value = 57
        mock_db.scalars.return_value = _scalars_result([make_event(1)])

        result = await counts(request=make_request(), locale="en", db=mock_db)

        assert result["today_count"] == 57
    @pytest.mark.asyncio
    async def test_returns_payload_shape(self, mock_db, make_event, make_request):
        import app.routers.public as public_module
        from app.routers.public import counts

        public_module._counts_cache.clear()
        mock_db.execute.return_value.one.return_value = _agg_row()
        mock_db.scalars.return_value = _scalars_result([make_event(1, title="Tonight Show")])

        result = await counts(request=make_request(), locale="en", db=mock_db)

        assert result["upcoming_count"] == 1008
        assert result["venue_count"] == 205
        assert result["furthest_date"] == "2027-01-15"
        assert result["cheapest_price"] == 1.0
        assert result["tonight_is_fallback"] is False
        assert result["tonight_events"] == [
            {"title": "Tonight Show", "starts_at": "2026-05-15T18:00:00+00:00", "venue_name": "Test Venue"}
        ]

    @pytest.mark.asyncio
    async def test_empty_tonight_falls_back_to_wider_window(self, mock_db, make_event, make_request):
        import app.routers.public as public_module
        from app.routers.public import counts

        public_module._counts_cache.clear()
        mock_db.execute.return_value.one.return_value = _agg_row()
        # First db.scalars() call (tonight) returns empty, second (fallback) returns events.
        mock_db.scalars.side_effect = [
            _scalars_result([]),
            _scalars_result([make_event(2, title="Later This Week")]),
        ]

        result = await counts(request=make_request(), locale="en", db=mock_db)

        assert result["tonight_is_fallback"] is True
        assert [e["title"] for e in result["tonight_events"]] == ["Later This Week"]
        assert mock_db.scalars.await_count == 2

    @pytest.mark.asyncio
    async def test_no_price_min_positive_returns_none(self, mock_db, make_request):
        import app.routers.public as public_module
        from app.routers.public import counts

        public_module._counts_cache.clear()
        mock_db.execute.return_value.one.return_value = _agg_row(cheapest_price=None, furthest_date=None)
        mock_db.scalars.return_value = _scalars_result([])

        result = await counts(request=make_request(), locale="en", db=mock_db)

        assert result["cheapest_price"] is None
        assert result["furthest_date"] is None

    @pytest.mark.asyncio
    async def test_second_call_within_ttl_hits_cache_not_db(self, mock_db, make_event, make_request):
        import app.routers.public as public_module
        from app.routers.public import counts

        public_module._counts_cache.clear()
        mock_db.execute.return_value.one.return_value = _agg_row()
        mock_db.scalars.return_value = _scalars_result([make_event(1)])

        first = await counts(request=make_request(), locale="en", db=mock_db)
        assert mock_db.execute.await_count == 1

        second = await counts(request=make_request(), locale="en", db=mock_db)

        assert second == first
        # No further DB hit — served from the in-process TTL cache.
        assert mock_db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_cache_is_keyed_per_locale(self, mock_db, make_event, make_request):
        import app.routers.public as public_module
        from app.routers.public import counts

        public_module._counts_cache.clear()
        mock_db.execute.return_value.one.return_value = _agg_row()
        mock_db.scalars.return_value = _scalars_result([make_event(1)])

        await counts(request=make_request(), locale="en", db=mock_db)
        await counts(request=make_request(), locale="ru", db=mock_db)

        assert mock_db.execute.await_count == 2


class TestShowcaseRealDb:
    """The slim window query, collapse and winner hydration against Postgres.
    Dates sit in 2090 so nothing else in the database falls in the window."""

    NOW = datetime(2090, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    async def _event(self, make, *, quality, days, **kw):
        from datetime import timedelta

        from app.models.models import EventClassification

        ev = await make.event(starts_at=self.NOW + timedelta(days=days), ends_at=None, **kw)
        make.db.add(
            EventClassification(event_id=ev.id, categories=["music"], vibes=[], quality_score=quality)
        )
        await make.db.flush()
        return ev

    @pytest.mark.asyncio
    async def test_query_count_is_fixed_and_winners_ranked(self, db, make):
        from app.constants.events import SHOWCASE_EVENT_COUNT
        from app.routers.public import _load_showcase
        from tests.conftest import count_statements

        events = [
            await self._event(make, quality=i / 20, days=1 + i % 3)
            for i in range(SHOWCASE_EVENT_COUNT * 2)
        ]
        db.expunge_all()

        with count_statements(db) as statements:
            payloads = await _load_showcase(db, self.NOW)

        # Window query, winner hydration, and its classification selectinload
        # (no linked venues here, so the venue selectinload has nothing to load).
        assert len(statements) == 3
        expected = sorted(events, key=lambda e: -e.id)[:SHOWCASE_EVENT_COUNT]
        assert [e["id"] for e in payloads["en"]["events"]] == [e.id for e in expected]

    @pytest.mark.asyncio
    async def test_venue_linked_series_collapses_to_earliest(self, db, make):
        from app.routers.public import _load_showcase

        venue = await make.venue(await make.organizer(), name="Kanuti Gildi SAAL")
        series = {"title_orig": "Workshop", "venue_id": venue.id}
        later = await self._event(make, quality=0.9, days=3, **series)
        earlier = await self._event(make, quality=0.1, days=1, **series)
        db.expunge_all()

        payloads = await _load_showcase(db, self.NOW)

        ids = [e["id"] for e in payloads["en"]["events"]]
        assert ids == [earlier.id]
        assert later.id not in ids
        assert payloads["en"]["events"][0]["venue_name"] == "Kanuti Gildi SAAL"
