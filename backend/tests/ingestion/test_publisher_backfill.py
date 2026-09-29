"""Unit tests for the one-time publisher backfill (#409/#411) —
app/ingestion/publisher_backfill.py. Scoping (claimable events only) and
batch discipline (bulk-load, fixed query count) are the acceptance criteria
under test here."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants import (
    SOURCE_KIND_API,
    SOURCE_KIND_HTML_SCRAPE,
    SOURCE_SLUG_ESTONIA_CONCERT_HALL,
    SOURCE_SLUG_FIENTA,
    SOURCE_SLUG_KUMU,
)
from app.ingestion.publisher_backfill import (
    _raw_organizer_by_external_id,
    backfill_publisher_ids,
)
from app.models.models import EventSource, Source


def _source(slug: str, id_: int, kind: str = SOURCE_KIND_API, config: dict | None = None) -> Source:
    return Source(id=id_, slug=slug, kind=kind, config=config or {}, enabled=True)


@pytest.mark.asyncio
async def test_no_target_sources_returns_empty_dict(mock_db):
    mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

    result = await backfill_publisher_ids(mock_db)

    assert result == {}


class TestFientaBackfill:
    @pytest.mark.asyncio
    async def test_matches_claimable_event_source_via_live_requery(self, mock_db):
        """Live re-query (organizer listing, stamped with organizer_id by the
        #411 fix) resolves a claimable event_sources row's publisher_id — not
        a replay of raw_events.payload history."""
        fienta = _source(SOURCE_SLUG_FIENTA, id_=1, config={"organizer_ids": [42]})
        claimable = EventSource(event_id=10, source_id=1, external_id="100", publisher_id=None)

        mock_db.scalars.side_effect = [
            MagicMock(all=MagicMock(return_value=[fienta])),  # sources lookup
            MagicMock(all=MagicMock(return_value=[claimable])),  # claimable event_sources
        ]
        mock_db.execute.return_value.all.return_value = [("42", 7)]  # publisher lookup

        with (
            patch(
                "app.ingestion.publisher_backfill._raw_organizer_by_external_id",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.ingestion.publisher_backfill.FientaAdapter.fetch_organizer",
                new_callable=AsyncMock,
                return_value=[{"id": "100", "organizer_id": 42}],
            ),
        ):
            result = await backfill_publisher_ids(mock_db)

        assert result[SOURCE_SLUG_FIENTA] == 1
        assert claimable.publisher_id == 7

    @pytest.mark.asyncio
    async def test_raw_events_stamp_resolves_without_live_requery(self, mock_db):
        """A raw_events organizer_id stamp resolves the row in SQL; the live
        organizer crawl never fires when nothing is left unresolved."""
        fienta = _source(SOURCE_SLUG_FIENTA, id_=1, config={"organizer_ids": [42]})
        claimable = EventSource(event_id=10, source_id=1, external_id="100", publisher_id=None)
        mock_db.scalars.side_effect = [
            MagicMock(all=MagicMock(return_value=[fienta])),
            MagicMock(all=MagicMock(return_value=[claimable])),
        ]
        mock_db.execute.return_value.all.return_value = [("42", 7)]

        with (
            patch(
                "app.ingestion.publisher_backfill._raw_organizer_by_external_id",
                new_callable=AsyncMock,
                return_value={"100": 42},
            ),
            patch(
                "app.ingestion.publisher_backfill.FientaAdapter.fetch_organizer",
                new_callable=AsyncMock,
            ) as mock_fetch,
        ):
            result = await backfill_publisher_ids(mock_db)

        mock_fetch.assert_not_awaited()
        assert result[SOURCE_SLUG_FIENTA] == 1
        assert claimable.publisher_id == 7

    @pytest.mark.asyncio
    async def test_no_claimable_event_sources_skips_the_live_requery(self, mock_db):
        """No claimable rows for this source → the (potentially expensive)
        organizer re-query never fires."""
        fienta = _source(SOURCE_SLUG_FIENTA, id_=1, config={"organizer_ids": [42]})
        mock_db.scalars.side_effect = [
            MagicMock(all=MagicMock(return_value=[fienta])),
            MagicMock(all=MagicMock(return_value=[])),
        ]

        with patch(
            "app.ingestion.publisher_backfill.FientaAdapter.fetch_organizer",
            new_callable=AsyncMock,
        ) as mock_fetch:
            result = await backfill_publisher_ids(mock_db)

        mock_fetch.assert_not_awaited()
        assert result[SOURCE_SLUG_FIENTA] == 0

    @pytest.mark.asyncio
    async def test_unmatched_external_id_left_unresolved(self, mock_db):
        """A claimable row whose external_id isn't in the fresh listing
        (e.g. the organizer since removed it) is left publisher_id=None,
        not counted as updated."""
        fienta = _source(SOURCE_SLUG_FIENTA, id_=1, config={"organizer_ids": [42]})
        claimable = EventSource(event_id=10, source_id=1, external_id="gone", publisher_id=None)

        mock_db.scalars.side_effect = [
            MagicMock(all=MagicMock(return_value=[fienta])),
            MagicMock(all=MagicMock(return_value=[claimable])),
        ]
        mock_db.execute.return_value.all.return_value = [("42", 7)]

        with patch(
            "app.ingestion.publisher_backfill.FientaAdapter.fetch_organizer",
            new_callable=AsyncMock,
            return_value=[{"id": "100", "organizer_id": 42}],
        ):
            result = await backfill_publisher_ids(mock_db)

        assert result[SOURCE_SLUG_FIENTA] == 0
        assert claimable.publisher_id is None


class TestConstantPublisherBackfill:
    @pytest.mark.asyncio
    async def test_kumu_update_scoped_via_seeded_publisher(self, mock_db):
        kumu = _source(SOURCE_SLUG_KUMU, id_=2, kind=SOURCE_KIND_HTML_SCRAPE)
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[kumu]))
        update_result = MagicMock(rowcount=4)
        mock_db.execute.side_effect = [
            MagicMock(all=MagicMock(return_value=[(None, 9)])),  # load_publisher_lookup
            update_result,  # the UPDATE
        ]

        result = await backfill_publisher_ids(mock_db)

        assert result[SOURCE_SLUG_KUMU] == 4

    @pytest.mark.asyncio
    async def test_zero_when_no_seeded_publisher(self, mock_db):
        """seed_publishers() hasn't run yet for this source — skip rather
        than guess a publisher_id."""
        ech = _source(SOURCE_SLUG_ESTONIA_CONCERT_HALL, id_=3, kind=SOURCE_KIND_HTML_SCRAPE)
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[ech]))
        mock_db.execute.return_value.all.return_value = []  # no seeded Publisher row

        result = await backfill_publisher_ids(mock_db)

        assert result[SOURCE_SLUG_ESTONIA_CONCERT_HALL] == 0
        # Only the lookup SELECT fired — never an UPDATE with no publisher_id.
        assert mock_db.execute.await_count == 1


@pytest.mark.asyncio
async def test_raw_organizer_lookup_skips_non_integer_stamps(mock_db):
    mock_db.execute.return_value.all.return_value = [("1", "42"), ("2", "junk")]

    result = await _raw_organizer_by_external_id(mock_db, 1, ["1", "2"])

    assert result == {"1": 42}
