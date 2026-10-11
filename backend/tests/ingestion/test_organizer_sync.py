"""Unit tests for Fienta organizer lifecycle (app/ingestion/organizer_sync.py)."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.constants import (
    PUBLISHER_STATUS_ACTIVE,
    PUBLISHER_STATUS_RETIRED,
    SOURCE_KIND_API,
    SOURCE_SLUG_FIENTA,
    STALE_ORGANIZER_RETIRE_DAYS,
    TALLINN_TZ,
)
from app.ingestion.organizer_sync import sync_fienta_organizers
from app.models.models import Publisher, Source


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


# ---------------------------------------------------------------------------
# Publisher mirroring (#409/#411) — sources.config stays the ingestion
# filter; publishers is a read mirror of it.
# ---------------------------------------------------------------------------


def _added_publishers(mock_db) -> list[Publisher]:
    return [
        c.args[0] for c in mock_db.add.call_args_list if isinstance(c.args[0], Publisher)
    ]


@pytest.mark.asyncio
async def test_publisher_mirrored_for_active_organizer(mock_db):
    source = _source({"organizer_ids": [42], "organizer_names": {"42": "Org A"}})
    source.id = 7
    mock_db.scalar.return_value = source

    with patch(
        "app.ingestion.organizer_sync.http_get",
        new_callable=AsyncMock,
        side_effect=[_resp([{"id": 1}]), _resp([])],
    ):
        await sync_fienta_organizers(mock_db)

    added = _added_publishers(mock_db)
    assert len(added) == 1
    assert added[0].source_id == 7
    assert added[0].external_id == "42"
    assert added[0].name == "Org A"
    assert added[0].status == PUBLISHER_STATUS_ACTIVE


@pytest.mark.asyncio
async def test_publisher_mirrored_as_retired(mock_db):
    """A newly-retired organizer's mirrored Publisher status flips to retired,
    it is never deleted (claims may still reference it)."""
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
    source.id = 7
    mock_db.scalar.return_value = source

    with patch(
        "app.ingestion.organizer_sync.http_get",
        new_callable=AsyncMock,
        side_effect=[_resp([]), _resp([])],
    ):
        await sync_fienta_organizers(mock_db)

    added = _added_publishers(mock_db)
    assert len(added) == 1
    assert added[0].external_id == "42"
    assert added[0].status == PUBLISHER_STATUS_RETIRED


@pytest.mark.asyncio
async def test_existing_publisher_updated_not_duplicated(mock_db):
    """An organizer already mirrored as a Publisher gets its row updated in
    place, not re-inserted."""
    source = _source({"organizer_ids": [42], "organizer_names": {"42": "New Name"}})
    source.id = 7
    mock_db.scalar.return_value = source

    existing_publisher = Publisher(
        source_id=7, external_id="42", name="Old Name", status=PUBLISHER_STATUS_ACTIVE
    )
    execute_result = MagicMock()
    execute_result.scalars.return_value = MagicMock(
        all=MagicMock(return_value=[existing_publisher])
    )
    mock_db.execute.return_value = execute_result

    with patch(
        "app.ingestion.organizer_sync.http_get",
        new_callable=AsyncMock,
        side_effect=[_resp([{"id": 1}]), _resp([])],
    ):
        await sync_fienta_organizers(mock_db)

    assert _added_publishers(mock_db) == []
    assert existing_publisher.name == "New Name"
    assert existing_publisher.status == PUBLISHER_STATUS_ACTIVE


@pytest.mark.asyncio
async def test_connection_released_before_http_phase(mock_db):
    source = _source({"organizer_ids": [42], "organizer_names": {"42": "Org"}})
    mock_db.scalar.return_value = source
    order: list[str] = []
    mock_db.rollback.side_effect = lambda: order.append("rollback")

    async def fake_get(*_a, **_k):
        order.append("http")
        return _resp([{"id": 1}])

    with patch("app.ingestion.organizer_sync.http_get", side_effect=fake_get):
        await sync_fienta_organizers(mock_db)

    assert order[0] == "rollback"
    assert "http" in order[1:]


@pytest.mark.asyncio
async def test_write_retried_once_on_invalidated_connection(mock_db):
    from sqlalchemy.exc import DBAPIError

    source = _source({"organizer_ids": [42], "organizer_names": {"42": "Org"}})
    mock_db.scalar.return_value = source
    dropped = DBAPIError("UPDATE", {}, Exception("server closed"), connection_invalidated=True)
    mock_db.flush.side_effect = [dropped, None]

    with patch(
        "app.ingestion.organizer_sync.http_get",
        new_callable=AsyncMock,
        side_effect=[_resp([{"id": 1}]), _resp([])],
    ):
        result = await sync_fienta_organizers(mock_db)

    assert result["stale"] == []
    assert mock_db.flush.await_count == 2
    assert "last_sync" in source.config


@pytest.mark.asyncio
async def test_non_connection_db_error_not_retried(mock_db):
    from sqlalchemy.exc import DBAPIError

    source = _source({"organizer_ids": [42], "organizer_names": {"42": "Org"}})
    mock_db.scalar.return_value = source
    mock_db.flush.side_effect = DBAPIError("UPDATE", {}, Exception("constraint"))

    with patch(
        "app.ingestion.organizer_sync.http_get",
        new_callable=AsyncMock,
        side_effect=[_resp([{"id": 1}]), _resp([])],
    ):
        with pytest.raises(DBAPIError):
            await sync_fienta_organizers(mock_db)

    assert mock_db.flush.await_count == 1


@pytest.mark.asyncio
async def test_write_preserves_concurrent_config_keys(mock_db):
    first = _source({"organizer_ids": [42], "organizer_names": {"42": "Org"}})
    fresh = _source(
        {"organizer_ids": [42], "organizer_names": {"42": "Org"}, "admin_note": "keep"}
    )
    mock_db.scalar.side_effect = [first, fresh]

    with patch(
        "app.ingestion.organizer_sync.http_get",
        new_callable=AsyncMock,
        side_effect=[_resp([{"id": 1}]), _resp([])],
    ):
        await sync_fienta_organizers(mock_db)

    assert fresh.config["admin_note"] == "keep"
    assert "last_sync" in fresh.config
