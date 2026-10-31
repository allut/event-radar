"""Unit tests for app.claims.target_resolution.bulk_resolve_publisher_events."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.claims.target_resolution import bulk_resolve_publisher_events


class TestBulkResolvePublisherEvents:
    """Shared by admin.py::admin_list_claims and
    app.claims.lifecycle._send_claim_expiry_emails (#421) — two fixed
    queries regardless of how many publisher_ids are passed, freshest
    EventSource (highest id) wins per publisher."""

    @pytest.mark.asyncio
    async def test_empty_input_short_circuits_with_no_queries(self, mock_db):
        result = await bulk_resolve_publisher_events(mock_db, set())

        assert result == {}
        mock_db.scalars.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_freshest_event_source_wins_per_publisher(self, mock_db, make_event):
        event = make_event(event_id=2)
        # DISTINCT ON (publisher_id) ORDER BY id DESC — one (publisher_id,
        # event_id) row per publisher, the freshest listing's.
        mock_db.execute = AsyncMock(
            return_value=MagicMock(all=MagicMock(return_value=[(99, 2)]))
        )
        mock_db.scalars = AsyncMock(
            side_effect=[MagicMock(all=MagicMock(return_value=[event]))]
        )

        result = await bulk_resolve_publisher_events(mock_db, {99})

        assert result == {99: event}

    @pytest.mark.asyncio
    async def test_no_matching_event_sources_returns_empty(self, mock_db):
        mock_db.execute = AsyncMock(
            return_value=MagicMock(all=MagicMock(return_value=[]))
        )

        result = await bulk_resolve_publisher_events(mock_db, {99})

        assert result == {}
