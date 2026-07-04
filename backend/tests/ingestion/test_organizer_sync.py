"""Unit tests for Fienta organizer lifecycle (app/ingestion/organizer_sync.py)."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.constants import (
    SOURCE_KIND_API,
    SOURCE_SLUG_FIENTA,
    STALE_ORGANIZER_RETIRE_DAYS,
    TALLINN_TZ,
)
from app.ingestion.organizer_sync import sync_fienta_organizers
from app.models.models import Source


def _source(config: dict) -> Source:
    return Source(
        slug=SOURCE_SLUG_FIENTA, kind=SOURCE_KIND_API, config=config, enabled=True
    )


def _resp(events: list[dict]) -> AsyncMock:
    r = AsyncMock()
    r.json = lambda: {"events": events}
    return r


@pytest.mark.asyncio
async def test_no_fienta_source_returns_empty_dict(mock_db):
    mock_db.scalar.return_value = None

    result = await sync_fienta_organizers(mock_db)

    assert result == {}


@pytest.mark.asyncio
async def test_newly_stale_organizer_records_stale_since(mock_db):
    source = _source({"organizer_ids": [42], "organizer_names": {"42": "Dead Org"}})
    mock_db.scalar.return_value = source

    with patch(
        "app.ingestion.organizer_sync.http_get",
        new_callable=AsyncMock,
        side_effect=[_resp([]), _resp([])],  # organizer probe, then discovery scan
    ):
        result = await sync_fienta_organizers(mock_db)

    assert 42 in result["stale"]
    assert "42" in source.config["stale_since"]
    assert 42 in source.config["organizer_ids"]  # not retired yet
    assert 42 not in source.config.get("retired_organizer_ids", [])


@pytest.mark.asyncio
async def test_revived_organizer_clears_stale_since(mock_db):
    since = datetime.now(tz=TALLINN_TZ).isoformat()
    source = _source(
        {
            "organizer_ids": [42],
            "organizer_names": {"42": "Org"},
            "stale_since": {"42": since},
            "stale_organizer_ids": [42],
        }
    )
    mock_db.scalar.return_value = source

    with patch(
        "app.ingestion.organizer_sync.http_get",
        new_callable=AsyncMock,
        side_effect=[_resp([{"id": 1}]), _resp([])],  # organizer now has events
    ):
        result = await sync_fienta_organizers(mock_db)

    assert 42 not in result["stale"]
    assert "42" not in source.config["stale_since"]
    assert 42 not in source.config["stale_organizer_ids"]


@pytest.mark.asyncio
async def test_retirement_after_grace_period(mock_db):
    long_ago = (
        datetime.now(tz=TALLINN_TZ) - timedelta(days=STALE_ORGANIZER_RETIRE_DAYS + 1)
    ).isoformat()
    source = _source(
        {
            "organizer_ids": [42],
            "organizer_names": {"42": "Long Dead Org"},
            "stale_since": {"42": long_ago},
            "stale_organizer_ids": [42],
        }
    )
    mock_db.scalar.return_value = source

    with patch(
        "app.ingestion.organizer_sync.http_get",
        new_callable=AsyncMock,
        side_effect=[_resp([]), _resp([])],  # still 0 events
    ):
        result = await sync_fienta_organizers(mock_db)

    assert 42 in result["retired"]
    assert 42 not in source.config["organizer_ids"]
    assert 42 in source.config["retired_organizer_ids"]
    assert "42" not in source.config["stale_since"]
    assert 42 not in source.config["stale_organizer_ids"]


@pytest.mark.asyncio
async def test_http_error_preserves_prior_stale_since(mock_db):
    since = datetime.now(tz=TALLINN_TZ).isoformat()
    source = _source(
        {
            "organizer_ids": [42],
            "organizer_names": {"42": "Org"},
            "stale_since": {"42": since},
            "stale_organizer_ids": [42],
        }
    )
    mock_db.scalar.return_value = source

    with patch(
        "app.ingestion.organizer_sync.http_get",
        new_callable=AsyncMock,
        side_effect=[httpx.ConnectError("boom"), _resp([])],
    ):
        result = await sync_fienta_organizers(mock_db)

    # Transient error: stale_since entry must survive unchanged (not cleared).
    assert source.config["stale_since"]["42"] == since
    assert 42 in result["stale"]


@pytest.mark.asyncio
async def test_discovery_revives_retired_organizer(mock_db):
    source = _source(
        {
            "organizer_ids": [],
            "organizer_names": {},
            "retired_organizer_ids": [99],
        }
    )
    mock_db.scalar.return_value = source

    discovery_events = [{"organizer_id": 99, "organizer_name": "Reborn Org"}] * 5
    with patch(
        "app.ingestion.organizer_sync.http_get",
        new_callable=AsyncMock,
        side_effect=[_resp(discovery_events)],  # no organizer probes (empty list)
    ):
        result = await sync_fienta_organizers(mock_db)

    assert (99, "Reborn Org") in result["added"]
    assert 99 in source.config["organizer_ids"]
    assert 99 not in source.config["retired_organizer_ids"]
